"""Item pipelines for the topic spider."""

from __future__ import annotations

from scrapy.exceptions import DropItem

from .dedup import DuplicateDetector


class _CrawlerPipeline:
    def __init__(self, crawler):
        self.crawler = crawler

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    @property
    def cfg(self):
        return self.crawler.spider.cfg

    @property
    def stats(self):
        return self.crawler.stats


class TopicFilterPipeline(_CrawlerPipeline):
    """Drop pages below the topic score threshold (unless save_off_topic: true)."""

    def process_item(self, item, spider=None):
        if not item["topic"]["on_topic"] and not self.cfg.save_off_topic:
            self.stats.inc_value("ir/dropped_off_topic")
            raise DropItem(f"off-topic (score {item['topic']['score']})")
        return item


class DuplicatePipeline(_CrawlerPipeline):
    """Mark exact (content hash) and near (MinHash LSH) duplicates; optionally drop them."""

    detector: DuplicateDetector | None = None

    def process_item(self, item, spider=None):
        if self.detector is None:
            self.detector = DuplicateDetector(threshold=self.cfg.near_dup_threshold)
        dup = self.detector.check(item["url"], item.get("text") or "")
        item["dedup"] = dup
        if dup["exact_duplicate_of"]:
            self.stats.inc_value("ir/exact_duplicates")
        elif dup["near_duplicate_of"]:
            self.stats.inc_value("ir/near_duplicates")
        is_dup = bool(dup["exact_duplicate_of"] or dup["near_duplicate_of"])
        if is_dup and self.cfg.drop_duplicates:
            raise DropItem(f"duplicate of {dup['exact_duplicate_of'] or dup['near_duplicate_of']}")
        self.stats.inc_value("ir/items_saved")
        return item
