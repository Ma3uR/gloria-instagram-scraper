# Gloria Instagram Feed — Full-Stack Co-founder test task

A minimal Python service that fetches the last ~20 posts from a public Instagram profile (Gloria's, for this brief) and exposes them as:

- a `posts.json` file on disk (for static frontends or a checked-in demo), and
- a FastAPI `GET /posts` endpoint (for a live frontend).

Per post it captures **publication date, caption, and media URLs** (supports single images, videos, and carousels).

Built for a digital-legacy product that preserves a person's social-media presence after their death. This submission is the "week-one spike" — working code + decisions I'd explain to a co-founder, not a production system. The broader product vision — who it's for, what we believe, what MVP looks like — is in [docs/VISION.md](docs/VISION.md). This README focuses on the technical approach.

---

## Quickstart

```bash
# 1. Install dependencies (Python 3.10+)
pip install -r requirements.txt

# 2. Configure Apify token
cp .env.example .env
# Edit .env and paste your token from https://console.apify.com/account/integrations
# (free tier includes $5/mo in credits — ~2000 Instagram posts)

# 3. Fetch the feed (defaults to @gloriya_glor)
python fetch.py
# or: python fetch.py some_other_handle
# → writes posts.json + gallery.html, downloads media into media/,
#   and opens the gallery in your browser.
# (set NO_OPEN=1 to skip auto-opening, e.g. in CI)

# 4. (Optional) serve the feed over HTTP for a frontend
uvicorn api:app --reload
curl http://localhost:8000/posts | jq '.posts | length'   # → 20
curl http://localhost:8000/health
```

`posts.json` and `gallery.html` are committed so a reviewer can see the shape without a token. `media/` is not committed (it's third-party user content, ~7 MB per full fetch) — running `python fetch.py` regenerates it. The `url` field in each post points at the local `media/` path; the original IG CDN URL is preserved in `source_url`.

### Why we rehost media bytes instead of just storing URLs

Instagram's CDN returns images with `Cross-Origin-Resource-Policy: same-origin`, which means browsers refuse to render them on any page not served from `instagram.com` — including a `file://` gallery and any production frontend we'd build. Videos happen to use `cross-origin` CORP so they work, but images don't. On top of that, the URLs are signed and expire in roughly two weeks. For a digital-legacy product that promises to preserve this content *forever*, storing bytes is the correct move, not an optimization. This is the same "media rehosting" requirement called out in the scale section below.

### Output schema

```json
{
  "username": "gloriya_glor",
  "fetched_at": "2026-04-17T12:34:56+00:00",
  "source": "apify",
  "apify_actor": "apify/instagram-scraper",
  "apify_run_id": "abc123...",
  "posts": [
    {
      "shortcode": "C7xYz...",
      "url": "https://www.instagram.com/p/C7xYz.../",
      "posted_at": "2026-04-10T18:22:15.000Z",
      "caption": "caption text or null",
      "media": [
        { "url": "https://scontent.cdninstagram.com/...", "type": "image" }
      ]
    }
  ]
}
```

Carousels produce a `media` array with multiple items in original order; videos have `"type": "video"`.

---

## 1. Approach — how we bypass Instagram's blocking

First, a framing correction. **This task is scraping a public profile, not an API integration.** The data we want is the same feed anyone sees in a browser without logging in — there's no private data involved.

The reason we have to scrape at all is that Meta has no official API for reading arbitrary public profiles:

- **Instagram Graph API** is an OAuth API. It returns data only for accounts whose owner has explicitly authorized *our* Meta app. Gloria has not authorized anything from us — there's no account relationship, so Graph API literally has no method to call. It's the wrong shape of tool, not a permission problem.
- **Instagram Basic Display API** used to cover third-party reads in a limited way. [Deprecated December 4, 2024.](https://developers.facebook.com/blog/post/2024/09/04/update-on-instagram-basic-display-api/) Gone.
- Meta's ToS discourages automated access, but US courts have consistently held that scraping *publicly accessible* data is not a violation of the CFAA (see [hiQ v. LinkedIn](https://en.wikipedia.org/wiki/HiQ_Labs_v._LinkedIn)). The risk is technical (Instagram tries to block scrapers) and operational (they can rate-limit or ban our IPs), not legal in the first instance.

So the question collapses to: **which scraping tool in April 2026?**

| Option | Works today? | Why I didn't pick it |
|---|---|---|
| `?__a=1` / old public GraphQL | ❌ dead since late 2023 | — |
| `i.instagram.com/api/v1/users/web_profile_info/` | ⚠️ profile metadata only | Doesn't return the full post list; IG rotates required tokens every 2–4 weeks |
| [`instaloader`](https://instaloader.github.io/) (free Python lib) | ⚠️ works but fragile | Public profiles increasingly require a login cookie, rate limits are aggressive, and IG rotates GraphQL `doc_id` values every few weeks — each rotation breaks the library until an upstream patch lands |
| [`instagrapi`](https://github.com/subzeroid/instagrapi) (unofficial private API) | ⚠️ active | Uses IG's private mobile API — requires a real IG account session, which means account-ban risk every run. Ethically worst option for a product that must be durable |
| Custom Playwright / headless browser | ✅ with effort | TLS fingerprinting + residential proxy rotation + login-wall handling is weeks of hardening work. Wrong shape for a 4-hour test task, and still our ops burden at scale |
| **[Apify Instagram Scraper](https://apify.com/apify/instagram-scraper)** | ✅ stable | **Chosen.** See below. |

**Why Apify.** It's a straight buy-vs-build decision.

Apify's entire business is keeping social-media scrapers alive. When Instagram changes its HTML, rotates a GraphQL `doc_id`, or flags a proxy range — that is *their problem to solve*, and they solve it in hours because every one of their paying customers demands it. Their Instagram Scraper actor already handles: residential proxy rotation, browser fingerprint randomization, TLS `ja3` hash rotation, login-wall bypass, and the actual GraphQL endpoint tracking. We inherit a ~99% success rate without writing a line of anti-bot code.

**Cost check:** Apify's free tier gives $5/mo in renewing credits. The `apify/instagram-scraper` actor costs roughly $0.003 per post on pay-per-result pricing — meaning ~1,600 posts per month on the free tier alone, comfortably covering one account fetched daily with ~20 posts each run. At the eventual scale of 1,000 profiles refreshed daily, this becomes ~$150/mo once incremental sync (see below) is in place — cheaper than one engineer-day per month of fighting scraper rot ourselves.

**What we give up:** vendor lock-in and loss of control over the scrape layer itself. Both are mitigated by the fact that `fetch.py` is a single flat file — swapping Apify for `instaloader`, a custom Playwright rig, or a different vendor is a ~1-day swap behind the same `posts.json` contract.

---

## 2. What happens when Instagram changes structure or blocks IP

Three distinct failure modes, each with its own detection and response path:

### Failure mode A — Instagram blocks Apify's proxy pool
Apify's ops team notices within minutes (every paying customer's actor fails simultaneously — they have monitoring we couldn't match at our scale). Typical time-to-fix is hours. Our `fetch.py` surfaces the failure as a non-zero exit + the Apify run ID printed to stderr, so we can [check the run in their dashboard](https://console.apify.com/actors/runs) and, if needed, link the run ID in a support ticket. **Our action: wait, retry, move on.**

### Failure mode B — Instagram changes the response schema
This is the quiet-failure case. IG adds a new post type or renames `timestamp` to `publishedAt`; Apify's actor keeps "succeeding" but returns fields our normalizer doesn't recognize.

Today, this is caught two ways:
- `normalize_post()` skips unknown `type` values with a warning to stderr rather than silently dropping data.
- The `/health` endpoint exposes `post_count` and `fetched_at`, so if a fetch returns zero posts or goes stale, we notice on the next check.

**What's missing (honestly):** production would add a scheduled `fetch.py` run + a Slack webhook on non-zero exit or when `post_count` drops suddenly, plus a per-field schema validator that asserts the *presence* of required fields (not their values). That's a 2-hour follow-up, not in scope for this submission — but the hook is already the script's exit code.

### Failure mode C — Apify retires the actor
Unlikely but plannable. Because `fetch.py` is ~100 lines with one call into Apify, a swap to `instaloader` (free, self-hosted, ~1 day of work to harden rate-limit handling) or a different Apify actor (`apidojo/instagram-scraper` is a near-drop-in alternative) leaves the `posts.json` contract — and therefore the API and any frontend — completely unchanged. This is why I chose *not* to introduce a `ScraperAdapter` protocol: the swap is cheap enough that the abstraction is YAGNI at this scope.

---

## 3. Scaling from 1 account to thousands

Today: one hardcoded username, one JSON file, one CLI call. That works for the demo and scales to zero accounts at 3am. Here's the architecture I'd move to for 1,000+ accounts refreshed daily.

```
 ┌──────────────────┐
 │ accounts table   │       ┌──────────────────────────┐
 │ (Postgres)       │ ───▶  │ scheduler                │
 │ - username        │      │ (cron / EventBridge)     │
 │ - last_synced_at  │      │ for each account due:    │
 │ - last_shortcode  │      │   enqueue(username,      │
 └──────────────────┘       │           since_shortcode)│
                            └────────────┬─────────────┘
                                         ▼
                             ┌─────────────────────┐
                             │ job queue           │
                             │ (SQS / Redis)       │
                             └───┬──────┬──────┬───┘
                                 ▼      ▼      ▼
                             worker  worker  worker    (autoscaled)
                                 │      │      │
                                 └──────┴──────┘
                                        │
                                        ▼
                            ┌──────────────────────┐
                            │ Apify Scraper API    │
                            │ (concurrent runs)    │
                            └──────────┬───────────┘
                                       ▼
                            ┌──────────────────────┐
                            │ normalizer           │
                            │ + schema validator   │◀──── Slack / PagerDuty
                            │ (fails loudly)       │      on drift
                            └──────────┬───────────┘
                                       │
                        ┌──────────────┼──────────────┐
                        ▼                             ▼
              ┌─────────────────┐          ┌────────────────────┐
              │ Postgres        │          │ S3 / R2            │
              │ (posts, media   │          │ media rehost       │
              │  rows, indexes  │          │ (IG CDN URLs       │
              │  on username,   │          │  expire!)          │
              │  shortcode)     │          └────────────────────┘
              └────────┬────────┘
                       │
                       ▼
              same FastAPI shape,
              reads from Postgres
              instead of posts.json
```

Six things change at scale; the rest of the architecture is recognizably the same:

1. **Queue-first.** `fetch.py` becomes a worker consuming one `(username, since_shortcode)` job at a time. The CLI becomes a thin wrapper that enqueues a single job — useful for manual backfills.
2. **Incremental sync.** After the initial backfill per account, we only fetch posts newer than `last_shortcode`. This reduces Apify spend roughly **20×** in steady state, because a typical active account produces ~1 new post per refresh cycle, not 20.
3. **Media rehosting is non-negotiable for a digital-legacy product.** Instagram CDN URLs are signed and expire in roughly two weeks. For a demo that's fine; for a product whose entire promise is "we preserve this forever," we *must* download the bytes and store them in our own object storage within the same worker run.
4. **Per-account circuit breaker.** One account blocked by Instagram shouldn't stall the queue. Track consecutive failures per username; on N in a row, skip for exponentially backed-off cooldown and page the on-call after 24h.
5. **Cost controls.** Per-account monthly budget in the accounts table + Apify's own daily spend cap as a backstop. Alert on anomalous burn (e.g., runaway retry loop).
6. **Observability.** Every fetch logs the Apify run ID + item count; dashboards surface per-account freshness and any account stale more than its SLA. Drift detector (see section 2B) runs on every fetch, not just scheduled checks.

And one shape choice that pays off later: the normalizer output is already platform-neutral enough that sibling adapters for TikTok, Facebook, and YouTube slot into the same downstream pipeline. That's explicitly why `source: "apify"` is a field in the feed shape — it becomes `"tiktok-apify"`, `"facebook-playwright"`, etc.

---

## Honest limitations of this submission

- Single hardcoded username (`DEFAULT_USERNAME = "gloriya_glor"` in `fetch.py`). Override by passing an argument: `python fetch.py another_handle`.
- No database. JSON file only. Fine for the demo; deliberately not built out (see scale section).
- **Media URLs expire** (IG CDN). The `posts.json` committed here will show broken images in a few weeks. Production fix described in scale section; out of scope here to keep the implementation under 4 hours.
- No scheduled fetches. One-shot CLI only.
- No automated tests. One manual end-to-end smoke run before submission is the verification.
- No rate-limit or retry logic in `fetch.py` — Apify handles it on their side. If the local run itself fails, re-run.
- No auth on the API. It's a read-only demo endpoint with CORS `*`.
- The `apify/instagram-scraper` actor occasionally returns `type` values I haven't mapped (`"IGTV"` edge cases, new reel shapes). The normalizer warns and skips those items rather than crashing — this was a deliberate choice to favor graceful degradation over completeness.

---

## Week 2, if this moves forward

Five concrete next steps in the order I'd take them:

1. **Cron + Slack drift alert.** `fetch.py` every N hours on Fly or a small EC2; exit-code-non-zero → Slack webhook. ~2 hours.
2. **Supabase persistence.** Replace `posts.json` with `posts` and `media` tables; `api.py` reads from DB. ~4 hours including schema + migrations.
3. **Incremental sync.** `--since <shortcode>` flag on `fetch.py`; accounts table with `last_shortcode` watermark. ~4 hours.
4. **S3/R2 media rehosting.** Background worker downloads media bytes into our bucket, rewrites URLs. ~1 day.
5. **Multi-platform adapter shape.** Generalize the normalizer; add TikTok scraper as the second source using the same contract. ~1 day for TikTok alone; the shape proves out.

---

## References

- [Apify Instagram Scraper](https://apify.com/apify/instagram-scraper) — the actor this project uses
- [Apify Python client](https://pypi.org/project/apify-client/)
- [Apify pricing / free tier](https://apify.com/pricing)
- [Instagram Basic Display API deprecation (Meta, Sept 2024)](https://developers.facebook.com/blog/post/2024/09/04/update-on-instagram-basic-display-api/)
- [Scrapfly: How to Scrape Instagram in 2026](https://scrapfly.io/blog/posts/how-to-scrape-instagram) — landscape confirmation
- [hiQ Labs v. LinkedIn](https://en.wikipedia.org/wiki/HiQ_Labs_v._LinkedIn) — US precedent on public-data scraping
<img width="2535" height="2016" alt="image" src="https://github.com/user-attachments/assets/aa9d4a74-21c9-4db7-8dce-9a5815f06872" />
