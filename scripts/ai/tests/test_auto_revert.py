import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixture import GitRepo, sh  # noqa: E402


class AutoRevertTest(unittest.TestCase):
    def setUp(self):
        self.repo = GitRepo({"a.txt": "one\n"})
        self.remote = tempfile.mkdtemp(prefix="remote-")
        sh(self.remote, "git", "init", "-q", "--bare")
        self.repo.run("git", "remote", "add", "origin", self.remote, check=True)
        self.repo.write("a.txt", "one\nbad\n")
        self.bad = self.repo.commit("bad change")
        self.repo.run("git", "push", "-q", "origin", "main", check=True)
        self.repo.run("git", "push", "-q", "origin", f"{self.repo.base}:refs/heads/staging", check=True)

    def tearDown(self):
        self.repo.cleanup()
        shutil.rmtree(self.remote, ignore_errors=True)

    def revert(self, *extra):
        return self.repo.run("python3", "scripts/ai/auto_revert.py", "--bad-sha", self.bad, "--no-pr", *extra)

    def test_dry_run_prints_plan_and_changes_nothing(self):
        res = self.revert("--dry-run")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("fast-forward staging", res.stdout)
        staging = sh(self.remote, "git", "rev-parse", "staging").stdout.strip()
        self.assertEqual(staging, self.repo.base)

    def test_revert_lands_on_staging_not_main(self):
        res = self.revert()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        main = sh(self.remote, "git", "rev-parse", "main").stdout.strip()
        self.assertEqual(main, self.bad)  # main untouched
        content = sh(self.remote, "git", "show", "staging:a.txt").stdout
        self.assertEqual(content, "one\n")
        branches = sh(self.remote, "git", "branch", "--format=%(refname:short)").stdout.split()
        self.assertEqual(sorted(branches), ["main", "staging"])  # no new branches

    def test_refuses_when_staging_diverged(self):
        sh(self.repo.path, "git", "checkout", "-q", "-b", "tmp", self.repo.base)
        self.repo.write("b.txt", "x\n")
        diverged = self.repo.commit("staging work")
        self.repo.run("git", "push", "-q", "-f", "origin", f"{diverged}:refs/heads/staging", check=True)
        self.repo.run("git", "checkout", "-q", "main", check=True)
        res = self.revert()
        self.assertEqual(res.returncode, 1)
        self.assertIn("diverged", res.stdout)

    def test_refuses_sha_not_on_main(self):
        res = self.repo.run("python3", "scripts/ai/auto_revert.py", "--bad-sha", "0" * 40, "--no-pr")
        self.assertNotEqual(res.returncode, 0)


if __name__ == "__main__":
    unittest.main()
