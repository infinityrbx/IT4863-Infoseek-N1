"""T2 (comparison): list every URL a site declares in its sitemap(s), without fetching pages.

    scrapy crawl sitemap_urls                       # hust.edu.vn
    scrapy crawl sitemap_urls -a site=https://soict.hust.edu.vn/

Looks at the `Sitemap:` lines in robots.txt plus /sitemap.xml, /sitemap_index.xml,
/wp-sitemap.xml, follows sitemap indexes, and writes one line per URL to
output/sitemap_urls.jsonl ({url, lastmod, sitemap, skip_reason}). Then run
scripts/compare_sitemap.py to compare it with the crawl.
"""

from __future__ import annotations

import gzip
from urllib.parse import urljoin

import scrapy
from lxml import etree

from ..filters import skip_reason_for_url
from ..urlnorm import configure as configure_urlnorm, normalize_url

COMMON_PATHS = ["/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml", "/sitemap-index.xml"]


class SitemapUrlsSpider(scrapy.Spider):
    name = "sitemap_urls"
    custom_settings = {
        "FEEDS": {"output/sitemap_urls.jsonl": {"format": "jsonlines", "mode": "overwrite"}},
    }

    def __init__(self, site="https://hust.edu.vn/", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.site = site if site.endswith("/") else site + "/"
        self.seen_urls: set[str] = set()

    async def start(self):
        for req in self.start_requests():
            yield req

    def start_requests(self):
        configure_urlnorm(self.settings)
        yield scrapy.Request(urljoin(self.site, "/robots.txt"), callback=self.parse_robots,
                             dont_filter=True)

    def parse_robots(self, response):
        found = []
        if response.status == 200:
            for line in response.text.splitlines():
                if line.lower().startswith("sitemap:"):
                    found.append(line.split(":", 1)[1].strip())
        self.logger.info("robots.txt lists %d sitemap(s)", len(found))
        for url in found + [urljoin(self.site, p) for p in COMMON_PATHS]:
            yield scrapy.Request(url, callback=self.parse_sitemap)

    def parse_sitemap(self, response):
        if response.status != 200:
            return
        body = response.body
        if body[:2] == b"\x1f\x8b":
            try:
                body = gzip.decompress(body)
            except OSError:
                return
        try:
            root = etree.fromstring(body, parser=etree.XMLParser(recover=True, resolve_entities=False))
        except etree.XMLSyntaxError:
            root = None
        if root is None:
            self.logger.warning("Not a sitemap: %s", response.url)
            return
        kind = etree.QName(root).localname

        def entries():
            for node in root:
                if not isinstance(node.tag, str):
                    continue
                d = {etree.QName(c).localname: (c.text or "").strip() for c in node if isinstance(c.tag, str)}
                if d.get("loc"):
                    yield d

        if kind == "sitemapindex":
            for entry in entries():
                yield scrapy.Request(entry["loc"], callback=self.parse_sitemap)
        elif kind == "urlset":
            for entry in entries():
                url = normalize_url(entry["loc"])
                if url in self.seen_urls:
                    continue
                self.seen_urls.add(url)
                yield {
                    "url": url,
                    "lastmod": entry.get("lastmod"),
                    "sitemap": response.url,
                    "skip_reason": skip_reason_for_url(url, skip_tag_archives=True),
                }
