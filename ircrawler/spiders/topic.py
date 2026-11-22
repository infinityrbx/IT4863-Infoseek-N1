"""Group project: topic-focused (best-first) crawler.

    scrapy crawl topic -a config=topics/example_tuyen_sinh.yaml
    scrapy crawl topic -a config=topics/my_topic.yaml -O output/my_topic.jsonl -s CLOSESPIDER_PAGECOUNT=500

For every fetched HTML page the spider extracts: outgoing links + anchor text, meta tags
(description, keywords, og:*, canonical), title/h1, main content (trafilatura) and
publish time, then scores it against the topic keywords. Pipelines then drop off-topic
pages (unless save_off_topic: true) and mark exact / near duplicates.

Focused crawling policy:
  * links are only followed from on-topic pages, or from up to `off_topic_tunnel`
    consecutive off-topic pages (so the crawler can cross a hub page);
  * links whose anchor text / URL mention a keyword get a higher priority, so they
    are fetched first.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import scrapy

from ..extract import (extract_headings, extract_links, extract_main_text, extract_meta,
                       extract_publish_time, fallback_text, now_iso)
from ..filters import skip_reason_for_response, skip_reason_for_url
from ..topic import TopicConfig, TopicScorer
from ..urlnorm import configure as configure_urlnorm, host_of, in_domain, normalize_url


class TopicSpider(scrapy.Spider):
    name = "topic"
    custom_settings = {
        "FEEDS": {"output/topic_pages.jsonl": {"format": "jsonlines", "mode": "overwrite"}},
        "ITEM_PIPELINES": {
            "ircrawler.pipelines.TopicFilterPipeline": 100,
            "ircrawler.pipelines.DuplicatePipeline": 200,
        },
    }

    def __init__(self, config="topics/example_tuyen_sinh.yaml", summary=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cfg = TopicConfig.load(config)
        self.scorer = TopicScorer(self.cfg)
        self.summary_path = summary or f"output/topic_summary_{Path(config).stem}.json"
        self.fetched = 0
        self.on_topic = 0
        self.skipped: Counter = Counter()
        self.logger.info("Topic '%s': %d keywords, min_score=%s, seeds=%s",
                         self.cfg.name, len(self.cfg.keywords), self.cfg.min_score, self.cfg.seeds)

    async def start(self):
        for req in self.start_requests():
            yield req

    def start_requests(self):
        configure_urlnorm(self.settings)
        for url in self.cfg.seeds:
            yield scrapy.Request(normalize_url(url), callback=self.parse,
                                 meta={"depth": 0, "tunnel": 0}, priority=1000)

    def _allowed(self, url: str) -> bool:
        return in_domain(url, self.cfg.allowed_domains, include_subdomains=self.cfg.include_subdomains)

    def parse(self, response):
        url = normalize_url(response.url)
        depth = response.meta.get("depth", 0)
        if not self._allowed(url):
            self.skipped["redirect_offsite"] += 1
            return
        reason = skip_reason_for_url(url) or skip_reason_for_response(response)
        if reason and reason != "pagination":
            self.skipped[reason] += 1
            return

        html = response.text
        text = extract_main_text(html, url) or fallback_text(response)
        meta = extract_meta(response)
        heads = extract_headings(response)
        links = extract_links(response)
        self.fetched += 1

        topic = self.scorer.score_page({
            "title": heads["title"] + " " + meta["og"].get("og:title", ""),
            "h1": " ".join(heads["h1"]),
            "description": meta["description"] or "",
            "keywords": " , ".join(meta["keywords"]),
            "url": url.replace("-", " ").replace("/", " "),
            "text": text,
        })
        is_listing = reason == "pagination" or len(text) < self.cfg.min_text_chars
        if topic["on_topic"]:
            self.on_topic += 1
        tunnel = 0 if topic["on_topic"] else response.meta.get("tunnel", 0) + 1

        if not is_listing:
            yield {
                "url": url,
                "fetched_url": response.url,
                "status": response.status,
                "depth": depth,
                "fetched_at": now_iso(),
                "title": heads["title"],
                "h1": heads["h1"],
                "meta": meta,
                "publish_time": extract_publish_time(response, html),
                "text": text,
                "text_chars": len(text),
                "links": links,
                "n_links": len(links),
                "topic": {"name": self.cfg.name, **topic},
            }

        # ---- focused link following
        if depth >= self.cfg.max_depth or tunnel > self.cfg.off_topic_tunnel:
            return
        for link in links:
            target = link["url"]
            if link["nofollow"] or not self._allowed(target):
                continue
            r = skip_reason_for_url(target)
            if r and r != "pagination":
                continue
            link_score = self.scorer.score_link(link["anchor"], target)
            priority = int(10 * link_score) + (5 if topic["on_topic"] else 0) - depth
            yield response.follow(target, callback=self.parse, priority=priority,
                                  meta={"depth": depth + 1, "tunnel": tunnel})

    def closed(self, reason):
        stats = self.crawler.stats
        summary = {
            "topic": self.cfg.name,
            "finished_reason": reason,
            "pages_fetched_and_parsed": self.fetched,
            "pages_on_topic": self.on_topic,
            "harvest_rate": round(self.on_topic / self.fetched, 4) if self.fetched else None,
            "items_saved": stats.get_value("ir/items_saved", 0),
            "dropped_off_topic": stats.get_value("ir/dropped_off_topic", 0),
            "exact_duplicates": stats.get_value("ir/exact_duplicates", 0),
            "near_duplicates": stats.get_value("ir/near_duplicates", 0),
            "skipped_by_reason": dict(self.skipped.most_common()),
            "finished_at": now_iso(),
        }
        Path(self.summary_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.summary_path).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        self.logger.info("Harvest rate %s (%d/%d). Summary: %s", summary["harvest_rate"],
                         self.on_topic, self.fetched, self.summary_path)
