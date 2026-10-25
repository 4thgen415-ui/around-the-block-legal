/**
 * Optional helper (not wired into app code): answer honestly when a data
 * lookup returns nothing, instead of letting a model invent IDs or records.
 *
 * Usage in a Worker/route (example only):
 *   const rows = (await env.DB.prepare("SELECT id, title FROM orders WHERE user_id = ?")
 *     .bind(userId).all()).results;
 *   const answer = honestResult(rows, { entity: "orders" });
 *   if (!answer.found) return Response.json(answer, { status: 200 });
 *   // only now pass answer.items (real rows) to the model/prompt
 */
export const NO_DATA_MESSAGE = "No matching records were found.";

export type HonestResult<T> =
  | { found: true; items: T[]; message: null }
  | { found: false; items: []; message: string };

export function honestResult<T>(
  rows: readonly T[] | null | undefined,
  options: { entity?: string } = {},
): HonestResult<T> {
  if (!rows || rows.length === 0) {
    const message = options.entity
      ? `No matching ${options.entity} were found.`
      : NO_DATA_MESSAGE;
    return { found: false, items: [], message };
  }
  return { found: true, items: [...rows], message: null };
}

/** True when every id the model mentions exists in the rows it was given. */
export function idsAreGrounded(
  mentionedIds: readonly string[],
  rows: readonly { id: string | number }[],
): boolean {
  const known = new Set(rows.map((r) => String(r.id)));
  return mentionedIds.every((id) => known.has(String(id)));
}
