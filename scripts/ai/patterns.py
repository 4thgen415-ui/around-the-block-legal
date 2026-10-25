#!/usr/bin/env python3
"""Shared regexes for placeholder / fabricated-output detection.

Used by pre_edit_guard.py (Claude Code PreToolUse hook), backstops/check_output.py
and the CI backstops job. scripts/ai/review-rules.sh keeps an equivalent grep -E list.
"""
import re

# Placeholder text an agent must never write into code or docs.
PLACEHOLDER_PATTERNS = [
    (r"\bTODO\b", "TODO marker"),
    (r"\bFIXME\b", "FIXME marker"),
    (r"\bTBD\b", "TBD marker"),
    (r"(?i)\.\.\.\s*(the\s+)?rest\s+of\s+(the\s+)?(code|file|implementation|function|component)", "'...rest of code' elision"),
    (r"(?i)(//|#|/\*|<!--)\s*\.\.\.\s*(existing|previous|other|unchanged)\b", "'// ... existing code' elision"),
    (r"(?i)\b(existing|remaining|other)\s+code\s+(here|unchanged|remains|stays)\b", "'existing code unchanged' elision"),
    (r"(?i)\blorem\s+ipsum\b", "lorem ipsum filler"),
    (r"(?i)\b(implement|fill\s+in|add\s+logic)\s+(this\s+|me\s+|it\s+)?(later|here)\b", "'implement later' stub"),
    (r"(?i)<\s*(insert|your|replace)[ _-][^>]{0,40}>", "<insert ...> placeholder"),
    (r"(?i)\byour[-_ ]?(api[-_ ]?key|secret|token|password)[-_ ]?here\b", "'your-api-key-here' placeholder"),
    (r"(?i)\bplaceholder\s+(text|content|implementation|value|data)\b", "explicit 'placeholder ...'"),
    (r"(?i)throw\s+new\s+Error\(\s*['\"]not\s+implemented", "'not implemented' stub"),
    (r"raise\s+NotImplementedError\b", "NotImplementedError stub"),
]

# IDs that look invented rather than read from a data source.
PLACEHOLDER_ID_PATTERNS = [
    (r"\b0{8}-0{4}-0{4}-0{4}-0{12}\b", "all-zero UUID"),
    (r"\b(12345678-1234-1234-1234-123456789(012|abc))\b", "sequential fake UUID"),
    (r"(?i)\b(user|order|customer|cus|sub|price|prod|acct|org|item)_(123|1234|12345|abc|abc123|xxx+|example|test123)\b", "fake prefixed ID"),
    (r"(?i)\bid\s*[:=]\s*['\"]?(xxx+|abc123|123456|example-id|your-id)['\"]?", "fake id value"),
]

CLAIM_PATTERNS = [
    r"(?i)\ball\s+(the\s+)?(tests|checks)\s+(pass|passed|passing|are\s+green|green)\b",
    r"(?i)\btests?\s+(pass|passed|passing|are\s+passing|is\s+passing)\b",
    r"(?i)\b(verified|confirmed)\s+(that\s+)?(it|this|everything)\s+works\b",
    r"(?i)\bbuild\s+(passes|passed|succeeds|succeeded|is\s+green)\b",
    r"(?i)\b(lint|typecheck|type[- ]check)\s+(passes|passed|is\s+clean|clean)\b",
    r"(?i)\bCI\s+(is\s+)?(green|passing|passes)\b",
]

# Evidence that makes a claim acceptable: a fenced block of command output or
# a link to a CI run.
EVIDENCE_PATTERNS = [
    r"```[\s\S]*?(\$ |> |PASS|passed|✓|ok\b|Tests?:|exit code|0 failed|failed:? 0)[\s\S]*?```",
    r"https://github\.com/[^/\s]+/[^/\s]+/actions/runs/\d+",
]


def compiled(pairs):
    return [(re.compile(p), label) for p, label in pairs]


def find_new_placeholders(new_text: str, old_text: str = "", include_ids: bool = True):
    """Return labels of patterns that occur more often in new_text than old_text."""
    found = []
    pairs = PLACEHOLDER_PATTERNS + (PLACEHOLDER_ID_PATTERNS if include_ids else [])
    for rx, label in compiled(pairs):
        if len(rx.findall(new_text)) > len(rx.findall(old_text or "")):
            found.append(label)
    return found
