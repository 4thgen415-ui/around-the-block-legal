# scripts/ai - AI coding guardrails

Deterministic, free (stdlib Python + bash) checks that keep AI agents inside the
request. Owner-only: agents are blocked from editing anything here.

| File | What it does | Runs in |
|---|---|---|
| `run-checks.sh` | The repo's real lint / typecheck / test / build commands (`NOT CONFIGURED` when the repo has none) | CI `repo-checks`, locally |
| `ship.sh` | SHIP gate (AGENTS.md "Work modes"): full suite + every guardrail check with `AI_MODE=ship`; `--suite` = full suite only. SANDBOX (default) never runs it | owner says "ship it"; pre-commit when `AI_MODE=ship` |
| `pre-edit-guard.sh` / `pre_edit_guard.py` | Claude Code PreToolUse hook: blocks edits to tests, guardrail files, paths outside the repo, and added placeholders (exit 2) | `.claude/settings.json` |
| `backstops/check_output.py` | Claims without evidence, invented URLs/citations, placeholder IDs | Claude Stop + PostToolUse hooks, CI |
| `review-rules.sh` | Review feedback as grep rules on added lines (secrets, console.log, focused tests, ...) | CI, pre-commit |
| `check-tests-untouched.sh` | TDD gate: no mixed test+code commits, no test edits after implementation starts | CI |
| `editlint.py` | Scope check vs `.ai/change-scope.yml`: symbols, comments, line endings, line budget, refactor-split byte-identity | CI |
| `module_lint.py` | New files within module budget; no deep imports past a module's index | CI |
| `dual_review.py` | Second-model review (Gemini / OpenAI) with JSON verdict | `dual-model-review.yml` |
| `auto_revert.py` | Reverts a commit that broke `main` through `staging` | `agent-pr-loop.yml` |
| `lock-tests.sh` / `unlock-tests.sh` | Owner toggles test write access | owner |
| `unlock-guardrails.sh` | Owner unlocks guardrail edits (re-lock: `rm .git/ai-guardrails-unlocked`) | owner |
| `install-hooks.sh`, `hooks/pre-commit` | Local git hook: mixed commits, locked tests, branch policy, review rules | each clone |
| `helpers/` | Optional honest-empty-result helpers (not wired into app code) | app code, if adopted |
| `aiconfig.py`, `pathrules.py`, `patterns.py` | Shared config parser, path classes, placeholder/claim patterns | library |

Self-test: `python3 -m unittest discover -s scripts/ai/tests -p 'test_*.py'`,
`scripts/ai/tests/test-pre-edit-guard.sh`, `npx --yes tsx --test scripts/ai/tests/honestEmpty.check.mjs`.

## Add a review rule
Every repeated review comment should become a rule. Append one line near the
other `rule` calls in `review-rules.sh`:
```bash
rule ID SEVERITY FILE_REGEX PATTERN MESSAGE
rule no-any-cast error '\.(ts|tsx)$' 'as any\b' 'Do not cast to any; type it properly.'
```
- `SEVERITY`: `error` fails CI and the pre-commit hook; `warning` only annotates.
- `FILE_REGEX`: Python-style regex searched in the repo-relative path.
- `PATTERN`: `git grep -E` regex matched against each line. In CI only lines
  added by the change are checked, so legacy code never blocks a merge.
- Then add a case to `tests/test_scripts.py` (a fixture commit that must hit
  the rule) and run the self-test.
