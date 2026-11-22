"""Duplicate detection.

* Exact duplicates: SHA-1 of the normalized main text.
* Near duplicates: MinHash over word 5-shingles + LSH (datasketch), estimated
  Jaccard >= threshold. Also a 64-bit SimHash is computed for every page so you
  can compare the two methods in the report (Hamming distance <= 3 ~ near-dup).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

from datasketch import MinHash, MinHashLSH

TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text or "").lower()
    return " ".join(TOKEN_RE.findall(text))


def content_hash(text: str) -> str:
    return hashlib.sha1(normalize_text(text).encode("utf-8")).hexdigest()


def shingles(text: str, k: int = 5) -> set[str]:
    words = normalize_text(text).split()
    if len(words) < k:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i:i + k]) for i in range(len(words) - k + 1)}


def simhash(text: str, bits: int = 64) -> int:
    """Charikar SimHash over word 3-shingles."""
    v = [0] * bits
    for sh in shingles(text, 3):
        h = int.from_bytes(hashlib.md5(sh.encode("utf-8")).digest()[:8], "big")
        for i in range(bits):
            v[i] += 1 if (h >> i) & 1 else -1
    return sum(1 << i for i in range(bits) if v[i] > 0)


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


class DuplicateDetector:
    def __init__(self, threshold: float = 0.8, num_perm: int = 128, shingle_size: int = 5):
        self.num_perm = num_perm
        self.k = shingle_size
        self.lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
        self.exact: dict[str, str] = {}      # content hash -> first URL
        self.minhashes: dict[str, MinHash] = {}

    def minhash(self, text: str) -> MinHash:
        m = MinHash(num_perm=self.num_perm)
        for sh in shingles(text, self.k):
            m.update(sh.encode("utf-8"))
        return m

    def check(self, url: str, text: str) -> dict:
        """Register a page and report whether it duplicates an earlier one."""
        h = content_hash(text)
        result = {
            "content_hash": h,
            "simhash": format(simhash(text), "016x"),
            "exact_duplicate_of": None,
            "near_duplicate_of": None,
            "near_duplicate_jaccard": None,
        }
        if not normalize_text(text):
            return result
        if h in self.exact:
            result["exact_duplicate_of"] = self.exact[h]
            return result
        self.exact[h] = url

        m = self.minhash(text)
        candidates = self.lsh.query(m)
        if candidates:
            best = max(candidates, key=lambda c: m.jaccard(self.minhashes[c]))
            result["near_duplicate_of"] = best
            result["near_duplicate_jaccard"] = round(m.jaccard(self.minhashes[best]), 3)
        if url not in self.minhashes:
            self.lsh.insert(url, m)
            self.minhashes[url] = m
        return result
