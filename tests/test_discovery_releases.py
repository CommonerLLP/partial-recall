"""Discovery release-pipe tests — pure parsers + routing, offline (CI-safe).

Live-network behaviour (LoC SRU / OpenLibrary / NBN actually reachable, and
upstream format drift) is covered separately by tests marked @pytest.mark.live,
which are excluded from CI.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from partial_recall.discovery import releases as rel
from partial_recall.discovery.releases import (
    Release,
    _book_meta_from_html,
    _build_cql,
    _nbn_parse,
    _ol_parse,
    _parse_marc,
    _parse_sitemap,
    _press_match,
    find_books,
    press_new_from_sitemap,
)

BANERJEE_URL = "https://press.princeton.edu/books/hardcover/9780691268217/computing-in-the-age-of-decolonization"
BANERJEE_HTML = (
    '<meta property="og:title" content="Computing in the Age of Decolonization">'
    '<meta property="og:description" content="How Cold War geopolitics and domestic '
    "capitalism changed the trajectory of India’s computing industry\">"
)
PRINCETON = {"short": "princeton", "name": "Princeton University Press",
             "crossref_match": ["Princeton University Press"],
             "source": {"type": "sitemap", "index": "x", "book_substr": "/books/"}}

FIX = Path(__file__).parent / "fixtures" / "discovery"


# ---- parsers on real/realistic fixtures ----
def test_parse_marc_extracts_lcsh_lcc_lccn_publisher() -> None:
    recs = _parse_marc((FIX / "loc_marc.xml").read_text())
    assert len(recs) == 1
    r = recs[0]
    assert "Government as practice" in r.title
    assert "Cambridge" in r.publisher
    assert r.lcc.startswith("JC574")
    assert r.lccn == "2015016416"
    assert "West Bengal" in r.subjects
    assert r.cip is False


def test_nbn_parse_parses_book_titles_and_skips_non_books() -> None:
    recs = _nbn_parse((FIX / "nbn_feed.xml").read_text())
    assert len(recs) == 2  # the "Democracy Dialogues" discussion episode is skipped
    g = recs[0]
    assert g.title.startswith("Labors of Division")
    assert g.authors == "Navyug Gill"
    assert g.publisher == "Stanford UP"
    assert g.year == "2024"  # book's publication year
    assert g.date == "2025-01-14"  # episode AIR date, from pubDate — the freshness signal


def test_nbn_episode_date_enables_since_filter() -> None:
    recs = _nbn_parse((FIX / "nbn_feed.xml").read_text())
    # episode air dates are 2025-01-14 (Gill) and 2025-01-03 (Roy)
    fresh = [r for r in recs if r.date >= "2025-01-10"]
    assert [r.authors for r in fresh] == ["Navyug Gill"]


def test_ol_parse_fixture() -> None:
    docs = json.loads((FIX / "ol_response.json").read_text())["docs"]
    recs = _ol_parse(docs)
    assert recs[0].title == "Dalit Studies"
    assert recs[0].publisher == "Duke University Press"
    assert recs[0].year == "2016"
    assert "Caste" in recs[0].subjects
    assert recs[0].lccn == "2015045123"


# ---- pure logic ----
def test_build_cql() -> None:
    expect = 'dc.subject="West Bengal" and dc.subject="Caste"'
    assert _build_cql(["West Bengal", "Caste"]) == expect
    assert _build_cql([]) == 'dc.subject="South Asia"'


def test_year_extraction_ignores_cip_yymm_codes() -> None:
    ns = "http://www.loc.gov/MARC21/slim"
    # 263 projected date "2406" (YYMM) and no 264$c → year must NOT become "2406"
    xml = (f'<collection xmlns="{ns}"><record><leader>00000nam</leader>'
           '<datafield tag="245"><subfield code="a">Test</subfield></datafield>'
           '<datafield tag="263"><subfield code="a">2406</subfield></datafield>'
           '</record></collection>')
    assert _parse_marc(xml)[0].year == ""
    xml2 = xml.replace('<datafield tag="263"><subfield code="a">2406</subfield></datafield>',
                       '<datafield tag="264"><subfield code="c">[2024]</subfield></datafield>')
    assert _parse_marc(xml2)[0].year == "2024"


def test_press_match() -> None:
    r = Release("T", "A", "Stanford University Press, 2024", "2024", "")
    assert _press_match(r, "stanford") is True
    assert _press_match(r, "duke") is False


# ---- router: source selection + press filter + dedup (fetchers stubbed) ----
def test_find_books_routes_by_axis(monkeypatch) -> None:
    nbn_r = [Release("NBN bk", "X", "Routledge", "2025", "")]
    ol_r = [Release("OL bk", "Y", "Duke University Press", "2020", "")]
    loc_r = [Release("LoC bk", "Z", "Kaveri Books", "2024", "")]
    monkeypatch.setattr(rel, "_nbn", lambda field, limit=25, since=None: nbn_r)
    monkeypatch.setattr(rel, "_openlibrary", lambda subj, press, year, rows=25: ol_r)
    monkeypatch.setattr(rel, "_sru", lambda *a, **k: "")
    monkeypatch.setattr(rel, "_parse_marc", lambda xml: loc_r)

    assert find_books(field="south asian studies")["sources"] == ["NBN:south asian studies"]
    # california is a loc-backfill press (no sitemap), so press×subject -> openlibrary
    assert find_books(press="california", subject=["Caste"])["sources"] == ["openlibrary"]
    assert find_books(subject=["West Bengal"], year="2024")["sources"] == ["loc"]


def test_find_books_press_filter_and_dedup(monkeypatch) -> None:
    dup = [Release("Same Book", "A", "University of California Press", "2024", ""),
           Release("Same Book", "A", "University of California Press", "2024", ""),
           Release("Other", "B", "Routledge", "2024", "")]
    monkeypatch.setattr(rel, "_sru", lambda *a, **k: "")
    monkeypatch.setattr(rel, "_parse_marc", lambda xml: dup)
    res = find_books(subject=["x"], year="2024", press="california")
    titles = [r.title for r in res["results"]]
    assert titles == ["Same Book"]  # Routledge filtered out, duplicate collapsed


# ---- snapshot diff (since we last checked) ----
def test_whats_new_snapshot_diff(monkeypatch, tmp_path) -> None:
    canned = [Release("Book A", "A", "Cambridge University Press", "2024", "lccn1")]
    monkeypatch.setattr(rel, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(rel, "_sru", lambda *a, **k: "")
    monkeypatch.setattr(rel, "_parse_marc", lambda xml: canned)
    first = rel.whats_new(subject=["West Bengal"], year="2024")
    assert first["first_check"] is True
    assert len(first["results"]) == 1
    second = rel.whats_new(subject=["West Bengal"], year="2024")
    assert second["first_check"] is False
    assert second["results"] == []  # nothing new


# ---- press sitemap front-line (no network) ----
def test_parse_sitemap_and_book_meta() -> None:
    sm = ('<urlset><url><loc>https://x/books/a</loc></url>'
          '<url><loc>https://x/about</loc></url></urlset>')
    assert _parse_sitemap(sm) == ["https://x/books/a", "https://x/about"]
    r = _book_meta_from_html(BANERJEE_HTML, "Princeton University Press")
    assert r.title == "Computing in the Age of Decolonization"
    assert "India" in r.subjects  # topic lives in og:description, not the title


def test_sitemap_first_run_seeds_then_diff_catches_new(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(rel, "SITEMAP_DIR", tmp_path)
    # first run: no snapshot → seed baseline (without Banerjee), nothing "new"
    monkeypatch.setattr(rel, "_sitemap_book_urls", lambda cfg: ["https://x/books/old"])
    first = press_new_from_sitemap(PRINCETON, subject=["India"])
    assert first["seeded"] == 1
    assert first["results"] == []
    # second run: Banerjee now in the sitemap → diff surfaces it, page fetched, India-filtered
    monkeypatch.setattr(rel, "_sitemap_book_urls",
                        lambda cfg: ["https://x/books/old", BANERJEE_URL])
    monkeypatch.setattr(rel, "_http", lambda url: BANERJEE_HTML if url == BANERJEE_URL else "")
    second = press_new_from_sitemap(PRINCETON, subject=["India"])
    assert second["new_total"] == 1
    assert [r.title for r in second["results"]] == ["Computing in the Age of Decolonization"]


def test_sitemap_sub_filter_descends_only_product_subsitemaps(monkeypatch) -> None:
    # WordPress presses (Yale/Cornell/Minnesota/Washington/Columbia) keep books in
    # dedicated `…-products.N.xml.gz` sub-sitemaps; sub_filter must follow only those.
    index = ('<sitemapindex>'
             '<sitemap><loc>https://x/post-sitemap.xml</loc></sitemap>'
             '<sitemap><loc>https://x/sitemaps/sitemap-products.1.xml.gz</loc></sitemap>'
             '</sitemapindex>')
    pages = {
        "https://x/sitemap.xml": index,
        "https://x/post-sitemap.xml":
            '<urlset><url><loc>https://x/blog/hello</loc></url></urlset>',
        "https://x/sitemaps/sitemap-products.1.xml.gz":
            '<urlset><url><loc>https://x/book/9781/a</loc></url>'
            '<url><loc>https://x/book/9782/b</loc></url></urlset>',
    }
    monkeypatch.setattr(rel, "_http", lambda url: pages.get(url, ""))
    cfg = {"index": "https://x/sitemap.xml", "sub_filter": "product", "book_substr": "/book/"}
    urls = rel._sitemap_book_urls(cfg)
    assert urls == ["https://x/book/9781/a", "https://x/book/9782/b"]  # blog sub skipped


def test_clean_title_strips_press_suffix_forms() -> None:
    emdash = "Once Within Borders — Harvard University Press"
    assert rel._clean_title(emdash) == "Once Within Borders"
    assert rel._clean_title("Computing | Princeton University Press") == "Computing"
    assert rel._clean_title("A Plain Book Title") == "A Plain Book Title"  # untouched


def test_book_marker_keeps_books_drops_journal_issues(monkeypatch, tmp_path) -> None:
    # Duke flat slugs mix books with journal issues; only the page carrying the
    # "ISBN:" marker is a book.
    monkeypatch.setattr(rel, "SITEMAP_DIR", tmp_path)
    duke = {"short": "duke", "name": "Duke University Press",
            "crossref_match": ["Duke University Press"],
            "source": {"type": "sitemap", "index": "x", "book_substr": "", "book_marker": "isbn:"}}
    book_url, issue_url = "https://dukeupress.edu/bomb-children", "https://dukeupress.edu/journal-64-4"
    (tmp_path / "sitemap_duke.json").write_text(json.dumps(["https://dukeupress.edu/old"]))
    monkeypatch.setattr(rel, "_sitemap_book_urls",
                        lambda cfg: ["https://dukeupress.edu/old", book_url, issue_url])
    pages = {
        book_url: '<meta property="og:title" content="Bomb Children">'
                  '<meta property="og:description" content="Life in former Laos battlefields">'
                  '<div>ISBN: 9781478005261</div>',
        issue_url: '<meta property="og:title" content="Comparative Literature 64:4">'
                   '<meta property="og:description" content="A journal issue">',  # no ISBN: label
    }
    monkeypatch.setattr(rel, "_http", lambda url: pages.get(url, ""))
    res = rel.press_new_from_sitemap(duke, subject=None)
    assert [r.title for r in res["results"]] == ["Bomb Children"]  # journal issue dropped


def test_sitemap_subject_filter_excludes_offtopic(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(rel, "SITEMAP_DIR", tmp_path)
    (tmp_path / "sitemap_princeton.json").write_text(json.dumps(["https://x/books/old"]))
    monkeypatch.setattr(rel, "_sitemap_book_urls",
                        lambda cfg: ["https://x/books/old", BANERJEE_URL, "https://x/books/shakespeare"])
    pages = {BANERJEE_URL: BANERJEE_HTML,
             "https://x/books/shakespeare":
                 '<meta property="og:title" content="Shakespeare at Thirty">'
                 '<meta property="og:description" content="On the Bard early career">'}
    monkeypatch.setattr(rel, "_http", lambda url: pages.get(url, ""))
    res = press_new_from_sitemap(PRINCETON, subject=["India"])
    assert [r.title for r in res["results"]] == ["Computing in the Age of Decolonization"]


# ---- live (excluded from CI; catches upstream drift) ----
@pytest.mark.live
def test_loc_live_reachable() -> None:
    recs = _parse_marc(rel._sru('dc.subject="West Bengal" and dc.date=2024', rows=10))
    assert any(r.title for r in recs)
