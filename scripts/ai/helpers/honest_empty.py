"""Optional helper (not wired into app code): answer honestly when a lookup
returns nothing instead of letting a model invent IDs or records.

    rows = db.execute("SELECT id, title FROM orders WHERE user_id = ?", (uid,)).fetchall()
    result = honest_result(rows, entity="orders")
    if not result["found"]:
        return result["message"]   # fixed text; never ask the model to fill the gap
"""
from __future__ import annotations

NO_DATA_MESSAGE = "No matching records were found."


def honest_result(rows, entity: str | None = None) -> dict:
    if not rows:
        msg = f"No matching {entity} were found." if entity else NO_DATA_MESSAGE
        return {"found": False, "items": [], "message": msg}
    return {"found": True, "items": list(rows), "message": None}


def ids_are_grounded(mentioned_ids, rows) -> bool:
    known = {str(r["id"]) for r in rows}
    return all(str(i) in known for i in mentioned_ids)
