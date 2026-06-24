.PHONY: help sync-agents deps deps-local deps-gemini deps-all hooks test lint typecheck clean

help:
	@echo "partial-recall — common dev tasks"
	@echo ""
	@echo "  make sync-agents   Sync CLAUDE.md / AGENTS.md / GEMINI.md from ../_org/"
	@echo "  make deps          Install dev dependencies"
	@echo "  make deps-local    Install dev + local-embedding deps"
	@echo "  make deps-gemini   Install dev + gemini deps"
	@echo "  make deps-all      Install everything"
	@echo "  make hooks         Install local pre-commit hook"
	@echo "  make test          Run pytest"
	@echo "  make lint          Run ruff check"
	@echo "  make typecheck     Run mypy strict"
	@echo "  make clean         Remove caches and build artefacts"

sync-agents:
	python ../_org/sync_all.py --repo .

deps:
	pip install -e ".[dev]"

deps-local:
	pip install -e ".[dev,local]"

deps-gemini:
	pip install -e ".[dev,gemini]"

deps-all:
	pip install -e ".[dev,all]"

hooks:
	install -m 0755 scripts/pre-commit .git/hooks/pre-commit

test:
	pytest

lint:
	ruff check src tests

typecheck:
	mypy src

clean:
	rm -rf build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
