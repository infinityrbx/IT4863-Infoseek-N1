"""Back off when the server says "429 Too Many Requests".

Scrapy's RetryMiddleware retries a 429 right away, at the same speed, which is what
got requests rejected again. This middleware instead:
  * raises the download delay for that site (to the Retry-After header if the server
    sends one, otherwise doubling it, capped at IR_429_MAX_DELAY seconds),
  * re-schedules the request, up to IR_429_MAX_RETRIES times.
AutoThrottle lowers the delay again slowly once responses are fine, but never below
DOWNLOAD_DELAY.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class TooManyRequestsMiddleware:
    def __init__(self, crawler):
        self.crawler = crawler
        s = crawler.settings
        self.max_retries = s.getint("IR_429_MAX_RETRIES", 5)
        self.max_delay = s.getfloat("IR_429_MAX_DELAY", 60.0)
        self.min_delay = max(s.getfloat("DOWNLOAD_DELAY", 1.0), 1.0)

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def _retry_after(self, response) -> float | None:
        value = response.headers.get(b"Retry-After")
        if not value:
            return None
        try:
            return float(value.decode("latin-1").strip())
        except ValueError:  # an HTTP date; just use the doubling rule
            return None

    def process_response(self, request, response, spider=None):
        if response.status != 429:
            return response
        stats = self.crawler.stats
        stats.inc_value("ir/http_429")

        slot_key = request.meta.get("download_slot")
        slot = self.crawler.engine.downloader.slots.get(slot_key) if slot_key else None
        if slot is not None:
            wanted = self._retry_after(response) or max(slot.delay * 2, self.min_delay * 2)
            new_delay = min(max(wanted, slot.delay), self.max_delay)
            if new_delay > slot.delay:
                logger.warning("429 from %s: slowing down, delay %.1fs -> %.1fs",
                               slot_key, slot.delay, new_delay)
                slot.delay = new_delay

        tries = request.meta.get("ir_429_tries", 0) + 1
        if tries > self.max_retries:
            stats.inc_value("ir/http_429_gave_up")
            logger.error("Gave up after %d x 429: %s", tries - 1, request.url)
            return response
        retry = request.replace(dont_filter=True, priority=request.priority - 1)
        retry.meta["ir_429_tries"] = tries
        return retry
