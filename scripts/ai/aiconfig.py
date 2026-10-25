#!/usr/bin/env python3
"""Tiny stdlib reader for the restricted YAML used in .ai/config.yml and
.ai/change-scope.yml (no PyYAML dependency).

Supported syntax (anything else is a hard error, so typos fail loudly):
    key: value            # scalars: int, true/false, quoted or bare strings
    key:                  # followed by a list
      - item
    key: [a, b]           # inline list
Comments start with '#' (outside quotes). Blank lines are ignored.

CLI:  python3 scripts/ai/aiconfig.py get <key> [--file .ai/config.yml]
      prints scalars as-is and lists one item per line.
"""
from __future__ import annotations

import os
import sys
sys.dont_write_bytecode = True  # never leave __pycache__ in the repo

DEFAULT_CONFIG = ".ai/config.yml"


def _strip_comment(line: str) -> str:
    out, quote = [], None
    for ch in line:
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "#":
            break
        out.append(ch)
    return "".join(out).rstrip()


def _scalar(raw: str):
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        return raw[1:-1]
    low = raw.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "~", ""):
        return None
    try:
        return int(raw)
    except ValueError:
        return raw


def parse(text: str) -> dict:
    data: dict = {}
    current_list_key = None
    for lineno, line in enumerate(text.splitlines(), 1):
        line = _strip_comment(line)
        if not line.strip():
            continue
        stripped = line.lstrip()
        if stripped.startswith("- "):
            if current_list_key is None:
                raise ValueError(f"line {lineno}: list item without a key")
            data[current_list_key].append(_scalar(stripped[2:]))
            continue
        if line[0] in " \t":
            raise ValueError(f"line {lineno}: unsupported nesting: {line!r}")
        if ":" not in line:
            raise ValueError(f"line {lineno}: expected 'key: value': {line!r}")
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if value == "":
            data[key] = []
            current_list_key = key
        elif value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            data[key] = [_scalar(v) for v in inner.split(",")] if inner else []
            current_list_key = None
        else:
            data[key] = _scalar(value)
            current_list_key = None
    return data


def load(path: str = DEFAULT_CONFIG, required: bool = False) -> dict:
    if not os.path.exists(path):
        if required:
            raise FileNotFoundError(path)
        return {}
    with open(path, encoding="utf-8") as fh:
        return parse(fh.read())


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] != "get":
        print(__doc__, file=sys.stderr)
        return 64
    path = DEFAULT_CONFIG
    if "--file" in argv:
        path = argv[argv.index("--file") + 1]
    value = load(path).get(argv[1])
    if value is None:
        return 1
    if isinstance(value, list):
        for item in value:
            print(item)
    else:
        print(str(value).lower() if isinstance(value, bool) else value)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
