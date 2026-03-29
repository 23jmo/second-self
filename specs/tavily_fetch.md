# Spec: fetch/tavily_fetch.py

**Purpose:** Fetch public information about the user via three Tavily searches,
deduplicate results by URL, cache to disk, and return a clean list of result
dicts for the downstream synthesizer.

---

## Environment variables (from .env)

| Variable | Required | Notes |
|----------|----------|-------|
| `TAVILY_API_KEY` | Yes | Raise `EnvironmentError` if missing |
| `USER_NAME` | Yes | May be `First_Last` — normalize underscores to spaces |
| `USER_EMAIL` | Yes | Used to extract domain for query 2 |

Load with `python-dotenv`. Fail fast with a clear message if any required var is absent.

---

## Name normalization

Before building any query string:

```python
user_name = os.environ["USER_NAME"].replace("_", " ")
# "Vin_Chutijirawong" → "Vin Chutijirawong"
```

---

## The three queries

Run in order. All use `search_depth="basic"`, `max_results=5`.

| # | Query string | Notes |
|---|-------------|-------|
| q1 | `user_name` | e.g. `"Vin Chutijirawong"` |
| q2 | `user_name + " " + domain` | Domain = part after `@` in `USER_EMAIL`. Run even if it is a personal domain (gmail.com, yahoo.com, etc.) |
| q3 | `user_name + " github OR linkedin OR twitter"` | Literal string, single Tavily call |

Domain extraction:
```python
domain = USER_EMAIL.split("@")[1]   # "ravinc2016@gmail.com" → "gmail.com"
```

---

## Caching

- Cache file: `output/tavily_raw.json`
- TTL: **24 hours** (`fetched_at` unix timestamp stored in file)
- On every call: check if file exists AND `time.time() - fetched_at < 86400`
- If fresh → load from disk, return `results` list, skip all API calls
- If stale or missing → run queries, write new file
- `force_refresh=False` parameter on `fetch_tavily_data()` — pass `True` to bypass cache regardless of age (main.py passes `--no-cache` through as `force_refresh=True`)

---

## Partial failure handling

If any individual query raises an exception (network error, rate limit, invalid key, etc.):
- Log the error at `WARNING` level with the query string and exception message
- Skip that query and continue with the remaining ones
- Final result is the union of whichever queries succeeded
- If **all three** queries fail → log a warning, return `[]`, do not raise

---

## Deduplication

Deduplicate across all query results by URL (exact string match, case-sensitive).
When the same URL appears in multiple query results, **keep the one with the highest `score`**.

```python
# Pseudocode
seen: dict[str, dict] = {}
for result in all_results:
    url = result["url"]
    if url not in seen or result["score"] > seen[url]["score"]:
        seen[url] = result
final_results = list(seen.values())
```

---

## Result schema

Each result dict stored in the final list:

```python
{
    "url": str,       # original URL from Tavily
    "title": str,     # page title
    "content": str,   # snippet, truncated to 500 characters
    "score": float,   # Tavily relevance score
}
```

Content truncation:
```python
content = (result.get("content") or "")[:500]
```

No score filtering — all results (including score=0.0) are returned.

---

## Output file: `output/tavily_raw.json`

```json
{
  "fetched_at": 1743000000,
  "user_name": "Vin Chutijirawong",
  "user_email": "ravinc2016@gmail.com",
  "query_counts": {
    "q1": 5,
    "q2": 3,
    "q3": 4
  },
  "results": [
    { "url": "...", "title": "...", "content": "...", "score": 0.91 }
  ]
}
```

- `query_counts` reflects counts **before** deduplication (how many each query returned)
- `results` is the final deduplicated list
- Write atomically if possible (`tmp` file + rename) to avoid corrupt reads mid-run

---

## Public API

```python
def fetch_tavily_data(force_refresh: bool = False) -> list[dict]:
    """Fetch public Tavily results for the user. Returns deduplicated result dicts.

    Uses a 24h on-disk cache. Pass force_refresh=True to bypass.
    Returns an empty list (never raises) if all queries fail or return nothing.
    """
```

- Return type: `list[dict]` — each dict matches the result schema above
- If result count is 0 after deduplication: log `WARNING` and return `[]`
- Never raises for empty results or individual query failures

---

## CLI entrypoint

```python
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, ...)
    results = fetch_tavily_data()
    print(f"Fetched {len(results)} results")
    for r in results[:3]:
        print(f"  {r['score']:.2f}  {r['title']}  —  {r['url']}")
```

Prints:
1. Total result count
2. Top 3 results (by order in list) with score, title, and URL

---

## Module conventions

- `logging` only — no `print()` except in `__main__` block
- Type hints on all functions
- `output/` directory created with `Path.mkdir(parents=True, exist_ok=True)` before writing
- `CACHE_PATH = Path("output/tavily_raw.json")` as module-level constant
- `CACHE_MAX_AGE_HOURS = 24` as module-level constant
- Independently runnable: `python -m fetch.tavily_fetch`

---

## Error cases summary

| Condition | Behavior |
|-----------|----------|
| `TAVILY_API_KEY` missing | `EnvironmentError` with clear message |
| `USER_NAME` or `USER_EMAIL` missing | `EnvironmentError` with clear message |
| Single query fails | Log warning, skip, continue |
| All queries fail | Log warning, return `[]` |
| 0 results after dedup | Log warning, return `[]` |
| `output/` directory missing | Create it before writing |
| Cache file is corrupt JSON | Log warning, re-fetch fresh |
