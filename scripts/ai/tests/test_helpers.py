import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "helpers"))
from honest_empty import NO_DATA_MESSAGE, honest_result, ids_are_grounded  # noqa: E402


class HonestEmptyTest(unittest.TestCase):
    def test_empty_is_honest(self):
        self.assertEqual(honest_result([]), {"found": False, "items": [], "message": NO_DATA_MESSAGE})
        self.assertEqual(honest_result(None, "orders")["message"], "No matching orders were found.")

    def test_rows_pass_through(self):
        rows = [{"id": 1}]
        self.assertEqual(honest_result(rows), {"found": True, "items": rows, "message": None})

    def test_ids_grounded(self):
        self.assertTrue(ids_are_grounded(["1"], [{"id": 1}]))
        self.assertFalse(ids_are_grounded(["user_123"], [{"id": 1}]))


if __name__ == "__main__":
    unittest.main()
