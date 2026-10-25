import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixture import GitRepo  # noqa: E402

PY = '''import os

# helper comment
def alpha(x):
    """Alpha."""
    return x + 1


def beta(y):
    # keep me
    return y * 2
'''

TS = '''import { z } from "./z";

// public API
export function createCheckout(id: string) {
  return id;
}

export const PRICE = 5;

function internal() {
  // internal note
  return 1;
}
'''


class EditlintTest(unittest.TestCase):
    def setUp(self):
        self.repo = GitRepo({"app/mod.py": PY, "src/billing.ts": TS, "README.md": "line one\nline two\n"})

    def tearDown(self):
        self.repo.cleanup()

    def lint(self, scope: str | None = None, *extra):
        if scope is not None:
            self.repo.write(".ai/change-scope.yml", scope)
            self.repo.commit("scope")
        return self.repo.run("python3", "scripts/ai/editlint.py", "--base", self.repo.base, *extra)

    def test_allowed_function_change_passes(self):
        self.repo.write("app/mod.py", PY.replace("x + 1", "x + 2"))
        self.repo.commit("impl")
        res = self.lint("allow:\n  - app/mod.py::alpha\n")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_unlisted_function_change_fails(self):
        self.repo.write("app/mod.py", PY.replace("y * 2", "y * 3"))
        self.repo.commit("impl")
        res = self.lint("allow:\n  - app/mod.py::alpha\n")
        self.assertEqual(res.returncode, 1)
        self.assertIn("symbol 'beta' modified", res.stdout)

    def test_ts_symbol_deletion_fails(self):
        self.repo.write("src/billing.ts", TS.replace("export const PRICE = 5;\n\n", ""))
        self.repo.commit("impl")
        res = self.lint("allow:\n  - createCheckout\n")
        self.assertEqual(res.returncode, 1)
        self.assertIn("symbol 'PRICE' deleted", res.stdout)

    def test_ts_allowed_change_and_new_symbol_pass(self):
        self.repo.write("src/billing.ts", TS.replace("return id;", "return id.trim();") +
                        "\nexport function refund(id: string) {\n  return id;\n}\n")
        self.repo.commit("impl")
        res = self.lint("allow:\n  - src/billing.ts::createCheckout\n")
        self.assertEqual(res.returncode, 0, res.stdout)

    def test_comment_loss_fails(self):
        self.repo.write("src/billing.ts", TS.replace("// public API\n", ""))
        self.repo.commit("impl")
        res = self.lint("allow:\n  - src/billing.ts::createCheckout\n")
        self.assertEqual(res.returncode, 1)
        self.assertIn("comment", res.stdout)

    def test_line_ending_change_fails(self):
        self.repo.write("app/mod.py", PY.replace("\n", "\r\n"))
        self.repo.commit("crlf")
        res = self.lint("allow:\n  - app/mod.py::*\n  - app/mod.py::<preamble>\n")
        self.assertEqual(res.returncode, 1)
        self.assertIn("line endings changed lf -> crlf", res.stdout)

    def test_budget_exceeded_fails(self):
        self.repo.write("app/new.py", "".join(f"V{i} = {i}\n" for i in range(50)))
        self.repo.commit("big")
        res = self.lint("max_lines: 20\n")
        self.assertEqual(res.returncode, 1)
        self.assertIn("budget exceeded", res.stdout)

    def test_budget_capped_by_ceiling(self):
        self.repo.write("app/new.py", "".join(f"V{i} = {i}\n" for i in range(450)))
        self.repo.commit("big")
        res = self.lint("max_lines: 100000\n")
        self.assertEqual(res.returncode, 1)
        self.assertIn("ceiling=400", res.stdout)

    def test_removing_doc_text_fails_unless_allowed(self):
        self.repo.write("README.md", "line one\n")
        self.repo.commit("docs")
        self.assertEqual(self.lint("").returncode, 1)
        res = self.lint("allow_files:\n  - README.md\n")
        self.assertEqual(res.returncode, 0, res.stdout)

    def test_file_deletion_fails(self):
        self.repo.delete("app/mod.py")
        self.repo.commit("rm")
        res = self.lint("")
        self.assertEqual(res.returncode, 1)
        self.assertIn("file deleted", res.stdout)

    def test_pr_body_scope_block(self):
        self.repo.write("app/mod.py", PY.replace("y * 2", "y * 3"))
        self.repo.commit("impl")
        body = os.path.join(self.repo.path, "body.md")
        with open(body, "w") as fh:
            fh.write("Fix beta\n\n```ai-change-scope\nallow:\n  - app/mod.py::beta\n```\n")
        res = self.lint(None, "--pr-body-file", body)
        self.assertEqual(res.returncode, 0, res.stdout)

    def test_refactor_split_identical_move_passes(self):
        moved = '''

function internal() {
  // internal note
  return 1;
}
'''
        self.repo.write("src/billing.ts", TS.replace(moved, "\n"))
        self.repo.write("src/billing/internal.ts", "export function internal() {\n  // internal note\n  return 1;\n}\n")
        self.repo.commit("split")
        scope = ("mode: refactor-split\nsplit_from: src/billing.ts\nsplit_to:\n  - src/billing/internal.ts\n"
                 "split_symbols:\n  - internal\n")
        res = self.lint(scope)
        self.assertEqual(res.returncode, 0, res.stdout)

    def test_refactor_split_altered_body_fails(self):
        self.repo.write("src/billing.ts", TS.split("function internal")[0])
        self.repo.write("src/billing/internal.ts", "export function internal() {\n  return 2;\n}\n")
        self.repo.commit("split")
        scope = ("mode: refactor-split\nsplit_from: src/billing.ts\nsplit_to:\n  - src/billing/internal.ts\n"
                 "split_symbols:\n  - internal\n")
        res = self.lint(scope)
        self.assertEqual(res.returncode, 1)
        self.assertIn("byte-identical", res.stdout)

    def test_bootstrap_skip_when_base_lacks_guardrails(self):
        repo = GitRepo()
        try:
            repo.run("git", "rm", "-rq", "scripts/ai")
            repo.commit("no guardrails")
            base = repo.head()
            repo.write("x.py", "A = 1\n")
            repo.commit("x")
            res = repo.run("python3", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                                   "editlint.py"), "--base", base)
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertIn("bootstrap", res.stdout)
        finally:
            repo.cleanup()


if __name__ == "__main__":
    unittest.main()
