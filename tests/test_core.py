"""Run with:  python -m pytest tests  (from the crawler/ folder)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ircrawler.dedup import DuplicateDetector, hamming, simhash  # noqa: E402
from ircrawler.filters import skip_reason_for_url  # noqa: E402
from ircrawler.topic import TopicConfig, TopicScorer  # noqa: E402
from ircrawler.urlnorm import in_domain, normalize_url, page_key  # noqa: E402


def test_normalize_variants_collapse():
    variants = [
        "http://hust.edu.vn/tin-tuc/abc/",
        "https://www.hust.edu.vn/tin-tuc/abc",
        "https://HUST.edu.vn:443/tin-tuc//abc#top",
        "https://hust.edu.vn/tin-tuc/abc?utm_source=fb&fbclid=xyz",
        "https://hust.edu.vn/tin-tuc/x/../abc/index.html",
    ]
    assert {page_key(v) for v in variants} == {"https://hust.edu.vn/tin-tuc/abc"}
    # request URLs keep the trailing slash (avoids a 301 round-trip per page)
    assert normalize_url("http://www.hust.edu.vn/a/b/") == "https://hust.edu.vn/a/b/"


def test_normalize_keeps_meaningful_query_sorted():
    assert normalize_url("https://a.vn/news?b=2&a=1") == "https://a.vn/news?a=1&b=2"
    assert normalize_url("https://a.vn/") == "https://a.vn/"


def test_domain():
    assert in_domain("https://soict.hust.edu.vn/x", ["hust.edu.vn"], include_subdomains=True)
    assert not in_domain("https://soict.hust.edu.vn/x", ["hust.edu.vn"], include_subdomains=False)
    assert not in_domain("https://nothust.edu.vn/x", ["hust.edu.vn"], include_subdomains=True)


def test_skip_rules():
    s = skip_reason_for_url
    assert s("https://hust.edu.vn/files/a.pdf") == "non_html_ext"
    assert s("https://hust.edu.vn/dang-nhap") == "login"
    assert s("https://hust.edu.vn/wp-login.php") == "login"
    assert s("https://hust.edu.vn/tim-kiem?q=abc") == "search"
    assert s("https://hust.edu.vn/?s=abc") == "search"
    assert s("https://hust.edu.vn/tin-tuc/page/3") == "pagination"
    assert s("https://hust.edu.vn/tin-tuc?page=3") == "pagination"
    assert s("https://hust.edu.vn/vi/news/hoat-dong-chung/page-2") == "pagination"   # NukeViet
    assert s("https://hust.edu.vn/?p=123") is None          # WordPress post id
    assert s("https://hust.edu.vn/tin-tuc/bai-viet-1") is None


def test_dedup():
    base = " ".join(f"từ{i}" for i in range(300))
    d = DuplicateDetector(threshold=0.8)
    assert d.check("u1", base)["exact_duplicate_of"] is None
    assert d.check("u2", base.upper())["exact_duplicate_of"] == "u1"
    near = base + " thêm vài từ cuối trang"
    assert d.check("u3", near)["near_duplicate_of"] == "u1"
    other = " ".join(f"khác{i}" for i in range(300))
    r = d.check("u4", other)
    assert r["exact_duplicate_of"] is None and r["near_duplicate_of"] is None
    assert hamming(simhash(base), simhash(near)) < hamming(simhash(base), simhash(other))


def test_topic_scoring(tmp_path):
    p = tmp_path / "t.yaml"
    p.write_text("name: t\nseeds: [https://a.vn/]\nallowed_domains: [a.vn]\n"
                 "keywords: {tuyển sinh: 3, điểm chuẩn: 2}\nnegative_keywords: [tuyển dụng]\n"
                 "min_score: 6\n", encoding="utf-8")
    sc = TopicScorer(TopicConfig.load(p))
    on = sc.score_page({"title": "Thông tin TUYEN SINH 2026", "text": "điểm chuẩn các ngành"})
    assert on["on_topic"] and set(on["matched_keywords"]) == {"tuyển sinh", "điểm chuẩn"}
    off = sc.score_page({"title": "Thông báo tuyển dụng", "text": "giảng viên"})
    assert not off["on_topic"]
    assert sc.score_link("Điểm chuẩn 2026", "https://a.vn/diem-chuan") > sc.score_link("Liên hệ", "https://a.vn/lien-he")
