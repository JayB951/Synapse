"""Refresh only the two AGORA display rows in an existing edition."""
import os
from supabase import create_client

def main():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY")
    edition_date = os.getenv("EDITION_DATE", "2026-11-26")
    if not url or not key:
        raise RuntimeError("Missing Supabase credentials.")

    db = create_client(url, key)
    editions = (
        db.table("shard_editions").select("id")
        .eq("edition_date", edition_date).limit(1).execute().data or []
    )
    if not editions:
        raise RuntimeError(f"Edition not found: {edition_date}")
    edition_id = editions[0]["id"]

    rows = (
        db.table("shard_edition_items")
        .select("id,content_item_id,editor_note,processing_status")
        .eq("edition_id", edition_id).execute().data or []
    )
    source_ids = [row["content_item_id"] for row in rows if row.get("content_item_id")]
    sources = (
        db.table("shard_content_items")
        .select("id,metadata").in_("id", source_ids).execute().data or []
    ) if source_ids else []
    types = {source["id"]: (source.get("metadata") or {}).get("content_type") for source in sources}

    refreshed = 0
    for row in rows:
        content_type = types.get(row.get("content_item_id"))
        if content_type not in {"agora_hungary", "agora_world"}:
            continue
        (
            db.table("shard_edition_items")
            .update({
                "processing_status": "pending",
                "display_title": None,
                "display_summary": None,
                "display_body": None,
            })
            .eq("id", row["id"]).execute()
        )
        refreshed += 1

    if refreshed != 2:
        raise RuntimeError(f"Expected exactly 2 AGORA rows to refresh, found {refreshed}.")
    print(f"Reset {refreshed} AGORA edition rows for display-text regeneration.")

if __name__ == "__main__":
    main()
