# Contributing

`partial-recall` is open to contributions from scholars, developers, translators, and anyone who wants better tools for working with scholarly corpora.

## Bug reports and feature requests

Open an issue at https://github.com/CommonerLLP/partial-recall/issues. Include:

- What you tried to do
- What happened (and what you expected)
- Your OS, Python version, and how you installed (`pipx`, `pip`, source)
- `partial-recall --version` and `partial-recall doctor` output
- For indexing or search bugs: which corpus adapter (zotero / folder / calibre / markdown_notes / jabref), how many items in your corpus, which embedding provider you're using

## Pull requests

- One change per PR.
- Tests for any new behaviour.
- Match the existing code style (`ruff check src tests`, `mypy --strict src`).
- Be specific in the PR description: what changed and why.

## Translations

The project ships in English only. i18n infrastructure is not yet in place — this is planned for v0.6.0. When it is ready, priority languages will be Hindi, Tamil, Bengali, Marathi, Urdu, Swahili, Spanish, and Portuguese.

If you want to contribute translations, open an issue first so we can coordinate once the infrastructure is ready.

## Adding a corpus adapter

If you want to add a corpus adapter (for an open-source / open-format reference manager, note tool, or archive), please open an issue first to discuss fit. The project's stance is **open-source / open-format only** — we do not adapt for Mendeley, EndNote, Paperpile, DEVONthink, Notion, or other closed sources.

Current adapters: Zotero, Folder, Calibre, Markdown notes, JabRef.

## Code of conduct

This project follows the [Contributor Covenant](https://www.contributor-covenant.org/). Be kind. The project's primary audience is scholars on older / cheaper hardware, in non-English languages, in institutions without robust API budgets. Their concerns are the project's concerns.

## Maintainer

[Commoner LLP](https://commoner.in). License: [AGPL-3.0-or-later](./LICENSE).
