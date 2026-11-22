# IR crawler (IT4863) — Scrapy

Three spiders for the IT4863 Information Retrieval assignments:

| Spider | What it's for | Output |
|---|---|---|
| `site_count` | **T2**: estimate how many content pages `hust.edu.vn` has | `output/site_count_pages.jsonl`, `output/site_count_summary.json` |
| `hust` | **Nhiệm vụ 1**: crawl hust.edu.vn **and its subdomains**, saving each page's text for the search index | `output/hust_pages.jsonl`, `output/hust_summary.json`, `output/hust_skipped.json` |
| `sitemap_urls` | **T2**: list the URLs the site declares in its `sitemap.xml`, to compare with the crawl | `output/sitemap_urls.jsonl` |
| `topic` | **Group project (BTL)**: focused crawler for a topic you choose | `output/topic_pages.jsonl`, `output/topic_summary_<config>.json` |

## Setup

Use Python 3.10 or newer.

```bash
cd crawler
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest tests             # optional: 6 quick unit tests (needs `pip install pytest`)
```

Run every `scrapy crawl ...` command from the `crawler/` folder (where `scrapy.cfg` is).

Before a real crawl, put your group name or contact in `USER_AGENT` in `ircrawler/settings.py`.

## Politeness (already on)

`ircrawler/settings.py` sets these:

- obey `robots.txt`
- wait 2 s between requests to the same site (with ±50% jitter), and slow down automatically if the server gets slow (AutoThrottle)
- one request at a time per site (hust.edu.vn starts answering 429 "Too Many Requests" above ~30 pages/min)
- on a 429, `ircrawler/middlewares.py` raises the delay (to the server's `Retry-After`, or doubles it) and retries the page up to 5 times
- no cookies
- crawl breadth-first

Don't lower the delay on the university's servers. To test without hitting the network twice, add `-s HTTPCACHE_ENABLED=1`. Re-runs then come from the disk cache in `.scrapy/httpcache`.

Useful options for any spider:

```bash
-s CLOSESPIDER_PAGECOUNT=500     # stop after 500 responses (quick sample)
-s CLOSESPIDER_TIMEOUT=3600      # stop after 1 hour
-s JOBDIR=crawls/run1            # pause with Ctrl+C once, resume by re-running the same command
-O output/other_name.jsonl       # write items to a different file (overwrites)
```

**Pause and resume (`site_count`).** With `-s JOBDIR=...`, press Ctrl+C **once** and wait for `Spider closed`. Rerun the same command to continue. The pages file is appended to, and the totals in the summary include the pages counted before the pause. To start a crawl over from scratch, delete both `output/` and the `crawls/...` folder first.

---

## Nhiệm vụ 1: crawl hust.edu.vn and its subdomains

```bash
caffeinate -i python -m scrapy crawl hust -s JOBDIR=crawls/hust
```

The command is the same as `site_count` with these defaults:

- **Subdomains are crawled.** It starts from hust.edu.vn and about 55 known content subdomains (admissions, students, the 6 schools, the faculties and the institutes; see `SUBDOMAIN_SEEDS` in `ircrawler/spiders/hust.py`). Any other `*.hust.edu.vn` found through links is crawled too.
- **Portals are excluded.** Login portals, webmail, the LMS, grade lookup and library-catalogue search (`EXCLUDED_HOSTS` in `ircrawler/filters.py`) are skipped. To add more, use `-a exclude_hosts=x.hust.edu.vn,y.hust.edu.vn`.
- **Each subdomain is capped** at 3,000 pages (`-a max_pages_per_host=...`, 0 = no cap). The main site isn't capped.
- **Each page stores its content.** Besides URL and title, every line has `text` (main content via trafilatura), `h1`, `meta`, `lang` and `publish_time`. That's the input for the search index.
- **Pages are cached** (gzipped, in `.scrapy/httpcache-hust`), so they can be re-extracted later without downloading again.
- **Speed:** each host still gets 1 request every 2 s, and 4 hosts are crawled in parallel.

`output/hust_summary.json` has the page count per subdomain (`content_pages_by_host`), which is what the report needs.

## T2: How many content pages does hust.edu.vn have?

### 1. Crawl the internal links

```bash
scrapy crawl site_count                                   # only hust.edu.vn (+ www.)
scrapy crawl site_count -a include_subdomains=1           # also soict.hust.edu.vn, ts.hust.edu.vn, ...
scrapy crawl site_count -a max_depth=3 -s CLOSESPIDER_PAGECOUNT=2000   # quick trial
```

Arguments (`-a name=value`):

| Argument | Default | Meaning |
|---|---|---|
| `start` | `https://hust.edu.vn/` | Start URL(s), comma-separated |
| `domains` | `hust.edu.vn` | Domains that count as internal |
| `include_subdomains` | `0` | `1` = `*.hust.edu.vn` is internal too |
| `max_depth` | `0` (no limit) | Maximum link hops from the start page |
| `follow_listing` | `1` | Fetch pagination and tag pages to find links, but don't count them |
| `count_tag_archives` | `0` | `1` = count `/tag/...` and `/author/...` pages as content |
| `dedup_content` | `1` | Don't count a page whose visible text is identical to a page already counted |

### What counts as a "content page"

A page is counted only if all of these are true:

- **Same site.** It is on `domains`, including after redirects.
- **Real HTML page.** It returns status 2xx with an HTML content type.
- **Not an error page.** Its title doesn't read like a soft 404 ("không tìm thấy", "404", ...).
- **Not a login page.** It isn't just a login form.
- **Not excluded by its URL.** Its URL doesn't look like any of these:
  - a file: `.pdf`, `.docx`, images, `.zip`, ...
  - login: `/dang-nhap`, `/login`, `wp-login.php`, ...
  - search: `/tim-kiem`, `?q=`, `?s=`, ...
  - a feed: `/feed`, `/rss`
  - pagination: `/page/2`, `?page=2`
  - a URL trap: `?sort=`, `?print=`, Liferay `p_p_id`, ...
- **Not already counted.** Its normalized URL, its `<link rel="canonical">` and its text haven't been counted yet.

### URL normalization

The code is in `ircrawler/urlnorm.py` and the tests are in `tests/test_core.py`. These variants are all treated as one page:

```text
http://hust.edu.vn/tin-tuc/abc/
https://www.hust.edu.vn/tin-tuc/abc
https://HUST.edu.vn:443/tin-tuc//abc#top
https://hust.edu.vn/tin-tuc/abc?utm_source=fb&fbclid=xyz
https://hust.edu.vn/tin-tuc/x/../abc/index.html
→ https://hust.edu.vn/tin-tuc/abc
```

The normalizer does the following:

- lowercases the host
- treats http as https
- treats `www.` as the same host
- removes default ports
- removes `#fragment`
- removes tracking and session params (`utm_*`, `fbclid`, `gclid`, `PHPSESSID`, ...)
- sorts the remaining query params
- resolves `..` and `//`
- removes `index.html`, and ignores the trailing `/` when deciding whether two URLs are the same page (requests keep the `/`, because hust.edu.vn redirects `/a` to `/a/`)

Two settings control the http/https and `www.` rules:

- **`-s IR_FORCE_HTTPS=0`** for a site that only works over http.
- **`-s IR_STRIP_WWW=0`** if `www.` is a different site.

To skip more URL patterns, add them to the lists in `ircrawler/filters.py`. For example, set `EXTRA_SKIP_PATH_RE` for a calendar section that generates endless URLs.

The crawl also writes `output/site_count_skipped.json`, which lists every skipped URL by reason. Skim it to check that no skip rule throws away real content pages.

### 2. Compare with the sitemap

```bash
scrapy crawl sitemap_urls                 # reads robots.txt "Sitemap:" + /sitemap.xml, /sitemap_index.xml, /wp-sitemap.xml
python scripts/compare_sitemap.py
```

The script prints the following:

- the crawl count and the sitemap count
- the overlap and the union
- a **capture-recapture (Lincoln–Petersen) estimate**, N ≈ |crawl| · |sitemap| / |crawl ∩ sitemap|

It also writes `output/only_in_crawl.txt` and `output/only_in_sitemap.txt`. Pages that are only in the sitemap are "orphan" pages that no link reaches, so a link crawl can't find them. Discuss that in the report.

### What to put in the T2 report

`output/site_count_summary.json` contains:

- `content_pages`
- pages per host and per depth
- skipped URLs by reason (`pagination`, `login`, `non_html_ext`, `duplicate_content`, ...)
- HTTP status counts

Together with the sitemap comparison, this gives you the number, how you got it, and what you excluded.

---

## Group project: topic-focused crawler

### 1. Describe your topic in a YAML file

Copy `topics/example_tuyen_sinh.yaml` (admissions at HUST) to `topics/<your_topic>.yaml` and edit it. Every key is commented in the example.

- `seeds`: start URLs
- `allowed_domains` and `include_subdomains`: the crawler never leaves these
- `keywords`: a list, or `keyword: weight`. Matching ignores case and Vietnamese diacritics, so `hoc may` matches `học máy`.
- `negative_keywords`: subtract points (e.g. `tuyển dụng` when your topic is admissions)
- `field_weights`: a keyword in the title counts more than one in the body (default title 3, h1 3, description 2, keywords 2, url 1, text 1)
- `min_score`: threshold for "on-topic"
- `max_depth`, `off_topic_tunnel`: how far to go, and through how many off-topic pages in a row
- `save_off_topic`, `drop_duplicates`, `near_dup_threshold`, `min_text_chars`

### 2. Run it

```bash
scrapy crawl topic -a config=topics/example_tuyen_sinh.yaml
scrapy crawl topic -a config=topics/my_topic.yaml -O output/my_topic.jsonl -s CLOSESPIDER_PAGECOUNT=1000
```

To tune `min_score`, set `save_off_topic: true`, run a small crawl and look at the `topic.score` values of pages you consider on-topic and off-topic.

### How it decides what to crawl

The crawler is best-first, in `ircrawler/spiders/topic.py`:

- every page is scored against the keywords
- links are followed from on-topic pages, and from at most `off_topic_tunnel` off-topic pages in a row, so it can pass through a hub page but not drift away
- links whose anchor text or URL contain a keyword get a higher Scrapy priority, so they are fetched first
- pages with less than `min_text_chars` of main text (hubs, listings) are used for links but not saved

The summary file reports the **harvest rate** (on-topic pages / fetched pages). This is the standard metric for a focused crawler and is worth putting in the report.

### Output: one JSON object per line

```jsonc
{
  "url": "https://ts.hust.edu.vn/...",            // normalized
  "fetched_url": "...", "status": 200, "depth": 2, "fetched_at": "2026-...",
  "title": "...", "h1": ["..."],
  "meta": {
    "description": "...", "keywords": ["..."], "author": null, "robots": null, "lang": "vi",
    "canonical": "https://...", "og": {"og:title": "...", "og:image": "...", "og:type": "article"}
  },
  "publish_time": {"value": "2026-03-10T09:00:00+07:00", "source": "json-ld"},
  "text": "main content extracted by trafilatura ...", "text_chars": 3456,
  "links": [{"url": "https://...", "anchor": "Điểm chuẩn 2026", "internal": true, "nofollow": false}],
  "n_links": 87,
  "topic": {"name": "...", "score": 21.0, "on_topic": true,
            "matched_keywords": ["tuyển sinh", "điểm chuẩn"], "per_field": {"title": 9.0, "text": 12.0}},
  "dedup": {"content_hash": "sha1...", "simhash": "16 hex digits",
            "exact_duplicate_of": null, "near_duplicate_of": "https://...", "near_duplicate_jaccard": 0.86}
}
```

### Where each field comes from

- **Links + anchor text.** Every `<a href>` on the page, normalized. Image links use `alt` or `title` as the anchor.
- **Main content.** `trafilatura.extract` removes menus, footers and sidebars. If it returns nothing, the crawler falls back to the plain visible text.
- **Publish time.** The crawler tries these sources in order and stops at the first that gives a date. `publish_time.source` records which one it used.
  1. `<meta>` tags such as `article:published_time`, `datePublished`, `dc.date`, ...
  2. JSON-LD `datePublished`
  3. `<time datetime>`
  4. trafilatura's date guess
  5. a date in the URL (`/2024/05/12/`, `-20240512`)
  6. a `dd/mm/yyyy` date near the top of the page
- **Duplicates.** This runs in `ircrawler/dedup.py`.
  - *Exact:* SHA-1 of the normalized main text.
  - *Near:* MinHash (128 permutations) of word 5-shingles, indexed with `datasketch.MinHashLSH`. A page whose estimated Jaccard similarity is at least `near_dup_threshold` to an earlier page gets `near_duplicate_of`.
  - *SimHash:* a 64-bit SimHash is also stored, so you can compare the two methods. Hamming distance ≤ 3 usually means near-duplicate.

## Project layout

```text
crawler/
├── scrapy.cfg
├── requirements.txt
├── ircrawler/
│   ├── settings.py          politeness, cache, normalization switches
│   ├── urlnorm.py           URL normalization + domain checks
│   ├── filters.py           skip rules (file types, login, search, pagination, errors)
│   ├── extract.py           links, meta, title/h1, trafilatura text, publish time
│   ├── dedup.py             content hash, MinHash LSH, SimHash
│   ├── topic.py             YAML topic config + keyword scorer
│   ├── pipelines.py         off-topic filter, duplicate marking
│   ├── middlewares.py       backs off on 429 Too Many Requests
│   └── spiders/
│       ├── hust.py          Nhiệm vụ 1: hust.edu.vn + subdomains, with page text
│       ├── site_count.py    T2 crawl
│       ├── sitemap_urls.py  T2 sitemap list
│       └── topic.py         BTL focused crawler
├── topics/example_tuyen_sinh.yaml
├── scripts/compare_sitemap.py
└── tests/test_core.py
```

## Troubleshooting

| Problem | What to do |
|---|---|
| **The crawl finds very few pages** | Check `skipped_unique_urls_by_reason` in the summary first. A rule in `filters.py` may be too broad for this site. |
| **A JavaScript-heavy page has no links or text** | Scrapy doesn't run JavaScript. Use the page's sitemap or API, or add `scrapy-playwright` for those pages only. |
| **The crawl is very slow** | That is the 2 s politeness delay at work. Run it overnight with `-s JOBDIR=crawls/t2`, so you can stop and resume it. |
