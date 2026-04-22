"""
Ingest events.json into Supabase (signals table).

Runs in GitHub Actions with:
  - SUPABASE_URL
  - SUPABASE_SERVICE_ROLE_KEY

Uses Supabase PostgREST upsert endpoint; no extra dependencies required.
"""

import json
import os
import sys
import urllib.request


def env(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


def postgrest_upsert(url: str, api_key: str, rows: list[dict]) -> None:
    endpoint = url.rstrip("/") + "/rest/v1/signals?on_conflict=link"
    body = json.dumps(rows).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "apikey": api_key,
            "Authorization": f"Bearer {api_key}",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status < 200 or resp.status >= 300:
            raise RuntimeError(f"Upsert failed: HTTP {resp.status}")


def main() -> int:
    supabase_url = env("SUPABASE_URL")
    service_key = env("SUPABASE_SERVICE_ROLE_KEY")

    with open("events.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    scraped = data.get("scraped", [])
    if not isinstance(scraped, list):
        raise RuntimeError("events.json: scraped must be a list")

    rows = []
    for s in scraped:
        link = (s.get("link") or "").strip()
        _id = (s.get("id") or "").strip()
        title = (s.get("title") or "").strip()
        if not link or not _id or not title:
            continue
        rows.append(
            {
                "id": _id,
                "link": link,
                "title": title,
                "summary": s.get("summary") or "",
                "source": s.get("source") or "",
                "layer": s.get("layer"),
                "access": s.get("access") or "",
                "score": s.get("score"),
                "moments": s.get("moments") or [],
                "published_text": s.get("date") or "",
            }
        )

    if not rows:
        print("No rows to ingest.")
        return 0

    # PostgREST has payload limits; batch to be safe.
    batch_size = 200
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        postgrest_upsert(supabase_url, service_key, batch)
        print(f"Upserted {len(batch)} rows")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise

