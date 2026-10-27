# Test-driven workflow for AI agents

Tests are the specification. The owner (or the owner explicitly asking for it) writes them; agents make them pass without touching them.

## Roles
| Step | Who | Command / rule |
|---|---|---|
| 1. Unlock tests | owner | `scripts/ai/unlock-tests.sh` (marker in `.git/`, makes test files writable) |
| 2. Write failing tests | owner | Commit **only test files** on `staging` (a test-only commit). Run the test command and confirm it fails for the right reason. |
| 3. Lock tests | owner | `scripts/ai/lock-tests.sh` (test files read-only, Claude Code hook blocks edits) |
| 4. Implement | agent | Smallest change that makes the failing tests pass. Implementation commits contain **no** test files. |
| 5. Refactor | agent | Optional, behaviour-preserving, tests stay green, still no test edits. Module splits only via a `refactor-split` scope. |
| 6. Verify | CI | `check-tests-untouched` fails on mixed commits or on any test change after the first implementation commit. No bypass label exists. |

Install the local git hook once per clone: `scripts/ai/install-hooks.sh` (rejects mixed test/non-test commits, test edits while locked, and commits on branches other than main/staging).

Optional: list the owner's commit e-mail(s) under `test_authors:` in `.ai/config.yml` so CI also rejects test-only commits by anyone else.

## Work modes: when test-first applies

- SANDBOX (default, AGENTS.md "Work modes"): test-first applies to behaviour and
  logic changes. Cosmetic or copy tweaks (layout, spacing, colours, wording)
  need no new test and no full test run; at most one quick check under ~1
  minute (typecheck of the touched package or one targeted test).
- SHIP ("push this", "ship it", "deploy"): full red-green-refactor for every
  behaviour change, and the full suite plus every check via
  `scripts/ai/ship.sh`. Nothing merges to `main` until it is green.
- Both modes: tests stay owner-only; locked and protected tests are never
  edited or weakened.

## Prompt template (red -> green -> refactor)
```
Request: <one sentence>
Failing tests (do not edit): <paths>  - run: <exact test command from AGENTS.md>
1. Run the tests and paste the failing output.
2. Declare scope in .ai/change-scope.yml (request, allow: path::Symbol, max_lines).
3. Implement the smallest change in the allowed symbols only. No test edits.
4. Re-run the exact commands (tests, lint, typecheck, build) and paste the output.
5. If anything is still red after 3 attempts, stop and report the output; do not weaken tests.
```
