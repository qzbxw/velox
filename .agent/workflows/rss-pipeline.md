---
description: RSS news pipeline — fetch, cache, summarize, distribute
---

# RSS News Pipeline Workflow

// turbo-all

## Architecture Overview

```
Scheduler (every 15 min)
   └── rss_engine.fetch_all()
          ├── 50+ publisher RSS feeds (parallel, with ETag)
          ├── 11 Google News dynamic queries
          └── Deduplicate by GUID + title normalisation
                 └── In-memory cache (TTL = 24h)

Consumer Request (overview, hedge chat, scheduler)
   └── news_summarizer.get_digest()
          ├── Filter by category limits
          ├── Check digest cache (30min TTL)
          └── Call Flash-Lite AI for scored summary
                 └── Return compact 500-token digest
```

## Key Files

| File | Purpose |
|---|---|
| `bot/rss_engine.py` | Feed registry, async fetcher with ETag, deduplication, cache |
| `bot/news_summarizer.py` | AI subagent for pre-summarization via Flash-Lite |
| `bot/market_overview.py` | Main Hedge Agent — consumes digests from above modules |
| `bot/scheduler.py` | `refresh_news_cache` job runs every `RSS_REFRESH_INTERVAL_MIN` |
| `bot/config.py` | Configuration knobs for RSS + summarizer |

## How to Add a New RSS Feed

1. Open `bot/rss_engine.py`
2. Add a `FeedConfig` entry to `FEED_REGISTRY`:
   ```python
   FeedConfig("Source Name", "https://example.com/rss", "category", tier)
   ```
   - `category`: one of `crypto`, `defi`, `regulatory`, `politics`, `macro`, `tech`, `research`, `ru_news`
   - `tier`: 1 (critical), 2 (standard), 3 (optional/noisy)
3. Add a domain→name mapping in `SOURCE_DOMAINS` dict (for Google News attribution)
4. Restart the bot. The new feed will be picked up on the next refresh cycle.

## How to Add a Google News Topic Query

1. Open `bot/rss_engine.py`
2. Add an entry to `GOOGLE_NEWS_QUERIES`:
   ```python
   {"query": "your search query", "category": "category"}
   ```
3. The query is automatically converted to a Google News RSS URL with `when:1d` filter.

## Configuration (.env)

| Variable | Default | Description |
|---|---|---|
| `RSS_REFRESH_INTERVAL_MIN` | 15 | How often to refresh RSS cache (minutes) |
| `RSS_ARTICLE_TTL_HOURS` | 24 | How long articles stay in cache |
| `RSS_FETCH_TIMEOUT` | 12 | Per-feed HTTP timeout (seconds) |
| `NEWS_SUMMARIZER_ENABLED` | true | Toggle AI pre-summarization |
| `NEWS_SUMMARIZER_MODEL` | gemini-2.0-flash-lite | LLM model for summarization |

## ETag Caching

The engine sends `If-None-Match` / `If-Modified-Since` headers on subsequent requests:
- If the server returns `304 Not Modified`, no XML is downloaded → saves bandwidth
- ETag values are cached in-memory per URL

## Deduplication

Two layers:
1. **GUID dedup** — BBC-style `#0, #1` suffix stripping before set lookup
2. **Title dedup** — normalised lowercase title matching to catch reposts across sources

## Monitoring

Check logs for:
```
RSS Engine: fetched 142 articles from 62 feeds (43200.0s ago cutoff)
News Summarizer: produced 890-char digest from 40 articles
RSS cache refreshed: 142 articles, age=0s
```

Warning patterns:
```
RSS timeout: <feed name>           — feed is slow, consider raising RSS_FETCH_TIMEOUT
RSS <feed> returned 403            — Cloudflare block, may need curl_cffi in future
News Summarizer API error 429      — Gemini rate limit, digest falls back to simple list
```

## Testing a Single Feed

```bash
python -c "
import asyncio
from bot.rss_engine import rss_engine

async def test():
    articles = await rss_engine.fetch_all(since_hours=6)
    print(f'Total: {len(articles)}')
    cats = {}
    for a in articles:
        cats[a['category']] = cats.get(a['category'], 0) + 1
    for k, v in sorted(cats.items(), key=lambda x: -x[1]):
        print(f'  {k}: {v}')
    print()
    for a in articles[:5]:
        print(f'  [{a[\"category\"]}] {a[\"title\"]} — {a[\"source\"]}')

asyncio.run(test())
"
```

## Category Limits (Default)

Used when generating digests for the main Hedge Agent:

| Category | Overview | Hedge Chat |
|---|---|---|
| crypto | 12 | 8 |
| defi | 5 | 3 |
| regulatory | 4 | 3 |
| politics | 4 | 2 |
| macro | 4 | 2 |
| tech | 2 | — |
| ru_news | 2 | — |
