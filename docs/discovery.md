# Discovery — tracking new academic releases

Find newly published / catalogued scholarly books, and decide what to read, by
querying public bibliographic sources — **no API key, no embeddings**, just
catalog metadata. This complements the search side of partial-recall (which
searches *what you've already read*); discovery is about *what's newly out there*.

## How a question maps to a source

No single catalog answers everything, so a query is routed to the source that
owns its axis:

| You ask by… | Example | Source |
|---|---|---|
| **press** (recent titles) | "what's *Princeton* just put out on India?" | **the press's own sitemap** (front-line) |
| **field / discipline / "studies"** | "what's new in *South Asian Studies*?" | **New Books Network** channels |
| **press × subject** | "has *Duke* published on *caste*?" | **OpenLibrary** (`publisher` × `subject`) |
| **topic + place + year (+ forthcoming)** | "new on *West Bengal* in *2024*, incl. CIP" | **Library of Congress** (LCSH/LCC) |

`press` also works as a filter on results from any source.

### What each source is good (and not good) at

- **Press sitemaps (the front-line).** A press's own XML sitemap lists every
  book page; we snapshot it and a **new book-URL = a new book** — so a title
  surfaces here the moment the press publishes it, *before* any third-party
  catalogue (LoC, OpenLibrary) gets around to it. (Verified: a 2026 Princeton
  title was live in the sitemap while absent from both LoC and OpenLibrary.)
  Per new page we read `og:title` and `og:description` — a plain GET, no
  headless browser, no third-party reader. First run seeds the baseline; every
  run after reports only what's new since. Tracked this way:
  **Princeton, Chicago, Columbia, Cornell, Yale, Harvard, Minnesota, Stanford,
  Washington, Duke**. Two wrinkles handled: WordPress presses keep books in
  dedicated `product`/`books` sub-sitemaps (`sub_filter` descends only those);
  Duke uses flat slugs that mix books with journal issues, so a `book_marker`
  (`"isbn:"`, present on book pages, absent on journal issues) keeps only books.
  Presses that expose no usable sitemap (MIT, California, Oxford, Cambridge,
  Routledge) fall back to LoC + OpenLibrary; each is labelled with the reason in
  `presses.json`. (Crossref was tested as a by-publisher source and rejected:
  its publisher filter is ignored and book dates are unreliable. Sites that block
  a self-identifying crawler User-Agent outright, e.g. cambridge.org, are left on
  the fallback rather than evaded.)
- **Library of Congress (SRU + MARC/CIP).** Authoritative; covers *every* press
  including Indian and vernacular houses; carries full **LCSH** subjects, **LCC**
  class, **LCCN**, and a **CIP / forthcoming** flag (books appear before
  publication). Queryable by **topic + place + year** — *not* by publisher or
  discipline, and it won't paginate deeply, so keep subjects **specific**.
- **OpenLibrary (Internet Archive).** The one source you can query by
  **publisher × subject** (and discipline-as-subject). Books appear quickly;
  their *subject tags* lag, so for the very newest titles query by publisher and
  read the topic off the record rather than subject-filtering.
- **New Books Network.** ~150 author-interview **channels = fields**; this is the
  only "discipline / studies" axis. It's a *second layer* (post-publication
  interviews, curated by hosts, Anglophone-leaning), so it shows *notable* recent
  books in a field, not everything a press printed.

## CLI

```bash
# A press's newest titles, front-line via its sitemap (seeds on first run,
# then reports only what's new since the last check)
python -m partial_recall.discovery.releases --press princeton --subject "India"
# Library of Congress: topic + place + year, with "since we last checked"
python -m partial_recall.discovery.releases --subject "West Bengal" --year 2024
python -m partial_recall.discovery.releases --list-presses
```

The LoC pipe records a per-query snapshot, so a second run reports only what's
**new since the last check**. Output is plain text (use `--json` for tooling).

## MCP tool

The `whats_new` MCP tool is the router — ask it in natural language from any
MCP client:

- *"What's Princeton just put out on India?"* → `{ "press": "princeton", "subject": ["India"] }`
- *"What's new in South Asian Studies?"* → `{ "field": "South Asian Studies" }`
- *"Has Duke published anything on caste?"* → `{ "press": "duke", "subject": ["Caste"] }`
- *"New on West Bengal in 2024?"* → `{ "subject": ["West Bengal"], "year": "2024" }`

Each result carries title, authors, publisher, year, and — from LoC — LCSH /
LCC / LCCN and the CIP flag. Sitemap front-line results carry the title and the
press's own blurb (`og:description`) as the topic.

## Registries — expand freely

Three small JSON files under `src/partial_recall/discovery/`:

- **`presses.json`** — presses to recognise (name + publisher match strings).
- **`channels.json`** — NBN field channels (`field` → Megaphone feed URL). Add a
  field by finding its channel's feed.
- **`interests.json`** — your subject terms, used to gauge "related to my work."

Add an entry to any of them; nothing else changes.

## Notes

- Everything is **catalog metadata** — there is no full text to embed, so the
  discovery path uses no embedding model and no external AI API.
- Live sources change and throttle; the parsers are unit-tested against committed
  fixtures (CI), and `@pytest.mark.live` tests (run manually) catch upstream
  format drift.
