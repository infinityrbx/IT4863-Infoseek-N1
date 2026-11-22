"""Scrapy settings shared by all spiders.

Override anything on the command line, e.g.
    scrapy crawl site_count -s DOWNLOAD_DELAY=2 -s CLOSESPIDER_PAGECOUNT=500
"""

BOT_NAME = "ircrawler"

# --- URL normalization (see ircrawler/urlnorm.py) ---------------------------
IR_FORCE_HTTPS = True   # http://x and https://x are the same page; requests go to https
IR_STRIP_WWW = True     # www.hust.edu.vn == hust.edu.vn
IR_STRIP_TRAILING_SLASH = False  # keep "/" in request URLs (hust.edu.vn 301-redirects /a -> /a/);
                                 # counting always ignores it (urlnorm.page_key)
SPIDER_MODULES = ["ircrawler.spiders"]
NEWSPIDER_MODULE = "ircrawler.spiders"

# Identify yourself honestly. Put your group/contact in here before a real crawl.
USER_AGENT = "IT4863-IR-student-crawler/0.1 (+HUST course project; polite, robots.txt-respecting)"

# --- Politeness -------------------------------------------------------------
ROBOTSTXT_OBEY = True
# hust.edu.vn starts answering 429 (Too Many Requests) at ~30 pages/min with 2 parallel
# requests, so: one request at a time, at least 2 s apart.
DOWNLOAD_DELAY = 2.0                 # seconds between requests to the same site
DOWNLOAD_DELAY_JITTER = 0.5          # actual delay is 0.5x .. 1.5x of DOWNLOAD_DELAY
CONCURRENT_REQUESTS = 8
CONCURRENT_REQUESTS_PER_DOMAIN = 1
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 2.0
AUTOTHROTTLE_MAX_DELAY = 30.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0
DOWNLOAD_TIMEOUT = 30
RETRY_TIMES = 2
# 429 is handled by our own middleware (slows down, then retries), not by RetryMiddleware.
RETRY_HTTP_CODES = [408, 500, 502, 503, 504, 522, 524]
DOWNLOADER_MIDDLEWARES = {"ircrawler.middlewares.TooManyRequestsMiddleware": 560}
IR_429_MAX_RETRIES = 5
IR_429_MAX_DELAY = 60.0

# Don't download huge files (PDF/video that slipped through the URL filter).
DOWNLOAD_MAXSIZE = 10 * 1024 * 1024
DOWNLOAD_WARNSIZE = 0

# Breadth-first order: better for "how big is the site" and for focused crawling.
DEPTH_PRIORITY = 1
SCHEDULER_DISK_QUEUE = "scrapy.squeues.PickleFifoDiskQueue"
SCHEDULER_MEMORY_QUEUE = "scrapy.squeues.FifoMemoryQueue"

# Keep error responses so the spider can count them instead of silently dropping.
HTTPERROR_ALLOW_ALL = True

# Cookies are not needed and can create session-id URL variants.
COOKIES_ENABLED = False

# Cache pages on disk while developing so re-runs don't hit the server again.
# Turn on with:  -s HTTPCACHE_ENABLED=1
HTTPCACHE_ENABLED = False
HTTPCACHE_DIR = "httpcache"
HTTPCACHE_EXPIRATION_SECS = 0

FEED_EXPORT_ENCODING = "utf-8"
LOG_LEVEL = "INFO"
REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
