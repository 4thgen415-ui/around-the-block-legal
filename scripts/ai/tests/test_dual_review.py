import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from fixture import GitRepo  # noqa: E402
import dual_review  # noqa: E402


def gemini_reply(verdict: dict) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(verdict)}]}}]}


AGREE = {"verdict": "agree", "unrelated_changes": [], "unverified_claims": [], "test_tampering": [],
         "summary": "Change matches the request."}


class DualReviewTest(unittest.TestCase):
    def setUp(self):
        self.repo = GitRepo({"src/a.ts": "export const a = 1;\n"})
        self.repo.write("src/a.ts", "export const a = 2;\n")
        self.repo.commit("change")
        self.cwd = os.getcwd()
        os.chdir(self.repo.path)
        self.calls = []

    def tearDown(self):
        os.chdir(self.cwd)
        self.repo.cleanup()

    def fake_post(self, reply):
        def post(url, payload, headers, timeout=120):
            self.calls.append((url, payload, headers))
            return reply if "generativelanguage" in url or "openai" in url else {}
        return post

    def run_main(self, env, reply):
        out = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=False), redirect_stdout(out):
            for k in ("GEMINI_API_KEY", "OPENAI_API_KEY", "GITHUB_TOKEN", "GITHUB_STEP_SUMMARY", "DUAL_REVIEW_MODEL"):
                if k not in env:
                    os.environ.pop(k, None)
            code = dual_review.main(["--base", self.repo.base, "--pr-number", "7"], post=self.fake_post(reply))
        return code, out.getvalue()

    def test_no_key_is_explicit_skip_not_pass(self):
        code, out = self.run_main({}, None)
        self.assertEqual(code, dual_review.EXIT_NO_KEY)
        self.assertIn("SKIPPED", out)
        self.assertEqual(self.calls, [])

    def test_gemini_agree_passes_and_posts_comment(self):
        code, out = self.run_main({"GEMINI_API_KEY": "k", "GITHUB_TOKEN": "t", "GITHUB_REPOSITORY": "o/r"},
                                  gemini_reply(AGREE))
        self.assertEqual(code, 0, out)
        self.assertIn("gemini-3.8-flash:generateContent", self.calls[0][0])
        self.assertEqual(self.calls[0][2]["x-goog-api-key"], "k")
        self.assertIn("export const a = 2", self.calls[0][1]["contents"][0]["parts"][0]["text"])
        self.assertTrue(self.calls[1][0].endswith("/repos/o/r/issues/7/comments"))
        self.assertIn("PASS", self.calls[1][1]["body"])

    def test_disagreement_fails(self):
        code, out = self.run_main({"GEMINI_API_KEY": "k"},
                                  gemini_reply({**AGREE, "verdict": "disagree", "unrelated_changes": ["edits README"]}))
        self.assertEqual(code, 1)
        self.assertIn("edits README", out)

    def test_test_tampering_fails_even_if_agree(self):
        code, _ = self.run_main({"GEMINI_API_KEY": "k"}, gemini_reply({**AGREE, "test_tampering": ["assert removed"]}))
        self.assertEqual(code, 1)

    def test_openai_fallback(self):
        reply = {"choices": [{"message": {"content": json.dumps(AGREE)}}]}
        code, _ = self.run_main({"OPENAI_API_KEY": "o"}, reply)
        self.assertEqual(code, 0)
        self.assertEqual(self.calls[0][1]["model"], "gpt-6-luna")
        self.assertEqual(self.calls[0][2]["Authorization"], "Bearer o")

    def test_malformed_reply_fails(self):
        bad = {"candidates": [{"content": {"parts": [{"text": "looks good to me!"}]}}]}
        code, out = self.run_main({"GEMINI_API_KEY": "k"}, bad)
        self.assertEqual(code, 1)
        self.assertIn("reviewer call failed", out)

    def test_parse_verdict_handles_fences(self):
        v = dual_review.parse_verdict("```json\n" + json.dumps(AGREE) + "\n```")
        self.assertEqual(v["verdict"], "agree")


if __name__ == "__main__":
    unittest.main()
