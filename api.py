"""FastAPI endpoints serving the cached Instagram feed.

Run locally:
    uvicorn api:app --reload
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

POSTS_PATH = Path(__file__).parent / "posts.json"

app = FastAPI(title="Gloria Instagram Feed", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _read_feed() -> dict | None:
    if not POSTS_PATH.exists():
        return None
    return json.loads(POSTS_PATH.read_text(encoding="utf-8"))


@app.get("/")
def root() -> dict:
    return {
        "service": "gloria-instagram-feed",
        "endpoints": {
            "/posts": "the fetched feed as JSON",
            "/health": "service + feed freshness status",
        },
    }


@app.get("/posts")
def get_posts() -> dict:
    feed = _read_feed()
    if feed is None:
        raise HTTPException(
            status_code=503,
            detail="No feed yet. Run `python fetch.py` first.",
        )
    return feed


@app.get("/health")
def health() -> dict:
    feed = _read_feed()
    if feed is None:
        return {"status": "no_feed", "message": "Run python fetch.py first"}

    try:
        file_mtime = datetime.fromtimestamp(
            POSTS_PATH.stat().st_mtime, tz=timezone.utc
        ).isoformat()
    except OSError:
        file_mtime = None

    return {
        "status": "ok",
        "username": feed.get("username"),
        "source": feed.get("source"),
        "post_count": len(feed.get("posts", [])),
        "fetched_at": feed.get("fetched_at"),
        "file_mtime": file_mtime,
    }
