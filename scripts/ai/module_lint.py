#!/usr/bin/env python3
"""module_lint.py - enforce small modules with explicit public interfaces (stdlib only).

ERRORS (fail CI):
  * a NEW source file (added since --base) exceeds the size budget
    (module_max_lines / module_max_symbols in .ai/config.yml; defaults 300 / 10)
  * a NEW import line reaches into another module's internals instead of its
    public interface:
      JS/TS  - a relative or '@/' import resolving to a file inside a directory
               that has an index.(ts|tsx|js|jsx|mjs) when the importer lives
               outside that directory (import the directory/index instead)
      Python - importing a '_private' submodule of a package from outside it
WARNINGS (GitHub annotations, never fail):
  * existing files over budget (legacy code must not freeze the repo)
  * existing deep imports
  * files that look like they mix concerns (db + payments + auth + routing + AI)
Test files, guardrail files and ignore_globs are exempt.

Usage: module_lint.py [--base origin/main]   (no --base = audit, warnings only)
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
sys.dont_write_bytecode = True  # never leave __pycache__ in the repo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import aiconfig  # noqa: E402
import pathrules  # noqa: E402
import editlint  # noqa: E402

SRC_EXT = (".py",) + editlint.JS_EXT
INDEX_NAMES = ("index.ts", "index.tsx", "index.js", "index.jsx", "index.mjs", "index.mts")
RESOLVE_EXT = ("", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".mts", ".cjs", ".d.ts")
JS_IMPORT = re.compile(r"""(?:^|\s)(?:import|export)\s[^'"]*?from\s*['"]([^'"]+)['"]|(?:import|require)\(\s*['"]([^'"]+)['"]\s*\)|^\s*import\s+['"]([^'"]+)['"]""")
CONCERNS = {
    "db": re.compile(r"\b(D1Database|drizzle|prisma|\.prepare\(|SELECT\s|INSERT\s+INTO|sqlalchemy|sqlite3)\b"),
    "payments": re.compile(r"\b(stripe|Stripe)\b"),
    "auth": re.compile(r"(@clerk/|\bclerk\b|verifyToken|jwt\.|jsonwebtoken)"),
    "routing": re.compile(r"\b(new Hono|Hono\(|express\(\)|Router\(|app\.(get|post|put|delete)\(|itty-router|APIRouter|FastAPI\()"),
    "ai": re.compile(r"(\bAI\.run\(|@cf/|openai|anthropic|generativelanguage|workers-ai)"),
}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def tracked_sources(config_path: str) -> list[str]:
    out = []
    for p in git("ls-files").splitlines():
        if p.endswith(SRC_EXT) and not p.endswith(".d.ts") and pathrules.classify(p, config_path) == "code" \
                and not pathrules.is_ignored(p, config_path) and os.path.isfile(p):
            out.append(p)
    return out


def count_symbols(path: str, text: str) -> int:
    syms = editlint.symbols_for(path, text) or {}
    return len([s for s in syms if s != editlint.PREAMBLE and not s.startswith("<stmt")])


def alias_root(importer: str) -> str | None:
    d = os.path.dirname(importer)
    while True:
        tsc = os.path.join(d, "tsconfig.json") if d else "tsconfig.json"
        if os.path.isfile(tsc):
            with open(tsc, encoding="utf-8", errors="replace") as fh:
                m = re.search(r'"@/\*"\s*:\s*\[\s*"([^"*]*)\*?"', fh.read())
            if m:
                return os.path.normpath(os.path.join(d, m.group(1)))
            return None
        if not d:
            return None
        d = os.path.dirname(d)


def resolve(importer: str, spec: str) -> str | None:
    if spec.startswith("."):
        base = os.path.normpath(os.path.join(os.path.dirname(importer), spec))
    elif spec.startswith("@/"):
        root = alias_root(importer)
        if root is None:
            return None
        base = os.path.normpath(os.path.join(root, spec[2:]))
    else:
        return None
    stems = [base]
    m = re.match(r"^(.*)\.(m?js|jsx)$", base)
    if m:  # ESM TypeScript writes './foo.js' for foo.ts
        stems.append(m.group(1))
    for stem in stems:
        for ext in RESOLVE_EXT:
            if os.path.isfile(stem + ext):
                return stem + ext
    for name in INDEX_NAMES:
        cand = os.path.join(base, name)
        if os.path.isfile(cand):
            return cand
    return None


def inside(path: str, directory: str) -> bool:
    directory = directory.rstrip("/")
    return directory in ("", ".") or path == directory or path.startswith(directory + "/")


def deep_import_violation(importer: str, target: str) -> str | None:
    d = os.path.dirname(target)
    while d and not inside(importer, d):
        index = next((os.path.join(d, n) for n in INDEX_NAMES if os.path.isfile(os.path.join(d, n))), None)
        if index and os.path.normpath(target) != os.path.normpath(index):
            return d
        d = os.path.dirname(d)
    return None


def js_deep_imports(path: str, text: str):
    for lineno, line in enumerate(text.splitlines(), 1):
        for m in JS_IMPORT.finditer(line):
            spec = next(g for g in m.groups() if g)
            target = resolve(path, spec)
            if target:
                mod = deep_import_violation(path, target)
                if mod:
                    yield lineno, f"imports '{spec}' (internal file of module '{mod}'); import '{mod}' via its index instead"


def py_deep_imports(path: str, text: str):
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return
    for node in ast.walk(tree):
        mods = []
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
        for mod in mods:
            parts = mod.split(".")
            for i, part in enumerate(parts[1:], 1):
                if part.startswith("_") and not part.startswith("__"):
                    pkg_dir = "/".join(parts[:i])
                    candidates = [pkg_dir, f"src/{pkg_dir}", os.path.join(os.path.dirname(path), pkg_dir)]
                    real = next((c for c in candidates if os.path.isdir(c)), None)
                    if real and not inside(path, real):
                        yield node.lineno, f"imports private module '{mod}' from outside package '{'.'.join(parts[:i])}'"
                    break


def added_lines(base: str) -> tuple[set, set]:
    new_files = set(git("diff", "--name-only", "--diff-filter=A", base, "HEAD").splitlines())
    added: set = set()
    current = None
    for line in git("diff", "-U0", "--no-color", base, "HEAD").splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@ ") and current:
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            start, n = int(m.group(1)), int(m.group(2) or 1)
            added.update(f"{current}:{start + i}" for i in range(n))
    return new_files, added


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base")
    ap.add_argument("--config", default=aiconfig.DEFAULT_CONFIG)
    args = ap.parse_args(argv)
    os.chdir(git("rev-parse", "--show-toplevel").strip())
    cfg = aiconfig.load(args.config)
    max_lines = int(cfg.get("module_max_lines") or 300)
    max_syms = int(cfg.get("module_max_symbols") or 10)
    new_files, added = (set(), set())
    if args.base:
        mb = git("merge-base", args.base, "HEAD").strip()
        new_files, added = added_lines(mb)
    gha = bool(os.environ.get("GITHUB_ACTIONS"))
    errors = warnings = 0

    def emit(level: str, path: str, line: int, msg: str) -> None:
        nonlocal errors, warnings
        if level == "error":
            errors += 1
        else:
            warnings += 1
        print(f"{level.upper():7} {path}:{line}: {msg}")
        if gha:
            print(f"::{level} file={path},line={line},title=module_lint::{msg}")

    for path in tracked_sources(args.config):
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        n_lines = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
        n_syms = count_symbols(path, text)
        is_new = path in new_files
        if n_lines > max_lines or n_syms > max_syms:
            msg = f"{n_lines} lines / {n_syms} top-level symbols exceeds budget {max_lines} / {max_syms}"
            if is_new:
                emit("error", path, 1, f"new file {msg}; split it into a module with an index")
            else:
                emit("warning", path, 1, f"legacy {msg}; split only via a refactor-split scope when already editing it")
        hits = [k for k, rx in CONCERNS.items() if rx.search(text)]
        if len(hits) >= 3:
            emit("warning", path, 1, f"mixes concerns ({'+'.join(hits)}); keep one responsibility per module")
        finder = py_deep_imports if path.endswith(".py") else js_deep_imports
        for lineno, msg in finder(path, text):
            if is_new or f"{path}:{lineno}" in added:
                emit("error", path, lineno, msg)
            else:
                emit("warning", path, lineno, f"legacy {msg}")
    print(f"module_lint: {errors} error(s), {warnings} warning(s) "
          f"(budget {max_lines} lines / {max_syms} symbols{', base ' + args.base if args.base else ', audit mode'}).")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
