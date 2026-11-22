"""URL normalization, so that one page is counted once.

Rules (each one is a choice you can defend in the report):
  * lowercase scheme and host, drop default ports (:80, :443)
  * http -> https (most sites serve the same page on both)
  * optionally drop a leading "www." (www.hust.edu.vn == hust.edu.vn)
  * drop the #fragment (it is the same page)
  * drop tracking / session query params (utm_*, fbclid, gclid, PHPSESSID, ...)
  * sort the remaining query params (?b=2&a=1 == ?a=1&b=2)
  * collapse duplicate slashes, resolve ./ and ../
  * drop the trailing slash (except for the root "/") -- for the *counting key* only
    (page_key). Request URLs keep it by default, because many CMSs (e.g. NukeViet on
    hust.edu.vn) answer /a with a 301 to /a/, which doubles the number of requests.
  * drop index files (/index.html, /index.php, /default.aspx)
"""

from __future__ import annotations

import posixpath
import re
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "msclkid", "yclid", "igshid", "mc_cid", "mc_eid",
    "ref", "ref_src", "referrer", "source", "_ga", "_gl", "zarsrc", "share",
    "phpsessid", "sessionid", "sid", "jsessionid", "aspsessionid", "cfid", "cftoken",
}
TRACKING_PREFIXES = ("utm_", "pk_", "mtm_", "hsa_")
INDEX_FILES = re.compile(r"/(index|default)\.(html?|php|aspx?|jsp)$", re.I)


# Defaults; spiders override them from the IR_FORCE_HTTPS / IR_STRIP_WWW settings.
FORCE_HTTPS = True
STRIP_WWW = True
STRIP_TRAILING_SLASH = False


def configure(settings) -> None:
    global FORCE_HTTPS, STRIP_WWW, STRIP_TRAILING_SLASH
    FORCE_HTTPS = settings.getbool("IR_FORCE_HTTPS", True)
    STRIP_WWW = settings.getbool("IR_STRIP_WWW", True)
    STRIP_TRAILING_SLASH = settings.getbool("IR_STRIP_TRAILING_SLASH", False)


def _is_tracking(key: str) -> bool:
    k = key.lower()
    return k in TRACKING_PARAMS or k.startswith(TRACKING_PREFIXES)


def normalize_url(url: str, *, strip_www: bool | None = None, force_https: bool | None = None,
                  strip_trailing_slash: bool | None = None) -> str:
    """Return a canonical form of an absolute http(s) URL."""
    strip_www = STRIP_WWW if strip_www is None else strip_www
    force_https = FORCE_HTTPS if force_https is None else force_https
    if strip_trailing_slash is None:
        strip_trailing_slash = STRIP_TRAILING_SLASH
    url = url.strip()
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        return url
    if force_https:
        scheme = "https"

    host = (parts.hostname or "").lower().rstrip(".")
    if strip_www and host.startswith("www."):
        host = host[4:]
    port = parts.port
    netloc = host
    if port and not ((port == 80) or (port == 443)):
        netloc = f"{host}:{port}"

    # Path: decode then re-encode so %7E and ~ compare equal; resolve dot segments.
    path = unquote(parts.path) or "/"
    path = re.sub(r"/{2,}", "/", path)
    trailing = path.endswith("/")
    path = posixpath.normpath(path)
    if path in (".", "//"):
        path = "/"
    if trailing and path != "/":
        path += "/"
    path = INDEX_FILES.sub("/", path)
    if strip_trailing_slash and len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    path = quote(path, safe="/:@!$&'()*+,;=-._~")

    query_pairs = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _is_tracking(k)
    ]
    query_pairs.sort()
    query = urlencode(query_pairs, doseq=True)

    return urlunsplit((scheme, netloc, path, query, ""))


def page_key(url: str) -> str:
    """Key used to decide "same page" when counting: normalized, trailing slash removed."""
    return normalize_url(url, strip_trailing_slash=True)


def host_of(url: str, *, strip_www: bool | None = None) -> str:
    strip_www = STRIP_WWW if strip_www is None else strip_www
    host = (urlsplit(url).hostname or "").lower()
    if strip_www and host.startswith("www."):
        host = host[4:]
    return host


def in_domain(url: str, domains: list[str], *, include_subdomains: bool) -> bool:
    """True if url's host is one of `domains` (or a subdomain of one, if allowed)."""
    host = host_of(url)
    for d in domains:
        d = d.lower()
        if STRIP_WWW:
            d = d.removeprefix("www.")
        if host == d or (include_subdomains and host.endswith("." + d)):
            return True
    return False
