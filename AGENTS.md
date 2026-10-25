<!-- BEGIN AI guardrails (added 2026-10-25). Owner-approved guardrail section; agents must not edit it. -->
# AI agent guide

Rules for any AI coding agent (Claude Code, Cursor, Codex, Devin, ...) working in **around-the-block-legal**. Everything here is enforced by hooks and CI; see `scripts/ai/README.md`.

## Commands
Stack: Static site (legal pages); no package.json.

All checks run through `scripts/ai/run-checks.sh <check>` locally and in CI (`AI guardrails` workflow).

| Check | Exact commands (repo root) |
|---|---|
| lint | **NOT CONFIGURED** in this repo. Suggested free addition: npx --yes html-validate@latest '**/*.html' (free, no config needed) |
| typecheck | **NOT CONFIGURED** in this repo. Suggested free addition: n/a for plain HTML/JS; optional: add // @ts-check + npx --yes -p typescript tsc --allowJs --checkJs --noEmit |
| test | **NOT CONFIGURED** in this repo. Suggested free addition: add a tiny node --test smoke test (e.g. checks index.html links/IDs exist) |
| build | **NOT CONFIGURED** in this repo. Suggested free addition: n/a (static site served as-is) |

Helpers: `ni DIR` = `npm ci` (or pnpm `--frozen-lockfile` / `npm install` without a lockfile), `x DIR CMD` = run CMD in DIR, `pyi` = `python3 -m pip install`, `pnpmx` = pnpm at the pinned version.

## Naming conventions
- Plain static files; keep existing names: `privacy.html`, `terms.html`.

## Never do
- Never push to `main`, create branches/tags, open PRs other than the automated staging -> main PR, change repo settings, or delete anything.
- Never remove or rewrite existing features, text, comments or files unless the request explicitly says so; never reformat or "tidy" unrelated code.
- Never edit tests to make them pass, skip/focus tests, or loosen assertions (tests are owner-only; see docs/ai/TDD.md).
- Never edit guardrail files: AGENTS.md, CLAUDE.md, .ai/, .claude/, .cursor/rules/, .github/workflows/, scripts/ai/, docs/ai/.
- Never leave placeholders (`TODO`, `...rest of code`, `// ... existing code`, lorem ipsum) or invent IDs, URLs, citations, prices or API responses.
- Never commit secrets (`sk_live_`, `whsec_`, cloud keys) or put test keys in production config.
- Never claim something works ("tests pass", "build succeeded") without pasting the command output or linking the CI run.

## Definition of done
- The change does exactly what the request asked, inside the declared scope, and nothing else.
- The commands in **Commands** that exist for this repo were run locally and their output is pasted in the PR (or the CI run is linked). Checks marked NOT CONFIGURED are stated as such, never as passing.
- New behaviour is covered by the owner's failing-then-passing tests (docs/ai/TDD.md); no test file was edited by the agent.
- All `AI guardrails` jobs, `Dual-model review`, CodeQL/Socket/Snyk (where enabled) are green on the staging -> main PR.

## Verification
Run before every push to `staging` and paste the output:
```
scripts/ai/run-checks.sh all                                  # the repo's real lint / typecheck / test / build
scripts/ai/review-rules.sh --diff origin/main                 # review rules on added lines
scripts/ai/check-tests-untouched.sh origin/main               # TDD gate
python3 scripts/ai/editlint.py --base origin/main             # scope / symbols / comments / budget
python3 scripts/ai/module_lint.py --base origin/main          # module budget + deep imports
python3 scripts/ai/backstops/check_output.py --diff origin/main
uvx snyk-agent-scan@latest .                                   # optional, needs SNYK_TOKEN (free Snyk account)
```
One-time per clone: `scripts/ai/install-hooks.sh` (git pre-commit hook) and `scripts/ai/lock-tests.sh`.

## Scoped edits
Declare the change before making it (`.ai/change-scope.yml`, committed with the change):
```yaml
request: "Fix rounding in invoice totals"
mode: normal            # or refactor-split
max_lines: 120          # added+removed lines; capped by max_lines_ceiling in .ai/config.yml
allow:
  - src/billing/totals.ts::computeTotal   # path::Symbol you may change
allow_files: []         # non-code files you may remove lines from / delete / rename
```
Anything outside it fails `editlint`. See `.cursor/rules/scoped-edits.mdc`.

## Staging-only workflow
This repository has exactly two branches: `main` (production) and `staging` (agent work).
1. Start from an up-to-date `staging` (`git fetch origin && git switch staging && git reset --hard origin/staging`).
2. Declare scope in `.ai/change-scope.yml` (or an `ai-change-scope` block in the PR body).
3. Commit on `staging` and push `staging`. Never create another branch; experiments go in a temporary directory or `git worktree add --detach`.
4. `agent-pr-loop.yml` opens the staging -> main PR, labels failures `ai-failing` with the failing log, and closes the PR after 3 failed attempts (`ai-retry-cap-reached`).
5. When every check is green it merges automatically and `reset-staging.yml` resets `staging` to `main`.
6. If checks fail on `main` after a merge, `scripts/ai/auto_revert.py` reverts it through `staging`.

## Trust but verify
Every claim must be checkable by a machine, and the machines check it:
| Claim / risk | Deterministic check |
|---|---|
| "Tests pass" / "build succeeded" | `scripts/ai/backstops/check_output.py` (Claude Stop hook + CI) fails unless command output or a CI run link is included |
| Invented URLs or citations | backstops: every URL must exist in the repo or be this repo's GitHub URL; numbered citations need a source line |
| Placeholder / invented IDs | backstops + `scripts/ai/pre-edit-guard.sh` + `review-rules.sh` |
| Edits outside the request | `scripts/ai/editlint.py` (symbols, comments, line endings, line budget vs `.ai/change-scope.yml`) |
| Weakened tests | `pre-edit-guard.sh` (blocks edits), `scripts/ai/hooks/pre-commit`, `check-tests-untouched.sh` in CI (no bypass label) |
| Oversized / tangled modules | `scripts/ai/module_lint.py` |
| Second opinion | `dual-model-review.yml` (Gemini or OpenAI, structured verdict; fails on disagreement; skipped - never passed - without a key) |
| Security | CodeQL, Socket, Snyk Agent Scan + Snyk Open Source (each states SKIPPED when its token/plan is missing) |

When a data lookup returns nothing, say so plainly (see `scripts/ai/helpers/honestEmpty.ts` / `honest_empty.py`); never fill the gap with plausible-looking data.

## Modules
- One responsibility per module (a directory): e.g. billing, auth, storage, routes. Do not mix database access, payments, auth and HTTP routing in one file.
- A module's public API is its `index.ts` (TypeScript/JS) or `__init__.py` (Python). Other modules import only from that entry point, never from its internal files.
- Budget: new files <= 300 lines and <= 10 top-level symbols (`module_max_lines` / `module_max_symbols` in `.ai/config.yml`). `scripts/ai/module_lint.py` FAILS on new files over budget and on new deep imports, and only WARNS on existing files.
- Splitting an existing oversized file: only when you are already editing that file for the request, as a SEPARATE behaviour-preserving commit on `staging` with `mode: refactor-split` (`split_from`, `split_to`, `split_symbols`) in `.ai/change-scope.yml`. editlint verifies the moved symbols are byte-identical. Never refactor unrelated app code.

Example (static site): keep each page's script in its own file and share helpers through one `js/lib/index.js`:
```js
// GOOD
import { formatDate } from "./lib/index.js";
// BAD
import { formatDate } from "./lib/dates/internal-format.js";
```

## Tests (TDD)
Owner writes failing tests first; agents implement. Full flow: `docs/ai/TDD.md`.

<!-- END AI guardrails (added 2026-10-25) -->
