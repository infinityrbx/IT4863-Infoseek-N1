"""T2: estimate how many content pages a site (default hust.edu.vn) has.

    scrapy crawl site_count                                   # hust.edu.vn only
    scrapy crawl site_count -a include_subdomains=1           # + soict.hust.edu.vn, ...
    scrapy crawl site_count -a max_depth=3 -s CLOSESPIDER_PAGECOUNT=2000   # quick sample

Output
  output/site_count_pages.jsonl    one line per counted content page
  output/site_count_summary.json   totals, per host/depth, skipped URLs by reason

A page is counted when: it is HTML, status 2xx, not an error/login page, not a
listing (pagination/tag archive) page, and its normalized URL (or <link rel=canonical>)
has not been counted before. Listing pages are still fetched so their links are found.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import scrapy

from ..extract import (extract_headings, extract_links, extract_main_text, extract_meta,
                       extract_publish_time, fallback_text, now_iso)
from ..filters import EXCLUDED_HOSTS, skip_reason_for_response, skip_reason_for_url
from ..urlnorm import configure as configure_urlnorm, host_of, in_domain, normalize_url, page_key

# Reasons for which we fetch the page (to discover links) but do not count it.
FOLLOW_ONLY = {"pagination", "tag_archive"}


def _flag(v) -> bool:
    return str(v).lower() in ("1", "true", "yes", "y")


class SiteCountSpider(scrapy.Spider):
    name = "site_count"
    custom_settings = {
        "FEEDS": {"output/site_count_pages.jsonl": {"format": "jsonlines", "mode": "overwrite"}},
    }

    @classmethod
    def update_settings(cls, settings):
        super().update_settings(settings)
        # With JOBDIR (pause/resume), append to the output instead of overwriting it,
        # so pages counted before the pause are kept.
        if settings.get("JOBDIR"):
            feeds = settings.getdict("FEEDS")
            for uri, opts in feeds.items():
                feeds[uri] = {**opts, "mode": "append"}
            settings.set("FEEDS", feeds, priority="spider")

    def __init__(self, start="https://hust.edu.vn/", domains="hust.edu.vn", include_subdomains="0",
                 max_depth="0", follow_listing="1", count_tag_archives="0", dedup_content="1",
                 save_content="0", exclude_hosts="", max_pages_per_host="0",
                 summary="output/site_count_summary.json", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seed_urls = [u.strip() for u in start.split(",") if u.strip()]
        self.domains = [d.strip() for d in domains.split(",") if d.strip()]
        self.include_subdomains = _flag(include_subdomains)
        self.max_depth = int(max_depth)
        self.follow_listing = _flag(follow_listing)
        self.skip_tag_archives = not _flag(count_tag_archives)
        self.summary_path = summary
        self.dedup_content = _flag(dedup_content)
        self.save_content = _flag(save_content)   # also store text/meta/date (for indexing)
        self.excluded_hosts = set(EXCLUDED_HOSTS) | {h.strip().lower() for h in exclude_hosts.split(",")
                                                      if h.strip()}
        # Cap per subdomain (0 = no cap) so one huge or trap-like subdomain can't eat the crawl.
        # The main domain(s) themselves are never capped.
        self.max_pages_per_host = int(max_pages_per_host)
        self._bind_state({})

    def _bind_state(self, state: dict) -> None:
        """Keep all counters inside one dict. With -s JOBDIR=..., Scrapy saves `self.state`
        when the crawl is paused and restores it on resume, so totals survive a pause."""
        state.setdefault("content_hashes", set())     # exact-duplicate bodies under different URLs
        state.setdefault("counted", set())            # normalized URL / canonical keys
        state.setdefault("skipped", defaultdict(set))
        for k in ("by_host", "by_depth", "statuses", "external_hosts"):
            state.setdefault(k, Counter())
        self.content_hashes = state["content_hashes"]
        self.counted = state["counted"]
        self.skipped = state["skipped"]
        self.by_host = state["by_host"]
        self.by_depth = state["by_depth"]
        self.statuses = state["statuses"]
        self.external_hosts = state["external_hosts"]

    async def start(self):  # Scrapy >= 2.13
        for req in self.start_requests():
            yield req

    def start_requests(self):  # Scrapy < 2.13 calls this directly
        configure_urlnorm(self.settings)
        if isinstance(getattr(self, "state", None), dict):  # set by Scrapy when JOBDIR is used
            self._bind_state(self.state)
            if not self.counted:
                self._rebuild_from_output()
            if self.counted:
                self.logger.info("Resuming: %d content pages already counted", sum(self.by_host.values()))
        self.seed_urls = [normalize_url(u) for u in self.seed_urls]
        for url in self.seed_urls:
            yield scrapy.Request(url, callback=self.parse, meta={"depth": 0})

    def _rebuild_from_output(self) -> None:
        """Resume of a run whose saved state has no counters (started before this was added):
        rebuild the page counts from the pages already written to the output file."""
        for uri in self.settings.getdict("FEEDS"):
            path = Path(str(uri))
            if not path.is_file():
                continue
            with path.open(encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    key = page_key(rec["url"])
                    if key in self.counted:
                        continue
                    self.counted.add(key)
                    if rec.get("canonical"):
                        self.counted.add(rec["canonical"])
                    self.by_host[rec.get("host") or host_of(rec["url"])] += 1
                    self.by_depth[rec.get("depth", 0)] += 1
            self.logger.info("Rebuilt counts from %s", path)

    def _host_skip_reason(self, url: str) -> str | None:
        host = host_of(url)
        if host in self.excluded_hosts:
            return "excluded_host"
        if (self.max_pages_per_host and host not in self.domains
                and self.by_host[host] >= self.max_pages_per_host):
            return "host_page_cap"
        return None

    def _content_fields(self, response, url: str) -> dict:
        html = response.text
        meta = extract_meta(response)
        heads = extract_headings(response)
        text = extract_main_text(html, url) or fallback_text(response)
        return {
            "h1": heads["h1"],
            "meta": meta,
            "lang": meta.get("lang"),
            "publish_time": extract_publish_time(response, html),
            "text": text,
            "text_chars": len(text),
        }

    def _skip(self, reason: str, url: str):
        url = page_key(url)
        self.skipped[reason].add(url)
        self.crawler.stats.inc_value(f"ir/skipped/{reason}")

    def parse(self, response):
        self.statuses[response.status] += 1
        url = normalize_url(response.url)
        depth = response.meta.get("depth", 0)

        # Redirected off-site (e.g. to an SSO login on another domain)?
        if not in_domain(url, self.domains, include_subdomains=self.include_subdomains):
            self._skip("redirect_offsite", url)
            return

        host_reason = self._host_skip_reason(url)
        if host_reason == "excluded_host":   # e.g. redirected to a login portal
            self._skip(host_reason, url)
            return
        reason = skip_reason_for_url(url, skip_tag_archives=self.skip_tag_archives)
        if reason and reason not in FOLLOW_ONLY:  # e.g. a redirect landed on /login
            self._skip(reason, url)
            return
        resp_reason = skip_reason_for_response(response)
        if resp_reason:
            self._skip(resp_reason, url)
            return

        count_it = reason is None
        if count_it:
            canonical = response.css('link[rel="canonical"]::attr(href)').get()
            ukey = page_key(url)
            key = ukey
            if canonical:
                c = page_key(response.urljoin(canonical))
                if in_domain(c, self.domains, include_subdomains=self.include_subdomains):
                    key = c
            body_hash = None
            if self.dedup_content:
                body_hash = hashlib.sha1(fallback_text(response).lower().encode("utf-8")).hexdigest()
            if key in self.counted or ukey in self.counted:
                self._skip("duplicate_canonical_or_redirect", url)
                count_it = False
            elif body_hash and body_hash in self.content_hashes:
                self._skip("duplicate_content", url)
                count_it = False
            else:
                if body_hash:
                    self.content_hashes.add(body_hash)
                self.counted.update({key, ukey})
                host = host_of(url)
                self.by_host[host] += 1
                self.by_depth[depth] += 1
                self.crawler.stats.inc_value("ir/content_pages")
                item = {
                    "url": url,
                    "canonical": key if key != ukey else None,
                    "host": host,
                    "depth": depth,
                    "status": response.status,
                    "title": (response.css("title::text").get() or "").strip(),
                    "referer": (response.request.headers.get("Referer") or b"").decode("latin-1") or None,
                    "fetched_at": now_iso(),
                }
                if self.save_content:
                    item.update(self._content_fields(response, url))
                yield item
        elif reason in FOLLOW_ONLY:
            self._skip(reason, url)
            if not self.follow_listing:
                return

        if self.max_depth and depth >= self.max_depth:
            return
        for link in extract_links(response):
            target = link["url"]
            if not in_domain(target, self.domains, include_subdomains=self.include_subdomains):
                self.external_hosts[host_of(target)] += 1
                continue
            r = self._host_skip_reason(target) or skip_reason_for_url(
                target, skip_tag_archives=self.skip_tag_archives)
            if r and not (r in FOLLOW_ONLY and self.follow_listing):
                self._skip(r, target)
                continue
            # Requests to the same normalized URL are deduplicated by Scrapy's dupefilter.
            yield response.follow(target, callback=self.parse, meta={"depth": depth + 1})

    def closed(self, reason):
        summary = {
            "finished_reason": reason,
            "start": self.seed_urls,
            "domains": self.domains,
            "include_subdomains": self.include_subdomains,
            "excluded_hosts": sorted(self.excluded_hosts) if self.include_subdomains else [],
            "content_pages": sum(self.by_host.values()),
            "content_pages_by_host": dict(self.by_host.most_common()),
            "content_pages_by_depth": dict(sorted(self.by_depth.items())),
            "skipped_unique_urls_by_reason": {k: len(v) for k, v in
                                              sorted(self.skipped.items(), key=lambda kv: -len(kv[1]))},
            "http_status_counts": dict(self.statuses),
            "top_external_hosts": dict(self.external_hosts.most_common(20)),
            "finished_at": now_iso(),
        }
        Path(self.summary_path).parent.mkdir(parents=True, exist_ok=True)
        # Every skipped URL, grouped by reason, so you can check the skip rules by eye.
        stem = Path(self.summary_path).stem.removesuffix("_summary")
        skipped_path = Path(self.summary_path).with_name(f"{stem}_skipped.json")
        skipped_path.write_text(json.dumps({k: sorted(v) for k, v in self.skipped.items()},
                                           ensure_ascii=False, indent=1), encoding="utf-8")
        Path(self.summary_path).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        self.logger.info("Counted %d content pages. Summary: %s", summary["content_pages"], self.summary_path)
