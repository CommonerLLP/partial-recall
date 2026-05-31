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
    _build_cql,
    _nbn_parse,
    _ol_parse,
    _parse_marc,
    _press_match,
    find_books,
)

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
    assert g.year == "2024"


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
    monkeypatch.setattr(rel, "_nbn", lambda field, limit=25: nbn_r)
    monkeypatch.setattr(rel, "_openlibrary", lambda subj, press, year, rows=25: ol_r)
    monkeypatch.setattr(rel, "_sru", lambda *a, **k: "")
    monkeypatch.setattr(rel, "_parse_marc", lambda xml: loc_r)

    assert find_books(field="south asian studies")["sources"] == ["NBN:south asian studies"]
    assert find_books(press="duke", subject=["Caste"])["sources"] == ["openlibrary"]
    assert find_books(subject=["West Bengal"], year="2024")["sources"] == ["loc"]


def test_find_books_press_filter_and_dedup(monkeypatch) -> None:
    dup = [Release("Same Book", "A", "Duke University Press", "2024", ""),
           Release("Same Book", "A", "Duke University Press", "2024", ""),
           Release("Other", "B", "Routledge", "2024", "")]
    monkeypatch.setattr(rel, "_sru", lambda *a, **k: "")
    monkeypatch.setattr(rel, "_parse_marc", lambda xml: dup)
    res = find_books(subject=["x"], year="2024", press="duke")
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


# ---- live (excluded from CI; catches upstream drift) ----
@pytest.mark.live
def test_loc_live_reachable() -> None:
    recs = _parse_marc(rel._sru('dc.subject="West Bengal" and dc.date=2024', rows=10))
    assert any(r.title for r in recs)
