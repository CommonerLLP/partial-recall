# vcrpy cassettes for partial-recall

This directory holds **recorded HTTP fixtures** for tests that would
otherwise hit a real external API (today: only Gemini). The cassettes
are YAML files committed alongside the test that produced them; CI
replays from them so it never needs an API key and never calls out.

## Recording protocol

You only need to record a cassette if you're:

1. Adding a brand-new test that talks to an external API.
2. Updating an existing cassette because the API contract changed.

To record:

```zsh
export PARTIAL_RECALL_GEMINI_API_KEY='your-key-here'
pytest tests/test_gemini_provider_recorded.py \
    --run-live --record-mode=once -v
```

`--run-live` un-skips the live-marked tests. `--record-mode=once` tells
vcrpy to record if no cassette exists, fail otherwise. After the run
succeeds, **inspect the cassette** before committing:

* the `key` query parameter should appear as `REDACTED`
* `Authorization` and `x-goog-api-key` headers should appear as
  `REDACTED`
* no other field should contain your real key

The vcrpy filters in `tests/conftest.py::vcr_config` do this scrubbing
automatically — but always eyeball the YAML once before committing.
Cassettes are public artefacts; pretend they're going on the front
page of the org website.

## Replay (CI + ordinary local runs)

The default `record_mode = "none"` means vcrpy will **only replay**,
never record. Any test that would need a new cassette fails. This is
deliberate — it prevents CI from silently recording its way around a
missing fixture.

```zsh
pytest tests/test_gemini_provider_recorded.py -v
```

Tests that are marked `@pytest.mark.live` are skipped by default
without `--run-live`. CI does not pass `--run-live`. That's the
firewall: live calls only happen when a human explicitly opts in.

## What goes IN a cassette

The HTTP request/response pair. Headers (post-scrub), query params
(post-scrub), method, URL, body, status, response body, response
headers.

## What does NOT go in a cassette

* API keys (scrubbed by `filter_query_parameters` + `filter_headers`)
* Anything that identifies the recorder personally (User-Agent strings
  with hostnames should be checked; httpx's default is usually fine)
* Real user content — record against synthetic / public-domain text,
  not your private corpus

## File layout

One cassette per test, named after the test function:

```
tests/fixtures/cassettes/
├── README.md                                      ← this file
├── test_gemini_embed_single_document.yaml         ← created when you record
├── test_gemini_embed_batch.yaml
├── test_gemini_401_on_bad_key.yaml
└── ...
```

Tests place themselves into a cassette via `@pytest.mark.vcr` —
pytest-recording auto-names the file after the test function.
