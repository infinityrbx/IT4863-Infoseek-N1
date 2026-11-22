"""Per-page extraction: links + anchor text, meta tags, title/h1, main text, publish time."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from .urlnorm import host_of, normalize_url

try:
    import trafilatura
except ImportError:  # the T2 spider does not need it
    trafilatura = None

WS = re.compile(r"\s+")


def clean(s: str | None) -> str:
    return WS.sub(" ", s or "").strip()


# --------------------------------------------------------------------------- links
def extract_links(response, *, base_host: str | None = None) -> list[dict]:
    """All <a href> on the page: normalized absolute URL, anchor text, internal?, nofollow?"""
    base_host = base_host or host_of(response.url)
    base = response.css("base::attr(href)").get() or response.url
    out, seen = [], set()
    for a in response.css("a[href]"):
        href = (a.attrib.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            continue
        try:
            url = normalize_url(urljoin(base, href))
        except ValueError:
            continue
        if not url.startswith("http"):
            continue
        anchor = clean(" ".join(a.css("::text").getall()))
        if not anchor:  # image links: fall back to alt / title
            anchor = clean(a.css("img::attr(alt)").get() or a.attrib.get("title") or a.attrib.get("aria-label"))
        key = (url, anchor)
        if key in seen:
            continue
        seen.add(key)
        rel = (a.attrib.get("rel") or "").lower()
        out.append({
            "url": url,
            "anchor": anchor,
            "internal": host_of(url) == base_host,
            "nofollow": "nofollow" in rel,
        })
    return out


# --------------------------------------------------------------------------- meta
def extract_meta(response) -> dict:
    def meta(*names):
        for n in names:
            v = response.xpath(
                f'//meta[translate(@name,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz")="{n}"'
                f' or @property="{n}" or @itemprop="{n}"]/@content'
            ).get()
            if v:
                return clean(v)
        return None

    og = {}
    for m in response.xpath('//meta[starts-with(@property,"og:") or starts-with(@name,"og:")]'):
        key = m.attrib.get("property") or m.attrib.get("name")
        if key and m.attrib.get("content"):
            og.setdefault(key, clean(m.attrib["content"]))

    canonical = response.css('link[rel="canonical"]::attr(href)').get()
    keywords = meta("keywords")
    return {
        "description": meta("description"),
        "keywords": [k.strip() for k in keywords.split(",") if k.strip()] if keywords else [],
        "author": meta("author", "article:author"),
        "robots": meta("robots"),
        "lang": response.xpath("/html/@lang").get(),
        "canonical": normalize_url(urljoin(response.url, canonical)) if canonical else None,
        "og": og,
    }


def extract_headings(response) -> dict:
    return {
        "title": clean(response.css("title::text").get()),
        "h1": [t for t in (clean(" ".join(h.css("::text").getall())) for h in response.css("h1")) if t],
    }


# --------------------------------------------------------------------------- main content
def extract_main_text(html: str, url: str) -> str:
    """Boilerplate-free main content via trafilatura (falls back to all visible text)."""
    if trafilatura is not None:
        text = trafilatura.extract(
            html, url=url, include_comments=False, include_tables=True,
            favor_precision=True, deduplicate=True,
        )
        if text:
            return text.strip()
    return ""


def fallback_text(response) -> str:
    parts = response.xpath(
        "//body//text()[not(ancestor::script) and not(ancestor::style) and not(ancestor::nav)"
        " and not(ancestor::header) and not(ancestor::footer)]"
    ).getall()
    return clean(" ".join(parts))


# --------------------------------------------------------------------------- publish time
DATE_META = [
    "article:published_time", "og:published_time", "datepublished", "date", "pubdate",
    "publishdate", "publish-date", "dc.date", "dc.date.issued", "dcterms.created",
    "sailthru.date", "parsely-pub-date", "article:modified_time",
]
URL_DATE_PATTERNS = [
    re.compile(r"/(20\d{2}|19\d{2})/(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])(/|$)"),
    re.compile(r"/(20\d{2}|19\d{2})/(0?[1-9]|1[0-2])(/|$)"),
    re.compile(r"[-_/](20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{0,6}(?=\D|$)"),
]
# Vietnamese pages often print dates as dd/mm/yyyy (optionally with hh:mm).
TEXT_DATE_RE = re.compile(r"\b(0?[1-9]|[12]\d|3[01])[/\-.](0?[1-9]|1[0-2])[/\-.](20\d{2})"
                          r"(?:\D{1,5}(\d{1,2}):(\d{2}))?")


def _parse_iso(s: str) -> str | None:
    s = s.strip()
    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00")) if fmt is None else datetime.strptime(s, fmt)
            return dt.isoformat()
        except ValueError:
            continue
    m = TEXT_DATE_RE.search(s)
    if m:
        d, mo, y, hh, mm = m.groups()
        try:
            return datetime(int(y), int(mo), int(d), int(hh or 0), int(mm or 0)).isoformat()
        except ValueError:
            return None
    return None


def _jsonld_dates(response):
    for raw in response.xpath('//script[@type="application/ld+json"]/text()').getall():
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                for k in ("datePublished", "dateCreated", "uploadDate"):
                    if isinstance(node.get(k), str):
                        yield node[k]
                stack.extend(v for v in node.values() if isinstance(v, (list, dict)))


def extract_publish_time(response, html: str | None = None) -> dict:
    """Try, in order: meta tags, JSON-LD, <time>, trafilatura, URL, dd/mm/yyyy in text.

    Returns {"value": ISO string or None, "source": where it came from}.
    """
    for name in DATE_META:
        v = response.xpath(
            f'//meta[@property="{name}" or translate(@name,"ABCDEFGHIJKLMNOPQRSTUVWXYZ",'
            f'"abcdefghijklmnopqrstuvwxyz")="{name}" or translate(@itemprop,"ABCDEFGHIJKLMNOPQRSTUVWXYZ",'
            f'"abcdefghijklmnopqrstuvwxyz")="{name}"]/@content'
        ).get()
        if v and (iso := _parse_iso(v)):
            return {"value": iso, "source": f"meta:{name}"}

    for v in _jsonld_dates(response):
        if iso := _parse_iso(v):
            return {"value": iso, "source": "json-ld"}

    for t in response.css("time"):
        v = t.attrib.get("datetime") or clean(" ".join(t.css("::text").getall()))
        if v and (iso := _parse_iso(v)):
            return {"value": iso, "source": "time-tag"}

    if trafilatura is not None and html:
        try:
            md = trafilatura.extract_metadata(html, default_url=response.url, extensive=False)
            if md is not None and md.date:
                return {"value": md.date, "source": "trafilatura"}
        except Exception:  # trafilatura heuristics can fail on odd HTML
            pass

    for rx in URL_DATE_PATTERNS:
        m = rx.search(response.url)
        if m:
            g = [x for x in m.groups() if x and x.isdigit()]
            y, mo, d = int(g[0]), int(g[1]), int(g[2]) if len(g) > 2 else 1
            try:
                return {"value": datetime(y, mo, d).date().isoformat(), "source": "url"}
            except ValueError:
                pass

    # Last resort: first dd/mm/yyyy near the top of the visible text.
    head = " ".join(response.xpath("//body//text()[not(ancestor::script)]").getall()[:300])
    m = TEXT_DATE_RE.search(head)
    if m and (iso := _parse_iso(m.group(0))):
        return {"value": iso, "source": "text"}
    return {"value": None, "source": None}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
