"""Fetch recent public posts from an Instagram profile via Apify.

Usage:
    python fetch.py                # uses DEFAULT_USERNAME
    python fetch.py someone_else   # override the target handle
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from apify_client import ApifyClient
from dotenv import load_dotenv

# TODO: Replace "gloria" with Gloria's real Instagram handle before submission.
DEFAULT_USERNAME = "gloria"
LIMIT = 20
APIFY_ACTOR_ID = "apify/instagram-scraper"
OUTPUT_PATH = Path(__file__).parent / "posts.json"


def normalize_post(raw: dict) -> dict | None:
    """Map one Apify item to our canonical post shape.

    Returns None for unknown types or posts without extractable media,
    logging a warning so a single weird post doesn't break the whole batch.
    """
    post_type = raw.get("type")
    media: list[dict] = []

    if post_type == "Image":
        url = raw.get("displayUrl")
        if url:
            media.append({"url": url, "type": "image"})
    elif post_type == "Video":
        video_url = raw.get("videoUrl")
        if video_url:
            media.append({"url": video_url, "type": "video"})
        elif raw.get("displayUrl"):
            # Fallback: Apify sometimes omits videoUrl on reels; use the thumbnail.
            media.append({"url": raw["displayUrl"], "type": "image"})
    elif post_type == "Sidecar":
        for child in raw.get("childPosts") or []:
            if child.get("type") == "Video" and child.get("videoUrl"):
                media.append({"url": child["videoUrl"], "type": "video"})
            elif child.get("displayUrl"):
                media.append({"url": child["displayUrl"], "type": "image"})
    else:
        print(
            f"[warn] unknown post type {post_type!r} for {raw.get('shortCode')} — skipping",
            file=sys.stderr,
        )
        return None

    if not media:
        print(
            f"[warn] no media for {raw.get('shortCode')} — skipping",
            file=sys.stderr,
        )
        return None

    return {
        "shortcode": raw.get("shortCode"),
        "url": raw.get("url"),
        "posted_at": raw.get("timestamp"),
        "caption": raw.get("caption"),
        "media": media,
    }


def fetch(username: str, limit: int = LIMIT) -> dict:
    load_dotenv()
    token = os.getenv("APIFY_API_TOKEN")
    if not token:
        raise SystemExit(
            "ERROR: APIFY_API_TOKEN is not set.\n"
            "  1. cp .env.example .env\n"
            "  2. Get a free token at https://console.apify.com/account/integrations\n"
            "  3. Paste it into .env"
        )

    client = ApifyClient(token)
    run_input = {
        "directUrls": [f"https://www.instagram.com/{username}/"],
        "resultsType": "posts",
        "resultsLimit": limit,
        "addParentData": False,
    }

    print(f"Calling Apify actor {APIFY_ACTOR_ID} for @{username} (limit={limit})...")
    run = client.actor(APIFY_ACTOR_ID).call(run_input=run_input)
    run_id = run.get("id", "unknown")
    dataset_id = run.get("defaultDatasetId")
    print(f"Apify run {run_id} complete.")

    raw_items = list(client.dataset(dataset_id).iterate_items())
    print(f"Got {len(raw_items)} raw items from Apify.")

    posts = [p for p in (normalize_post(item) for item in raw_items) if p is not None]

    return {
        "username": username,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "apify",
        "apify_actor": APIFY_ACTOR_ID,
        "apify_run_id": run_id,
        "posts": posts,
    }


def main() -> None:
    username = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_USERNAME
    feed = fetch(username)
    OUTPUT_PATH.write_text(
        json.dumps(feed, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(feed['posts'])} posts → {OUTPUT_PATH.name}")


if __name__ == "__main__":
    main()
