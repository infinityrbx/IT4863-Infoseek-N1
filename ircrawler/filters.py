"""Decide which URLs / responses are NOT content pages.

`skip_reason_for_url` runs before a request is made (cheap, URL only).
`skip_reason_for_response` runs after download (status, content type, page text).
Both return a short reason string, or None if the page is fine. The reasons are
counted in the crawl stats, so the report can say e.g. "1 234 pagination URLs skipped".

Patterns lean towards Vietnamese university sites (WordPress, Joomla, Liferay,
ASP.NET portals). Add your own in EXTRA_* below after looking at real URLs.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlsplit

NON_HTML_EXT = {
    # documents
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "odp", "rtf", "txt", "csv",
    # images
    "jpg", "jpeg", "png", "gif", "bmp", "svg", "webp", "ico", "tif", "tiff", "heic",
    # media
    "mp3", "mp4", "avi", "mov", "wmv", "flv", "mkv", "webm", "wav", "ogg", "m4a",
    # archives / binaries
    "zip", "rar", "7z", "gz", "tar", "bz2", "exe", "msi", "dmg", "apk", "iso", "bin",
    # web assets / data
    "css", "js", "json", "xml", "rss", "atom", "woff", "woff2", "ttf", "eot", "map",
}

LOGIN_RE = re.compile(
    r"/(login|logout|log-in|signin|sign-in|signup|sign-up|register|registration|dk|dang-nhap|dang-ky|dang-xuat"
    r"|wp-login\.php|wp-admin|user/login|user/register|auth|sso|cas/login|account|my-account"
    r"|c/portal/login|admin|administrator)(/|$|\?)",
    re.I,
)
SEARCH_RE = re.compile(r"/(search|tim-kiem|timkiem|tra-cuu|ket-qua-tim-kiem)(/|$|\?)", re.I)
SEARCH_PARAMS = {"s", "q", "query", "search", "keyword", "keywords", "tukhoa", "searchword", "k"}
PAGINATION_RE = re.compile(r"/((page|trang)/\d+|(page|trang)-\d+)/?$", re.I)  # /page/2, NukeViet /page-2
PAGINATION_PARAMS = {
    # note: WordPress uses ?p=123 for a post id, so "p" is NOT treated as pagination
    "page", "paged", "pg", "start", "offset", "limitstart", "trang", "pageindex",
    "cur", "cpage", "_page",
}
# Liferay/portlet & calendar traps that generate infinite URL variants.
TRAP_PARAMS = {"p_p_id", "p_p_lifecycle", "p_p_state", "p_p_mode", "redirect", "returnurl",
               "return_url", "replytocom", "print", "format", "lang_switch", "sort", "order",
               "orderby", "filter", "view", "month", "year", "date", "calendar",
               "download"}  # NukeViet attachment links: ?download=1&id=0
FEED_RE = re.compile(r"/(feed|rss|atom|wp-json|xmlrpc\.php|trackback|embed)(/|$)", re.I)
TAG_ARCHIVE_RE = re.compile(r"/(tag|tags|author|category-feed|attachment)/", re.I)

ERROR_TITLE_RE = re.compile(
    r"(\b(403|404|410|500|502|503)\b|not found|không tìm thấy|không tồn tại|"
    r"access denied|forbidden|bad request|^\s*lỗi\b|^\s*error\b)",
    re.I,
)

# Subdomains that are login portals, webmail, LMS, grade lookup, library catalogue search...
# Not public content and/or infinite search spaces. Used when subdomains are crawled.
EXCLUDED_HOSTS = {
    "mail.hust.edu.vn", "e.hust.edu.vn", "work.hust.edu.vn", "lms.hust.edu.vn",
    "ctt.hust.edu.vn", "ctt-sis.hust.edu.vn", "ctt-daotao.hust.edu.vn", "sv-ctt.hust.edu.vn",
    "sis.hust.edu.vn", "qldt.hust.edu.vn", "tradiem.hust.edu.vn", "connect.hust.edu.vn",
    "nhaphoc.hust.edu.vn", "dangkytuyensinh.hust.edu.vn", "kqmb.hust.edu.vn", "kqtsmb.hust.edu.vn",
    "libopac.hust.edu.vn", "dlib.hust.edu.vn", "dkhsdh.hust.edu.vn",
}

EXTRA_SKIP_PATH_RE: re.Pattern | None = None  # e.g. re.compile(r"/lich-cong-tac/", re.I)

MAX_URL_LENGTH = 400
MAX_PATH_DEPTH = 12


def skip_reason_for_url(url: str, *, skip_tag_archives: bool = False) -> str | None:
    parts = urlsplit(url)
    path = parts.path or "/"
    if parts.scheme not in ("http", "https"):
        return "scheme"
    if len(url) > MAX_URL_LENGTH or path.count("/") > MAX_PATH_DEPTH:
        return "too_long"
    last = path.rsplit("/", 1)[-1]
    if "." in last:
        ext = last.rsplit(".", 1)[-1].lower()
        if ext in NON_HTML_EXT:
            return "non_html_ext"
    if LOGIN_RE.search(path):
        return "login"
    if SEARCH_RE.search(path):
        return "search"
    if FEED_RE.search(path):
        return "feed"
    if PAGINATION_RE.search(path):
        return "pagination"
    if skip_tag_archives and TAG_ARCHIVE_RE.search(path):
        return "tag_archive"
    if EXTRA_SKIP_PATH_RE is not None and EXTRA_SKIP_PATH_RE.search(path):
        return "extra_rule"

    keys = {k.lower() for k, _ in parse_qsl(parts.query, keep_blank_values=True)}
    if keys & SEARCH_PARAMS:
        return "search"
    if keys & PAGINATION_PARAMS:
        return "pagination"
    if keys & TRAP_PARAMS:
        return "query_trap"
    return None


def skip_reason_for_response(response, *, min_text_chars: int = 0, text: str | None = None) -> str | None:
    if response.status >= 400:
        return f"http_{response.status // 100}xx"
    ctype = response.headers.get(b"Content-Type", b"").decode("latin-1").lower()
    if ctype and "html" not in ctype:
        return "non_html_type"
    if not hasattr(response, "css"):
        return "non_html_type"
    title = (response.css("title::text").get() or "").strip()
    if title and ERROR_TITLE_RE.search(title) and len(title) < 80:
        return "soft_error"
    # Pages that are only a login form, even if the URL looked harmless.
    if response.css('input[type="password"]') and len(response.css("p").getall()) < 3:
        return "login"
    if min_text_chars and text is not None and len(text) < min_text_chars:
        return "thin_content"
    return None
