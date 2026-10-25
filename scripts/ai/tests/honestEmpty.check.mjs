// Unit test for scripts/ai/helpers/honestEmpty.ts. Named *.check.mjs so the
// repo's own jest/vitest/tsc never pick it up. Run:
//   npx --yes tsx --test scripts/ai/tests/honestEmpty.check.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { honestResult, idsAreGrounded, NO_DATA_MESSAGE } from "../helpers/honestEmpty.ts";

test("empty rows return the fixed honest message and no items", () => {
  assert.deepEqual(honestResult([]), { found: false, items: [], message: NO_DATA_MESSAGE });
  assert.deepEqual(honestResult(null, { entity: "orders" }), {
    found: false,
    items: [],
    message: "No matching orders were found.",
  });
});

test("non-empty rows are passed through unchanged", () => {
  const rows = [{ id: "a1" }, { id: "b2" }];
  const res = honestResult(rows);
  assert.equal(res.found, true);
  assert.deepEqual(res.items, rows);
  assert.equal(res.message, null);
});

test("idsAreGrounded rejects ids that are not in the data", () => {
  const rows = [{ id: "a1" }, { id: 7 }];
  assert.equal(idsAreGrounded(["a1", "7"], rows), true);
  assert.equal(idsAreGrounded(["a1", "user_123"], rows), false);
});
