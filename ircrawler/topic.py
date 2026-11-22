"""Configurable on-topic filter for the focused crawler.

A page's score is a weighted count of keyword hits in its fields:
    score = sum over fields f of weight[f] * (number of keyword hits in f)
Keywords may carry their own weight ("học máy: 2"). Matching is case-insensitive
and, by default, also ignores Vietnamese diacritics ("hoc may" matches "học máy").

The same scorer is used to rank links: a link whose anchor text or URL contains
a keyword is crawled earlier (Scrapy request priority) - this is "best-first"
focused crawling.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml


def strip_diacritics(s: str) -> str:
    s = s.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def norm(s: str, fold: bool) -> str:
    s = unicodedata.normalize("NFC", s or "").lower()
    return strip_diacritics(s) if fold else s


DEFAULT_FIELD_WEIGHTS = {"title": 3.0, "h1": 3.0, "description": 2.0, "keywords": 2.0,
                         "url": 1.0, "text": 1.0}


@dataclass
class TopicConfig:
    name: str
    seeds: list[str]
    allowed_domains: list[str]
    include_subdomains: bool = True
    keywords: dict[str, float] = field(default_factory=dict)
    negative_keywords: dict[str, float] = field(default_factory=dict)
    field_weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_FIELD_WEIGHTS))
    min_score: float = 3.0
    ignore_diacritics: bool = True
    max_text_hits_per_keyword: int = 5
    # crawl behaviour
    max_depth: int = 4
    off_topic_tunnel: int = 1        # follow links through N consecutive off-topic pages
    save_off_topic: bool = False
    drop_duplicates: bool = False
    near_dup_threshold: float = 0.8
    min_text_chars: int = 200

    @classmethod
    def load(cls, path: str | Path) -> "TopicConfig":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

        def kw(v):
            if v is None:
                return {}
            if isinstance(v, dict):
                return {str(k): float(w) for k, w in v.items()}
            out = {}
            for item in v:
                if isinstance(item, dict):
                    out.update({str(k): float(w) for k, w in item.items()})
                else:
                    out[str(item)] = 1.0
            return out

        data["keywords"] = kw(data.get("keywords"))
        data["negative_keywords"] = kw(data.get("negative_keywords"))
        fw = dict(DEFAULT_FIELD_WEIGHTS)
        fw.update(data.get("field_weights") or {})
        data["field_weights"] = fw
        known = set(cls.__dataclass_fields__)
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"Unknown keys in {path}: {sorted(unknown)}")
        return cls(**data)


class TopicScorer:
    def __init__(self, cfg: TopicConfig):
        self.cfg = cfg
        fold = cfg.ignore_diacritics
        def rx(k):
            return re.compile(r"(?<!\w)" + re.escape(norm(k, fold)) + r"(?!\w)")
        self._pos = [(k, rx(k), w) for k, w in cfg.keywords.items()]
        self._neg = [(k, rx(k), w) for k, w in cfg.negative_keywords.items()]

    def _hits(self, text: str, cap: int | None = None) -> tuple[float, list[str]]:
        t = norm(text, self.cfg.ignore_diacritics)
        score, matched = 0.0, []
        for k, rx, w in self._pos:
            n = len(rx.findall(t))
            if cap:
                n = min(n, cap)
            if n:
                score += w * n
                matched.append(k)
        for _, rx, w in self._neg:
            n = len(rx.findall(t))
            if cap:
                n = min(n, cap)
            score -= w * n
        return score, matched

    def score_page(self, fields: dict[str, str]) -> dict:
        total, matched = 0.0, set()
        per_field = {}
        for name, text in fields.items():
            if not text:
                continue
            cap = self.cfg.max_text_hits_per_keyword if name == "text" else None
            s, m = self._hits(text, cap)
            s *= self.cfg.field_weights.get(name, 1.0)
            if s:
                per_field[name] = round(s, 2)
            total += s
            matched.update(m)
        return {"score": round(total, 2), "on_topic": total >= self.cfg.min_score,
                "matched_keywords": sorted(matched), "per_field": per_field}

    def score_link(self, anchor: str, url: str) -> float:
        s1, _ = self._hits(anchor or "")
        s2, _ = self._hits(re.sub(r"[-_/.]+", " ", url))
        return s1 * 2 + s2
