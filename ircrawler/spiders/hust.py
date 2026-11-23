"""Task 1 (Nhiệm vụ 1): crawl hust.edu.vn AND its subdomains, saving page content for indexing.

    python -m scrapy crawl hust -s JOBDIR=crawls/hust

Same counting/filtering rules as `site_count`, plus:
  * subdomains (*.hust.edu.vn) are crawled; login portals, webmail, LMS, grade lookup and
    library-catalogue search hosts are excluded (filters.EXCLUDED_HOSTS, extend with
    -a exclude_hosts=a.hust.edu.vn,b.hust.edu.vn);
  * each subdomain is capped at -a max_pages_per_host=3000 pages (the main site is not capped);
  * each page also stores main text (trafilatura), h1, meta tags, language and publish time,
    which is what the search index (Task 2) needs;
  * the HTTP cache is on, so pages can be re-extracted later without downloading them again.

Output: output/hust_pages.jsonl, output/hust_summary.json, output/hust_skipped.json
"""

from __future__ import annotations

from .site_count import SiteCountSpider

# Subdomains linked from hust.edu.vn that publish public content. Used as extra start URLs so
# that rarely-linked ones are reached too; any other *.hust.edu.vn found via links is crawled as well.
SUBDOMAIN_SEEDS = [
    # general / admissions / students
    "en", "ts", "ts-hn", "tsa", "tuyensinhdaihoc", "sdh", "ctsv", "svbk", "csv", "alumni",
    "congdoan", "ktx", "tuyendung", "bulletin", "library", "jst", "research", "htqt", "event",
    "dtlt", "clc", "bktech", "bk-fund", "xttn",
    # schools (trường)
    "soict", "sme", "scls", "smse", "sem", "seee",
    # faculties (khoa)
    "fami", "sofl", "fed", "fpt", "gdqp", "gdtc", "sep", "set", "sie", "mse", "see", "bme",
    # institutes / centres (viện)
    "iet", "fintech", "act", "ai4life", "aist", "bkcs", "icea", "navis", "vjiist", "inapro",
    "bmec", "srn", "qmfs",'research'
]


class HustSpider(SiteCountSpider):
    name = "hust"
    custom_settings = {
        "FEEDS": {"output/hust_pages.jsonl": {"format": "jsonlines", "mode": "overwrite"}},
        # Many subdomains are crawled in parallel (still 1 request at a time per host);
        # keep the total low because several of them share servers.
        "CONCURRENT_REQUESTS": 4,
        "HTTPCACHE_ENABLED": True,
        "HTTPCACHE_GZIP": True,
        "HTTPCACHE_DIR": "httpcache-hust",
        "HTTPCACHE_IGNORE_HTTP_CODES": [429, 500, 502, 503, 504],
    }

    def __init__(self, start=None, domains="hust.edu.vn", include_subdomains="1", save_content="1",
                 max_pages_per_host="3000", summary="output/hust_summary.json", *args, **kwargs):
        if start is None:
            start = ",".join(["https://hust.edu.vn/"] +
                             [f"https://{s}.hust.edu.vn/" for s in SUBDOMAIN_SEEDS])
        super().__init__(start=start, domains=domains, include_subdomains=include_subdomains,
                         save_content=save_content, max_pages_per_host=max_pages_per_host,
                         summary=summary, *args, **kwargs)
