import os
import stat
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from fixture import GitRepo  # noqa: E402
import aiconfig  # noqa: E402
import pathrules  # noqa: E402


class ConfigAndPathsTest(unittest.TestCase):
    def test_aiconfig_parse(self):
        cfg = aiconfig.parse("# c\na: 1\nb: true\nc: [x, \"y z\"]\nd:\n  - one\n  - 'two'\ne: null\nf: hi # note\n")
        self.assertEqual(cfg, {"a": 1, "b": True, "c": ["x", "y z"], "d": ["one", "two"], "e": None, "f": "hi"})

    def test_aiconfig_rejects_nesting(self):
        with self.assertRaises(ValueError):
            aiconfig.parse("a:\n  b: 1\n")

    def test_classify(self):
        none = "/nonexistent/config.yml"  # built-in defaults, independent of cwd
        self.assertEqual(pathrules.classify("src/a.test.ts", none), "test")
        self.assertEqual(pathrules.classify("./tests/test_x.py", none), "test")
        self.assertEqual(pathrules.classify("pkg/__tests__/a.js", none), "test")
        self.assertEqual(pathrules.classify("scripts/ai/tests/test_x.py", none), "guardrail")
        self.assertEqual(pathrules.classify(".github/workflows/ci.yml", none), "guardrail")
        self.assertEqual(pathrules.classify("src/contest.ts", none), "code")
        self.assertTrue(pathrules.is_ignored("web/node_modules/x/index.js", none))
        self.assertTrue(pathrules.is_ignored("package-lock.json", none))


class ShellScriptsTest(unittest.TestCase):
    def setUp(self):
        self.repo = GitRepo({"src/app.ts": "export const a = 1;\n", "tests/app.test.ts": "test('a', () => {});\n"})

    def tearDown(self):
        for root, dirs, files in os.walk(self.repo.path):
            for f in files:
                p = os.path.join(root, f)
                os.chmod(p, os.stat(p).st_mode | stat.S_IWUSR)
        self.repo.cleanup()

    def untouched(self):
        return self.repo.run("bash", "scripts/ai/check-tests-untouched.sh", self.repo.base)

    def test_tests_first_then_impl_passes(self):
        self.repo.write("tests/app.test.ts", "test('a', () => {});\ntest('b', () => {});\n")
        self.repo.commit("owner: failing test")
        self.repo.write("src/app.ts", "export const a = 2;\n")
        self.repo.commit("impl")
        res = self.untouched()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_mixed_commit_fails(self):
        self.repo.write("tests/app.test.ts", "test('a', () => {});\n// x\n")
        self.repo.write("src/app.ts", "export const a = 2;\n")
        self.repo.commit("mixed")
        res = self.untouched()
        self.assertEqual(res.returncode, 1)
        self.assertIn("mixes 1 test file(s)", res.stdout)

    def test_test_change_after_impl_fails(self):
        self.repo.write("src/app.ts", "export const a = 2;\n")
        self.repo.commit("impl")
        self.repo.write("tests/app.test.ts", "test.skip('a', () => {});\n")
        self.repo.commit("weaken test")
        res = self.untouched()
        self.assertEqual(res.returncode, 1)
        self.assertIn("after implementation commit", res.stdout)

    def test_test_authors_enforced(self):
        self.repo.write(".ai/config.yml", "test_authors:\n  - owner@example.com\n")
        self.repo.commit("cfg")
        base = self.repo.head()
        self.repo.write("tests/app.test.ts", "// bot\n")
        self.repo.commit("bot test", env={"GIT_AUTHOR_EMAIL": "bot@example.com"})
        res = self.repo.run("bash", "scripts/ai/check-tests-untouched.sh", base)
        self.assertEqual(res.returncode, 1)
        self.assertIn("not in test_authors", res.stdout)

    def test_review_rules_diff_only_flags_added_lines(self):
        self.repo.write("src/app.ts", "export const a = 1;\nconsole.log('debug');\nconst k = 'sk_live_" + "x" * 24 + "';\n")
        self.repo.commit("bad")
        res = self.repo.run("bash", "scripts/ai/review-rules.sh", "--diff", self.repo.base)
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("stripe-live-secret", res.stdout)
        self.assertIn("console-log", res.stdout)

    def test_review_rules_file_scoped_rules(self):
        self.repo.write("src/x.test.ts", "describe.only('x', () => {});\n")
        self.repo.write("wrangler.toml", 'STRIPE_PK = "pk_test_' + 'a' * 20 + '"\n')
        self.repo.write("pkg/test_x.py", "def test_x():\n    breakpoint()\n")
        self.repo.commit("bad tests")
        res = self.repo.run("bash", "scripts/ai/review-rules.sh", "--diff", self.repo.base)
        self.assertEqual(res.returncode, 1)
        for rule in ("focused-test", "test-key-in-prod", "py-breakpoint"):
            self.assertIn(rule, res.stdout)

    def test_review_rules_clean_diff_passes(self):
        self.repo.write("src/app.ts", "export const a = 3;\n")
        self.repo.commit("ok")
        res = self.repo.run("bash", "scripts/ai/review-rules.sh", "--diff", self.repo.base)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_pre_commit_hook(self):
        self.assertEqual(self.repo.run("bash", "scripts/ai/install-hooks.sh").returncode, 0)
        self.repo.run("git", "checkout", "-q", "-b", "staging")
        self.repo.write("tests/app.test.ts", "// x\n")
        self.repo.write("src/app.ts", "export const a = 9;\n")
        self.repo.run("git", "add", "-A")
        res = self.repo.run("git", "commit", "-qm", "mixed")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("mixes", res.stderr)
        self.repo.run("git", "reset", "-q", "tests/app.test.ts")
        self.assertEqual(self.repo.run("git", "commit", "-qm", "impl").returncode, 0)
        self.repo.run("git", "add", "-A")
        res = self.repo.run("git", "commit", "-qm", "tests while locked")
        self.assertIn("locked", res.stderr)
        self.repo.run("bash", "scripts/ai/unlock-tests.sh")
        self.assertEqual(self.repo.run("git", "commit", "-qm", "owner tests").returncode, 0)
        self.repo.run("git", "checkout", "-q", "-b", "feature-x")
        self.repo.write("src/app.ts", "export const a = 10;\n")
        self.repo.run("git", "add", "-A")
        res = self.repo.run("git", "commit", "-qm", "on feature branch")
        self.assertIn("not allowed", res.stderr)

    def test_lock_and_unlock(self):
        res = self.repo.run("bash", "scripts/ai/lock-tests.sh")
        self.assertEqual(res.returncode, 0, res.stderr)
        p = os.path.join(self.repo.path, "tests/app.test.ts")
        self.assertFalse(os.stat(p).st_mode & stat.S_IWUSR)
        self.assertTrue(os.stat(os.path.join(self.repo.path, "src/app.ts")).st_mode & stat.S_IWUSR)
        self.repo.run("bash", "scripts/ai/unlock-tests.sh")
        self.assertTrue(os.stat(p).st_mode & stat.S_IWUSR)


if __name__ == "__main__":
    unittest.main()
