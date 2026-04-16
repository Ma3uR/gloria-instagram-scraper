"""Fetch recent public posts from an Instagram profile via Apify.

Usage:
    python fetch.py                # uses DEFAULT_USERNAME
    python fetch.py someone_else   # override the target handle
"""
from __future__ import annotations

import html
import json
import mimetypes
import os
import sys
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from apify_client import ApifyClient
from dotenv import load_dotenv

DEFAULT_USERNAME = "gloriya_glor"  # https://www.instagram.com/gloriya_glor/
LIMIT = 20
APIFY_ACTOR_ID = "apify/instagram-scraper"
OUTPUT_PATH = Path(__file__).parent / "posts.json"
GALLERY_PATH = Path(__file__).parent / "gallery.html"
MEDIA_DIR = Path(__file__).parent / "media"


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


def _guess_extension(url: str, media_type: str) -> str:
    """Pick a filename extension from the URL path, falling back by type."""
    path = urllib.parse.urlparse(url).path
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov"):
        if path.lower().endswith(ext):
            return ext
    guessed = mimetypes.guess_extension(f"{media_type}/*") or ""
    return guessed or (".mp4" if media_type == "video" else ".jpg")


def download_media(feed: dict, dest: Path = MEDIA_DIR) -> dict:
    """Download each post's media to dest/<shortcode>/<n><ext> and rewrite URLs.

    Keeps the original IG CDN URL as `source_url` so downstream consumers can
    tell what was rehosted. Idempotent: skips files that already exist.
    """
    dest.mkdir(exist_ok=True)
    total = sum(len(p["media"]) for p in feed["posts"])
    done = 0
    for post in feed["posts"]:
        post_dir = dest / (post.get("shortcode") or "unknown")
        post_dir.mkdir(exist_ok=True)
        for i, m in enumerate(post["media"]):
            ext = _guess_extension(m["url"], m.get("type", "image"))
            target = post_dir / f"{i}{ext}"
            if not target.exists():
                try:
                    urllib.request.urlretrieve(m["url"], target)
                except Exception as exc:
                    print(f"[warn] failed to download {m['url'][:60]}…: {exc}", file=sys.stderr)
                    continue
            m["source_url"] = m["url"]
            m["url"] = str(target.relative_to(dest.parent))
            done += 1
            print(f"  [{done}/{total}] {target.relative_to(dest.parent)}")
    return feed


def _format_date(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%b %d, %Y")
    except ValueError:
        return iso


def _render_media(media: list[dict]) -> str:
    parts = []
    for m in media:
        url = html.escape(m.get("url", ""), quote=True)
        if m.get("type") == "video":
            parts.append(f'<video controls preload="metadata" src="{url}"></video>')
        else:
            parts.append(f'<img loading="lazy" src="{url}" alt="">')
    return "\n".join(parts)


def render_gallery(feed: dict) -> str:
    """Render the feed as a self-contained HTML gallery."""
    cards = []
    for p in feed["posts"]:
        caption = html.escape(p.get("caption") or "", quote=False).replace("\n", "<br>")
        post_url = html.escape(p.get("url", "#"), quote=True)
        posted = _format_date(p.get("posted_at"))
        count_badge = (
            f'<span class="count">{len(p["media"])} items</span>'
            if len(p.get("media", [])) > 1
            else ""
        )
        cards.append(
            f"""<article class="card">
  <div class="media">{_render_media(p["media"])}{count_badge}</div>
  <div class="body">
    <div class="meta"><time>{posted}</time>
      <a href="{post_url}" target="_blank" rel="noopener">view on Instagram ↗</a>
    </div>
    <p class="caption">{caption}</p>
  </div>
</article>"""
        )

    title = html.escape(f"@{feed.get('username', '')} — Instagram feed")
    header_meta = (
        f"{len(feed['posts'])} posts · fetched {_format_date(feed.get('fetched_at'))} · "
        f"source: {html.escape(feed.get('source', ''))}"
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: light dark; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 2rem 1rem;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #fafafa; color: #262626;
    line-height: 1.5;
  }}
  header {{ max-width: 1100px; margin: 0 auto 2rem; }}
  h1 {{ margin: 0 0 .25rem; font-size: 1.75rem; font-weight: 600; }}
  header .meta {{ color: #737373; font-size: .9rem; }}
  .grid {{
    display: grid; gap: 1.25rem;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    max-width: 1100px; margin: 0 auto;
  }}
  .card {{
    background: #fff; border: 1px solid #dbdbdb; border-radius: 12px;
    overflow: hidden; display: flex; flex-direction: column;
  }}
  .media {{ position: relative; background: #000; aspect-ratio: 1 / 1; overflow: hidden; }}
  .media img, .media video {{
    width: 100%; height: 100%; object-fit: cover; display: block;
  }}
  .media video + video, .media img + img, .media img + video, .media video + img {{
    display: none; /* show only first media on multi-item cards */
  }}
  .count {{
    position: absolute; top: .5rem; right: .5rem;
    background: rgba(0,0,0,.65); color: #fff;
    padding: .2rem .55rem; border-radius: 999px;
    font-size: .75rem; font-weight: 500;
  }}
  .body {{ padding: .9rem 1rem 1.1rem; display: flex; flex-direction: column; gap: .5rem; }}
  .body .meta {{
    display: flex; justify-content: space-between; align-items: baseline;
    font-size: .85rem; color: #737373;
  }}
  .body .meta a {{ color: #0095f6; text-decoration: none; }}
  .body .meta a:hover {{ text-decoration: underline; }}
  .caption {{ margin: 0; white-space: pre-wrap; font-size: .95rem; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #0a0a0a; color: #fafafa; }}
    .card {{ background: #1c1c1c; border-color: #2a2a2a; }}
    .body .meta {{ color: #a0a0a0; }}
  }}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <div class="meta">{header_meta}</div>
</header>
<main class="grid">
{chr(10).join(cards)}
</main>
</body>
</html>
"""


def main() -> None:
    username = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_USERNAME
    feed = fetch(username)

    # Rehost media locally so the gallery works offline and doesn't depend on
    # IG CDN URLs (which expire in weeks AND set CORP: same-origin, blocking
    # images from rendering on a file:// page).
    print(f"Downloading media → {MEDIA_DIR.name}/ ...")
    feed = download_media(feed)

    OUTPUT_PATH.write_text(
        json.dumps(feed, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(feed['posts'])} posts → {OUTPUT_PATH.name}")

    GALLERY_PATH.write_text(render_gallery(feed), encoding="utf-8")
    print(f"Wrote gallery → {GALLERY_PATH.name}")

    # Open the gallery in the default browser unless suppressed (e.g. in CI).
    if os.getenv("NO_OPEN") != "1":
        webbrowser.open(GALLERY_PATH.resolve().as_uri())


if __name__ == "__main__":
    main()
