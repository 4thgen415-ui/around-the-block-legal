#!/usr/bin/env python3
"""editlint.py - blast-radius lint for agent changes (stdlib only).

Compares BASE vs HEAD (or the working tree) file by file and FAILS when the
change reaches beyond the declared scope:

  * a top-level symbol (function/class/const/type...) that is not on the
    allowlist is modified or deleted
  * a top-level non-symbol line (imports, module statements) is removed
    without `<path>::*` or `<path>::<preamble>` on the allowlist
  * an existing comment disappears (even inside an allowed symbol) unless the
    whole symbol is an allowed deletion or the file is listed in
    allow_comment_removal
  * a file's line-ending style (LF/CRLF) or final newline changes
  * a non-code text file loses existing lines and is not in allow_files
  * a file is deleted/renamed without being in allow_files
  * added+removed lines exceed the budget (max_lines, capped by
    max_lines_ceiling in .ai/config.yml)
  * mode: refactor-split - moved symbols must reappear byte-identical
    (an added leading `export ` is tolerated) in one of split_to, and test
    files may not change at all

Scope comes from .ai/change-scope.yml and/or a fenced ```ai-change-scope
block in the PR body (--pr-body-file); the PR-body block wins per key.
Symbol parsing: Python via ast/tokenize; JS/TS via top-level regex
(declarations starting in column 0). Parsing is heuristic: unusual syntax may
be attributed to the previous symbol, which errs towards failing.

Usage: editlint.py --base origin/main [--head HEAD|WORKTREE]
                   [--scope .ai/change-scope.yml] [--pr-body-file body.md]
Exit: 0 ok, 1 violations, 2 usage/git error.
"""
from __future__ import annotations

import argparse
import ast
import collections
import io
import os
import re
import subprocess
import sys
sys.dont_write_bytecode = True  # never leave __pycache__ in the repo
import tokenize

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import aiconfig  # noqa: E402
import pathrules  # noqa: E402

PY_EXT = (".py",)
JS_EXT = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
SCOPE_FILE = ".ai/change-scope.yml"
ALWAYS_FREE = {SCOPE_FILE}
PREAMBLE = "<preamble>"

JS_DECL = [
    re.compile(r"^(?:export\s+(?:default\s+)?)?(?:declare\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)"),
    re.compile(r"^(?:export\s+(?:default\s+)?)?(?:declare\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"^(?:export\s+)?(?:declare\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"^(?:export\s+)?(?:declare\s+)?(?:interface|type|enum|namespace|module)\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"^(export\s+default)\b"),
    re.compile(r"^(module\.exports)\s*="),
]


# --------------------------------------------------------------------------
# git helpers
# --------------------------------------------------------------------------
def git(*args: str, check: bool = True) -> str:
    res = subprocess.run(["git", *args], capture_output=True, text=True,
                         encoding="utf-8", errors="surrogateescape")
    if check and res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {res.stderr.strip()}")
    return res.stdout


def read_rev(rev: str, path: str) -> str | None:
    if rev == "WORKTREE":
        if not os.path.isfile(path):
            return None
        with open(path, encoding="utf-8", errors="surrogateescape", newline="") as fh:
            return fh.read()
    res = subprocess.run(["git", "show", f"{rev}:{path}"], capture_output=True)
    if res.returncode != 0:
        return None
    return res.stdout.decode("utf-8", errors="surrogateescape")


def changed_files(base: str, head: str):
    """Yield (status, old_path, new_path)."""
    args = ["diff", "--name-status", "-M", "--no-color", base]
    if head != "WORKTREE":
        args.append(head)
    out = git(*args)
    if head == "WORKTREE":
        for p in git("ls-files", "--others", "--exclude-standard").splitlines():
            out += f"A\t{p}\n"
    for line in out.splitlines():
        parts = line.split("\t")
        status = parts[0][0]
        if status == "R" or status == "C":
            yield status, parts[1], parts[2]
        else:
            yield status, parts[1], parts[1]


def numstat(base: str, head: str) -> dict:
    args = ["diff", "--numstat", "-M", base]
    if head != "WORKTREE":
        args.append(head)
    stats = {}
    for line in git(*args).splitlines():
        a, r, p = line.split("\t", 2)
        if "=>" in p:
            p = p.split("=>")[-1].strip(" }")
        stats[p] = (0 if a == "-" else int(a), 0 if r == "-" else int(r))
    return stats


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------
def _is_comment_or_blank(line: str, lang: str) -> bool:
    s = line.strip()
    if not s:
        return True
    if lang == "py":
        return s.startswith("#")
    return s.startswith("//") or s.startswith("/*") or s.startswith("*") or s.endswith("*/")


def _spans(lines: list[str], starts: list[tuple[int, str]], lang: str) -> dict:
    """starts: sorted (0-based line, name). Returns name -> text of its span.
    Leading comments/blank lines directly above a declaration belong to it."""
    symbols: dict = {}
    if not starts:
        symbols[PREAMBLE] = "".join(lines)
        return symbols
    adj = []
    for idx, (ln, name) in enumerate(starts):
        floor = starts[idx - 1][0] + 1 if idx else 0
        s = ln
        while s - 1 >= floor and lines[s - 1].strip() and _is_comment_or_blank(lines[s - 1], lang):
            s -= 1
        adj.append((s, name))
    symbols[PREAMBLE] = "".join(lines[: adj[0][0]])
    seen = collections.Counter()
    for idx, (s, name) in enumerate(adj):
        end = adj[idx + 1][0] if idx + 1 < len(adj) else len(lines)
        seen[name] += 1
        key = name if seen[name] == 1 else f"{name}#{seen[name]}"
        symbols[key] = "".join(lines[s:end])
    return symbols


def py_symbols(text: str) -> dict:
    lines = text.splitlines(keepends=True)
    try:
        tree = ast.parse(text)
    except SyntaxError:
        starts = [(i, m.group(2)) for i, l in enumerate(lines)
                  if (m := re.match(r"^(async\s+def|def|class)\s+(\w+)", l))]
        return _spans(lines, starts, "py")
    starts = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        first = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])]) - 1
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
        elif isinstance(node, ast.Assign) and all(isinstance(t, ast.Name) for t in node.targets):
            name = ",".join(t.id for t in node.targets)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
        else:
            name = "<stmt " + lines[first].strip()[:60] + ">"
        starts.append((first, name))
    # imports between symbols stay inside the previous span; the preamble keeps
    # the leading import block.
    return _spans(lines, sorted(starts), "py")


def js_symbols(text: str) -> dict:
    lines = text.splitlines(keepends=True)
    starts = []
    for i, line in enumerate(lines):
        if not line or line[0] in " \t}\n\r)/*":
            continue
        for rx in JS_DECL:
            m = rx.match(line)
            if m:
                starts.append((i, m.group(1).replace("export default", "default")))
                break
    return _spans(lines, starts, "js")


def symbols_for(path: str, text: str) -> dict | None:
    if path.endswith(PY_EXT):
        return py_symbols(text)
    if path.endswith(JS_EXT):
        return js_symbols(text)
    return None


def comments(path: str, text: str) -> collections.Counter:
    found: collections.Counter = collections.Counter()
    if path.endswith(PY_EXT):
        try:
            for tok in tokenize.generate_tokens(io.StringIO(text).readline):
                if tok.type == tokenize.COMMENT:
                    found[tok.string.strip()] += 1
            return found
        except (tokenize.TokenError, IndentationError, SyntaxError):
            for line in text.splitlines():
                if line.strip().startswith("#"):
                    found[line.strip()] += 1
            return found
    if path.endswith(JS_EXT):
        for m in re.finditer(r"/\*[\s\S]*?\*/", text):
            for part in m.group(0).splitlines():
                part = part.strip()
                if part.strip("/* "):
                    found[part] += 1
        for line in text.splitlines():
            m = re.search(r"(?:^|[\s;{}(),])(//.*)$", line)
            if m and not re.search(r"[\"'`][^\"'`]*//", line[: m.start(1) + 2]):
                found[m.group(1).strip()] += 1
    return found


def eol_style(text: str) -> tuple[str, bool]:
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    style = "none" if crlf + lf == 0 else ("crlf" if crlf >= lf and crlf else "lf")
    return style, text.endswith("\n")


# --------------------------------------------------------------------------
# scope
# --------------------------------------------------------------------------
def load_scope(scope_path: str, pr_body_file: str | None) -> dict:
    scope: dict = {}
    if scope_path and os.path.exists(scope_path):
        scope.update(aiconfig.load(scope_path))
    if pr_body_file and os.path.exists(pr_body_file):
        with open(pr_body_file, encoding="utf-8") as fh:
            body = fh.read()
        m = re.search(r"```ai-change-scope\s*\n([\s\S]*?)```", body)
        if m:
            scope.update(aiconfig.parse(m.group(1)))
    return scope


def allowed(path: str, symbol: str, allow: list) -> bool:
    base_symbol = symbol.split("#")[0]
    for entry in allow:
        entry = str(entry)
        if "::" in entry:
            p, s = entry.split("::", 1)
            if pathrules.matches(path, [p]) and (s in ("*", symbol, base_symbol)):
                return True
        elif entry in (symbol, base_symbol):
            return True
    return False


# --------------------------------------------------------------------------
# main check
# --------------------------------------------------------------------------
class Report:
    def __init__(self) -> None:
        self.errors: list[tuple[str, str]] = []
        self.notes: list[str] = []

    def fail(self, path: str, msg: str) -> None:
        self.errors.append((path, msg))


def _norm(body: str) -> str:
    """Symbol text without trailing blank lines (spacing between symbols moves
    when neighbours are added or removed; EOL changes are checked separately)."""
    return re.sub(r"[ \t\r\n]+$", "", body)


def strip_export(text: str) -> str:
    return re.sub(r"^((?:\s*(?://|#|/\*|\*).*\n|\s*\n)*)export\s+", r"\1", text, count=1)


def run(base: str, head: str, scope: dict, cfg: dict, config_path: str) -> Report:
    rep = Report()
    allow = [str(a) for a in (scope.get("allow") or [])]
    allow_files = [str(a) for a in (scope.get("allow_files") or [])]
    mode = str(scope.get("mode") or "normal")
    ceiling = int(cfg.get("max_lines_ceiling") or 400)
    budget = min(int(scope.get("max_lines") or cfg.get("default_max_lines") or 200), ceiling)

    files = list(changed_files(base, head))
    moved_lines = 0

    if mode == "refactor-split":
        src = str(scope.get("split_from") or "")
        targets = [str(t) for t in (scope.get("split_to") or [])]
        names = [str(s) for s in (scope.get("split_symbols") or [])]
        if not (src and targets and names):
            rep.fail(SCOPE_FILE, "refactor-split needs split_from, split_to and split_symbols")
        else:
            base_syms = symbols_for(src, read_rev(base, src) or "") or {}
            head_src = symbols_for(src, read_rev(head, src) or "") or {}
            head_targets = {t: symbols_for(t, read_rev(head, t) or "") or {} for t in targets}
            for name in names:
                if name not in base_syms:
                    rep.fail(src, f"refactor-split: symbol '{name}' does not exist in {base}:{src}")
                    continue
                if name in head_src and _norm(head_src[name]) == _norm(base_syms[name]):
                    rep.fail(src, f"refactor-split: '{name}' was not moved out of {src}")
                    continue
                want = base_syms[name].strip("\n")
                hit = [t for t, syms in head_targets.items()
                       if name in syms and strip_export(syms[name]).strip("\n") in (want, strip_export(want).strip("\n"))]
                if not hit:
                    rep.fail(src, f"refactor-split: '{name}' does not reappear byte-identical in any of {targets}")
                else:
                    allow.append(f"{src}::{name}")
                    moved_lines += want.count("\n") + 1
            allow.append(f"{src}::{PREAMBLE}")  # imports/re-exports of moved symbols
        for _, _, new in files:
            if pathrules.is_test(new, config_path):
                rep.fail(new, "refactor-split: test files must not change in a split commit")

    total = 0
    stats = numstat(base, head)
    for path, (a, r) in stats.items():
        if path in ALWAYS_FREE or pathrules.is_ignored(path, config_path):
            continue
        total += a + r
    total = max(0, total - 2 * moved_lines)
    if total > budget:
        rep.fail("*", f"change budget exceeded: {total} added+removed lines > max_lines {budget} "
                      f"(scope max_lines={scope.get('max_lines')}, ceiling={ceiling})")

    for status, old, new in files:
        if new in ALWAYS_FREE or pathrules.is_ignored(new, config_path):
            continue
        if status == "A":
            continue
        if status in ("D", "R"):
            if not (pathrules.matches(old, allow_files) or allowed(old, "*", allow)):
                verb = "deleted" if status == "D" else f"renamed to {new}"
                rep.fail(old, f"file {verb} without allow_files entry")
            if status == "D":
                continue
        before = read_rev(base, old)
        after = read_rev(head, new)
        if before is None or after is None:
            continue
        if eol_style(before)[0] != "none" and eol_style(after)[0] != "none" and eol_style(before)[0] != eol_style(after)[0]:
            rep.fail(new, f"line endings changed {eol_style(before)[0]} -> {eol_style(after)[0]}")
        if eol_style(before)[1] != eol_style(after)[1]:
            rep.fail(new, "final newline added/removed")
        bsyms = symbols_for(new, before)
        if bsyms is None:
            removed = stats.get(new, (0, 0))[1]
            if removed and not pathrules.matches(new, allow_files):
                rep.fail(new, f"removes {removed} existing line(s) from a non-code file; add it to allow_files if intended")
            continue
        hsyms = symbols_for(new, after) or {}
        for name, body in bsyms.items():
            if name == PREAMBLE:
                lost = collections.Counter(l.strip() for l in body.splitlines() if l.strip()) - \
                    collections.Counter(l.strip() for l in hsyms.get(PREAMBLE, "").splitlines() if l.strip())
                if lost and not (allowed(new, PREAMBLE, allow) or allowed(new, "*", allow)):
                    rep.fail(new, f"removes/changes {sum(lost.values())} top-level line(s) outside any symbol "
                                  f"(e.g. {next(iter(lost))!r}); allow '{new}::{PREAMBLE}' if intended")
                continue
            if name not in hsyms:
                if not allowed(new, name, allow):
                    rep.fail(new, f"symbol '{name}' deleted but not in allow list")
            elif _norm(hsyms[name]) != _norm(body) and not allowed(new, name, allow):
                rep.fail(new, f"symbol '{name}' modified but not in allow list")
        lost_comments = comments(new, before) - comments(new, after)
        if lost_comments:
            deleted_text = "".join(b for n, b in bsyms.items()
                                   if n != PREAMBLE and n not in hsyms and allowed(new, n, allow))
            ok_files = [str(a) for a in (scope.get("allow_comment_removal") or [])]
            really_lost = [] if pathrules.matches(new, ok_files) else \
                [c for c in lost_comments if c not in deleted_text]
            if really_lost:
                rep.fail(new, f"{len(really_lost)} existing comment(s) removed, e.g. {really_lost[0][:80]!r}")
    rep.notes.append(f"budget: {total}/{budget} lines; mode={mode}; files={len(files)}")
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=os.environ.get("BASE_REF", "origin/main"))
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--scope", default=SCOPE_FILE)
    ap.add_argument("--pr-body-file")
    ap.add_argument("--config", default=aiconfig.DEFAULT_CONFIG)
    args = ap.parse_args(argv)
    try:
        os.chdir(git("rev-parse", "--show-toplevel").strip())
        base = git("merge-base", args.base, "HEAD" if args.head == "WORKTREE" else args.head).strip()
    except RuntimeError as exc:
        print(f"editlint: {exc}", file=sys.stderr)
        return 2
    if read_rev(base, "scripts/ai/editlint.py") is None:
        print("editlint: bootstrap - base does not contain the guardrails yet; this change installs them, skipped once.")
        return 0
    cfg = aiconfig.load(args.config)
    scope = load_scope(args.scope, args.pr_body_file)
    rep = run(base, args.head, scope, cfg, args.config)
    for note in rep.notes:
        print(f"editlint: {note}")
    gha = bool(os.environ.get("GITHUB_ACTIONS"))
    for path, msg in rep.errors:
        print(f"FAIL {path}: {msg}")
        if gha:
            print(f"::error file={path},title=editlint::{msg}")
    if rep.errors:
        print(f"editlint: FAILED with {len(rep.errors)} violation(s). Declare the intended scope in {SCOPE_FILE}.")
        return 1
    print("editlint: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
