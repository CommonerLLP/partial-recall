# Contributing

`partial-recall` is open to contributions from scholars, developers, translators, and anyone who wants better tools for working with scholarly corpora.

## Bug reports and feature requests

Open an issue at https://github.com/CommonerLLP/partial-recall/issues. Include:

- What you tried to do
- What happened (and what you expected)
- Your OS, Python version, and how you installed (`pipx`, `pip`, source)
- For indexing or search bugs: which corpus adapter (zotero / folder), how many items in your corpus, which embedding provider you're using

## Pull requests

- One change per PR.
- Tests for any new behaviour.
- Match the existing code style (`ruff check src tests`, `mypy --strict src`).
- Be specific in the PR description: what changed and why.
- No AI attribution lines in commit messages (org-wide convention).

## Translations

The project ships in English in v0.1.0 but the i18n infrastructure (gettext) is in place. Translations welcome for v0.2.0 and beyond. Priority languages: Hindi, Tamil, Bengali, Marathi, Urdu, Swahili, Spanish, Portuguese.

If you want to translate, open an issue first so we can coordinate the string catalogue.

## Adding a corpus adapter

If you want to add a corpus adapter (for an open-source / open-format reference manager, note tool, or archive), please open an issue first to discuss fit. The project's stance is **open-source / open-format only** — we do not adapt for Mendeley, EndNote, Paperpile, DEVONthink, Notion, or other closed sources.

## Code of conduct

This project follows the [Contributor Covenant](https://www.contributor-covenant.org/). Be kind. The project's primary audience is scholars on older / cheaper hardware, in non-English languages, in institutions without robust API budgets. Their concerns are the project's concerns.

## Maintainer

[Commoner LLP](https://commoner.in). License: [AGPL-3.0-or-later](./LICENSE).
