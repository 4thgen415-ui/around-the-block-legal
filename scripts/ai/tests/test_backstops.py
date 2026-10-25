import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixture import GitRepo  # noqa: E402

SCRIPT = "scripts/ai/backstops/check_output.py"


class BackstopsTest(unittest.TestCase):
    def setUp(self):
        self.repo = GitRepo({"README.md": "Docs: https://developers.cloudflare.com/d1/\n",
                             "src/app.ts": "export const a = 1;\n"})
        self.repo.run("git", "remote", "add", "origin", "https://github.com/owner/demo.git")

    def tearDown(self):
        self.repo.cleanup()

    def text(self, body: str):
        path = os.path.join(self.repo.path, "body.md")
        with open(path, "w") as fh:
            fh.write(body)
        return self.repo.run("python3", SCRIPT, "--text-file", path)

    def test_claim_without_evidence_fails(self):
        res = self.text("Fixed the bug. All tests pass.")
        self.assertEqual(res.returncode, 1)
        self.assertIn("claim without evidence", res.stdout)

    def test_claim_with_output_block_passes(self):
        res = self.text("All tests pass.\n\n```\n$ npm test\nTests: 12 passed, 0 failed\n```\n")
        self.assertEqual(res.returncode, 0, res.stdout)

    def test_claim_with_own_run_url_passes(self):
        res = self.text("CI is green: https://github.com/owner/demo/actions/runs/123456")
        self.assertEqual(res.returncode, 0, res.stdout)

    def test_unknown_url_fails_known_url_passes(self):
        self.assertEqual(self.text("See https://developers.cloudflare.com/d1/").returncode, 0)
        res = self.text("See https://docs.made-up-vendor.io/api/v9/thing")
        self.assertEqual(res.returncode, 1)
        self.assertIn("possible invented citation", res.stdout)

    def test_citation_without_source_fails(self):
        res = self.text("D1 supports this [1].")
        self.assertEqual(res.returncode, 1)
        self.assertIn("citation [1]", res.stdout)
        ok = self.text("D1 supports this [1].\n\n[1]: https://developers.cloudflare.com/d1/\n")
        self.assertEqual(ok.returncode, 0, ok.stdout)

    def test_placeholder_id_in_added_code_fails_but_not_in_tests(self):
        self.repo.write("src/app.ts", 'export const a = 1;\nexport const owner = "user_123";\n')
        self.repo.write("src/app.test.ts", 'const id = "user_123";\n')
        self.repo.commit("ids")
        res = self.repo.run("python3", SCRIPT, "--diff", self.repo.base)
        self.assertEqual(res.returncode, 1)
        self.assertIn("src/app.ts: fake prefixed ID", res.stdout)
        self.assertNotIn("app.test.ts", res.stdout)

    def hook(self, flag: str, payload: dict):
        return self.repo.run("python3", SCRIPT, flag, input=json.dumps(payload))

    def test_stop_hook_blocks_unverified_claim(self):
        res = self.hook("--claude-stop", {"hook_event_name": "Stop", "stop_hook_active": False,
                                          "last_assistant_message": "Done - all tests pass."})
        self.assertEqual(res.returncode, 2)
        self.assertIn("claim without evidence", res.stderr)

    def test_stop_hook_never_loops(self):
        res = self.hook("--claude-stop", {"stop_hook_active": True, "last_assistant_message": "all tests pass"})
        self.assertEqual(res.returncode, 0)

    def test_stop_hook_reads_transcript_fallback(self):
        tpath = os.path.join(self.repo.path, "t.jsonl")
        with open(tpath, "w") as fh:
            fh.write(json.dumps({"type": "assistant", "message": {"role": "assistant",
                     "content": [{"type": "text", "text": "Build succeeded."}]}}) + "\n")
        res = self.hook("--claude-stop", {"transcript_path": tpath})
        self.assertEqual(res.returncode, 2)

    def test_post_tool_hook_flags_fake_ids_in_code_only(self):
        bad = {"tool_name": "Write", "tool_input": {"file_path": os.path.join(self.repo.path, "src/x.ts"),
                                                    "content": 'const c = "cus_123";'}}
        self.assertEqual(self.hook("--claude-post-tool", bad).returncode, 2)
        test_file = {"tool_name": "Write", "tool_input": {"file_path": "src/x.test.ts", "content": 'const c = "cus_123";'}}
        self.assertEqual(self.hook("--claude-post-tool", test_file).returncode, 0)
        clean = {"tool_name": "Edit", "tool_input": {"file_path": "src/x.ts", "new_string": "const c = row.id;"}}
        self.assertEqual(self.hook("--claude-post-tool", clean).returncode, 0)


if __name__ == "__main__":
    unittest.main()
