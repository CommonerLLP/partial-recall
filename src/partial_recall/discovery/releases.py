"""Track new releases from academic presses — an extension of partial-recall.

Source: the Library of Congress catalogue (SRU). LoC catalogues virtually
everything at publication (CIP / copyright deposit), so it covers EVERY press —
including the US university presses (Stanford, Princeton, Chicago…) that deposit
no book DOIs to Crossref. One authoritative pipe.

  registry   presses.json   (press name + publisher match strings; expand freely)
  puller      LoC SRU        (query by subject; parse MARCXML — LCSH, LCC,
                              publisher, LCCN, CIP/prepublication flag)
  query       whats_new()    "anything new in <subject> from <press> since we
                              last checked?" — press is a local filter on the
                              record publisher; "since last checked" is a
                              snapshot diff persisted in the data dir.

No HTML, no web framework. Returns structured records; the CLI prints text.

  python -m partial_recall.discovery.releases --press stanford --subject "South Asia" "Anthropology"
  python -m partial_recall.discovery.releases --subject Caste --press california
  python -m partial_recall.discovery.releases --list-presses
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from partial_recall.paths import user_data_dir

PRESSES_PATH = Path(__file__).with_name("presses.json")
STATE_PATH = user_data_dir() / "discovery_state.json"
UA = {"User-Agent": "partial-recall (+https://github.com/CommonerLLP/partial-recall)"}
SRU = "http://lx2.loc.gov:210/lcdb"
MARC = "{http://www.loc.gov/MARC21/slim}"


@dataclass(frozen=True)
class Release:
    title: str
    authors: str
    publisher: str
    year: str
    lccn: str
    subjects: str = ""    # LCSH headings, " | "-joined
    lcc: str = ""         # LC classification (e.g. P95.82.I4)
    cip: bool = False     # prepublication CIP record (encoding level 8)


# ---------------------------------------------------------------- registry
def load_presses() -> list[dict]:
    return json.loads(PRESSES_PATH.read_text())["presses"]


def find_press(token: str) -> dict | None:
    t = token.strip().lower()
    for p in load_presses():
        if t == p["short"] or t in p["name"].lower():
            return p
    return None


# ---------------------------------------------------------------- state
def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            return {}
    return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


# ---------------------------------------------------------------- LoC puller
def _sru(cql: str, rows: int = 80, start: int = 1) -> str:
    q = urllib.parse.urlencode({
        "version": "1.1", "operation": "searchRetrieve", "query": cql,
        "maximumRecords": rows, "startRecord": start, "recordSchema": "marcxml"})
    try:
        req = urllib.request.Request(f"{SRU}?{q}", headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode("utf-8", "ignore")
    except Exception as exc:  # noqa: BLE001
        print(f"  ! LoC SRU fetch failed: {exc}")
        return ""


def _build_cql(subject_terms: list[str]) -> str:
    clauses = [f'dc.subject="{t}"' for t in subject_terms if t.strip()]
    return " and ".join(clauses) if clauses else 'dc.subject="South Asia"'


def _sf(df, code: str) -> list[str]:
    return [(s.text or "").strip() for s in df.findall(f"{MARC}subfield") if s.get("code") == code]


def _df(rec, tag: str) -> list:
    return [d for d in rec.findall(f"{MARC}datafield") if d.get("tag") == tag]


def _parse_marc(xml: str) -> list[Release]:
    """Parse LoC MARCXML: title (245), authors (100/700), publisher+date (264/260),
    LC class (050), LCSH (650), LCCN (010), and CIP flag (leader/17 == '8')."""
    out: list[Release] = []
    try:
        root = ET.fromstring(xml)
    except Exception:
        return out
    for rec in root.iter(f"{MARC}record"):
        ldr = rec.findtext(f"{MARC}leader") or ""
        cip = len(ldr) > 17 and ldr[17] == "8"
        t = _df(rec, "245")
        title = " ".join(_sf(t[0], "a") + _sf(t[0], "b")).strip(" /:.") if t else ""
        if not title:
            continue
        authors = []
        for tag in ("100", "700"):
            for d in _df(rec, tag):
                authors += _sf(d, "a")
        pubf = _df(rec, "264") or _df(rec, "260")
        pub = (_sf(pubf[0], "b")[0].strip(" ,;") if pubf and _sf(pubf[0], "b") else "—")
        datef = (_sf(pubf[0], "c")[0] if pubf and _sf(pubf[0], "c") else "")
        proj = (_sf(_df(rec, "263")[0], "a")[0] if _df(rec, "263") else "")
        year = ""  # take a real 19xx/20xx year; ignore CIP 263 YYMM codes like "2406"
        for src in (datef, proj):
            for tok in "".join(c if c.isdigit() else " " for c in src).split():
                if len(tok) >= 4 and tok[:2] in ("19", "20"):
                    year = tok[:4]
                    break
            if year:
                break
        c050 = _df(rec, "050")
        lcc = " ".join(_sf(c050[0], "a") + _sf(c050[0], "b")) if c050 else ""
        subs = []
        for d in _df(rec, "650"):
            parts = _sf(d, "a") + _sf(d, "x") + _sf(d, "z") + _sf(d, "y")
            if parts:
                subs.append("—".join(p.strip(" .") for p in parts))
        c010 = _df(rec, "010")
        lccn = _sf(c010[0], "a")[0].strip() if c010 and _sf(c010[0], "a") else ""
        out.append(Release(
            title=title, authors="; ".join(a.strip(" ,.") for a in authors[:4]) or "—",
            publisher=pub or "—", year=year, lccn=lccn,
            subjects=" | ".join(subs[:6]), lcc=lcc, cip=cip))
    return out


# ---------------------------------------------------------------- OpenLibrary backend
def _openlibrary(subject: list[str] | None, press: str | None,
                 year: str | None, rows: int = 25) -> list[Release]:
    """Query OpenLibrary (Internet Archive — open, no key) by publisher × subject
    × year. This is the axis LoC can't do: PRESS and DISCIPLINE/FIELD/STUDIES are
    both real query terms here (publisher:..., subject:Anthropology). Recency lags
    LoC, so use this for 'has <press> published anything on <field/topic>'."""
    q = []
    if press:
        p = find_press(press)
        q.append(f'publisher:"{p["name"] if p else press}"')
    for s in (subject or []):
        q.append(f'subject:"{s}"')
    if year:
        q.append(f"first_publish_year:{year}")
    params = urllib.parse.urlencode({
        "q": " ".join(q) or "*", "sort": "new", "limit": rows,
        "fields": "title,author_name,first_publish_year,publisher,lccn,subject"})
    url = "https://openlibrary.org/search.json?" + params
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=45) as r:
            docs = json.loads(r.read()).get("docs", [])
    except Exception as exc:  # noqa: BLE001
        print(f"  ! OpenLibrary fetch failed: {exc}")
        return []
    return _ol_parse(docs)


def _ol_parse(docs: list[dict]) -> list[Release]:
    """Pure parse of OpenLibrary search docs → Releases (unit-testable)."""
    out = []
    for d in docs:
        out.append(Release(
            title=d.get("title", ""),
            authors="; ".join(d.get("author_name", [])[:4]) or "—",
            publisher="; ".join(d.get("publisher", [])[:1]) or "—",
            year=str(d.get("first_publish_year", "")),
            lccn=(d.get("lccn", [""])[0] if d.get("lccn") else ""),
            subjects=" | ".join(d.get("subject", [])[:6]), lcc="", cip=False))
    return out


# ---------------------------------------------- New Books Network (field channels)
CHANNELS_PATH = Path(__file__).with_name("channels.json")
_NBN_TITLE = re.compile(r'^\s*(.+?),\s*[“"\'](.+?)[”"\']\s*\(([^()]+?),?\s*(\d{4})\)')


def load_channels() -> list[dict]:
    return json.loads(CHANNELS_PATH.read_text())["channels"]


def find_channel(field: str) -> dict | None:
    f = field.strip().lower()
    for c in load_channels():
        if f == c["field"] or f in c.get("aliases", []) or f in c["field"]:
            return c
    return None


def _nbn_parse(xml: str) -> list[Release]:
    """Parse an NBN Megaphone feed: book is encoded in the episode title as
    'Author, "Title" (Publisher, Year)'. Non-book episodes (no match) skipped."""
    out: list[Release] = []
    try:
        root = ET.fromstring(xml)
    except Exception:
        return out
    for it in root.iter("item"):
        m = _NBN_TITLE.match(it.findtext("title") or "")
        if not m:
            continue
        author, title, pub, year = (x.strip() for x in m.groups())
        blurb = re.sub(r"<[^>]+>", "", (it.findtext("description") or "")).strip()
        out.append(Release(title=title, authors=author, publisher=pub, year=year,
                           lccn="", subjects=blurb[:160], lcc="", cip=False))
    return out


def _nbn(field: str, limit: int = 25) -> list[Release]:
    ch = find_channel(field)
    if not ch:
        return []
    try:
        req = urllib.request.Request(ch["feed"], headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            xml = r.read().decode("utf-8", "ignore")
    except Exception as exc:  # noqa: BLE001
        print(f"  ! NBN fetch failed: {exc}")
        return []
    return _nbn_parse(xml)[:limit]


# ---------------------------------------------------------------- router
def _press_match(r: Release, press: str) -> bool:
    p = find_press(press)
    needles = p["crossref_match"] if p else [press]
    return any(n.lower() in r.publisher.lower() for n in needles)


def find_books(
    *, field: str | None = None, press: str | None = None,
    subject: list[str] | None = None, place: str | None = None,
    year: str | None = None, limit: int = 40,
) -> dict:
    """Route a release query to the source that owns its axes, then merge.

      field (discipline/studies)         -> New Books Network channel
      press x subject (no place/year)    -> OpenLibrary (publisher x subject)
      topic + place + year (+ CIP)       -> Library of Congress (LCSH/LCC)

    `press` is applied as a publisher filter across whatever sources ran.
    Results deduped by title. Returns {"sources": [...], "results": [Release]}."""
    results: list[Release] = []
    sources: list[str] = []

    if field:
        results += _nbn(field, limit)
        sources.append(f"NBN:{field}")
    if press and subject and not (place or year):
        results += _openlibrary(subject, press, year, rows=limit)
        sources.append("openlibrary")
    if place or year or (subject and not field and not (press and not (place or year))):
        terms = list(subject or [])
        if place:
            terms.append(place)
        recs = _parse_marc(_sru(_build_cql(terms or ["South Asia"]) +
                                (f' and dc.date={year}' if year else ""), rows=80))
        results += recs
        sources.append("loc")

    if press:
        results = [r for r in results if _press_match(r, press)]

    seen, uniq = set(), []
    for r in results:
        k = r.title.lower()[:80]
        if not r.title or k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    return {"sources": sources, "results": uniq[:limit]}


# ---------------------------------------------------------------- query
def whats_new(
    *, press: str | None = None, subject: list[str] | None = None,
    year: str | None = None, mark_checked: bool = True, limit: int = 60, pull: int = 80,
) -> dict:
    """anything new in <subject> [from <press>] [in <year>] since we last checked?

    One source — the Library of Congress catalogue (covers every press incl.
    Indian/vernacular). Subject + optional exact year are the query; press is a
    local filter on the record publisher (LoC has no publisher index, so keep
    the subject specific — a narrow LCSH returns a small set in one call). "Since
    last checked" = snapshot diff (keyed on LCCN) persisted in the data dir."""
    state = _load_state()
    p = find_press(press) if press else None
    subj = subject or ["South Asia"]

    cql = _build_cql(subj)
    if year:
        cql += f' and dc.date={year}'
    recs = _parse_marc(_sru(cql, rows=pull))
    if p:
        recs = [r for r in recs
                if any(m.lower() in r.publisher.lower() for m in p["crossref_match"])]

    def _idkey(r: Release) -> str:
        return r.lccn or r.title.lower()[:80]

    # dedupe by LCCN (stable) / title
    seen_t, uniq = set(), []
    for r in recs:
        k = _idkey(r)
        if k in seen_t:
            continue
        seen_t.add(k)
        uniq.append(r)

    subj_label = (" · ".join(subj) if subj else "(everything)") + (f" · {year}" if year else "")
    subj_slug = ("+".join(subj).lower() if subj else "all") + (f"+{year}" if year else "")
    snap_key = f"snap::{(p['short'] if p else 'all')}::{subj_slug}"
    prev = set(state.get(snap_key, []))
    first_check = snap_key not in state
    new = [r for r in uniq if _idkey(r) not in prev]
    if mark_checked:
        state[snap_key] = [_idkey(r) for r in uniq]
        _save_state(state)
    return {"press": (p["name"] if p else "all presses"), "subject": subj_label,
            "first_check": first_check, "total_in_catalogue": len(uniq),
            "results": (uniq if first_check else new)[:limit]}


# ---------------------------------------------------------------- CLI
def _print(res: dict) -> None:
    head = f'New from {res["press"]} in "{res["subject"]}"'
    head += " (first check — showing all)" if res["first_check"] else " since last check"
    print(f"\n{head}\n{'=' * min(len(head), 90)}")
    if not res["results"]:
        print("  (nothing new since last check)")
    for r in res["results"]:
        tag = " [CIP/forthcoming]" if r.cip else ""
        print(f"  • {r.title}{tag}")
        print(f"      {r.authors}  ·  {r.publisher}  ·  {r.year}  ·  {r.lccn}")
        if r.subjects:
            print(f"      LCSH: {r.subjects}")
        if r.lcc:
            print(f"      LCC:  {r.lcc}")
    n_shown, n_total = len(res["results"]), res["total_in_catalogue"]
    print(f"\n  {n_shown} shown · {n_total} match for this press+subject.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Track new academic press releases.")
    ap.add_argument("--press", help="filter to a press short name (e.g. chicago)")
    ap.add_argument("--subject", nargs="+", help='LCSH subject term(s), e.g. "West Bengal"')
    ap.add_argument("--year", help="exact publication year, e.g. 2024")
    ap.add_argument("--no-mark", action="store_true", help="do not update the snapshot")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--list-presses", action="store_true")
    a = ap.parse_args()
    if a.list_presses:
        for p in load_presses():
            print(f"  {p['short']:12} {p['name']} ({p['country']})")
        return
    res = whats_new(press=a.press, subject=a.subject, year=a.year, mark_checked=not a.no_mark)
    if a.json:
        payload = {**res, "results": [asdict(r) for r in res["results"]]}
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        _print(res)


if __name__ == "__main__":
    main()
