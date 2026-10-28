.PHONY: setup data load run test demo reset lint schema

PYTHON ?= python3
export PATH := $(HOME)/.local/bin:$(PATH)

setup:
	@command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh
	uv python pin 3.13 || true
	uv sync --all-extras
	@echo "Copy .env.example to .env if you have not already."

schema:
	./scripts/setup_exasol.sh

data:
	uv run python -m closedesk.generator

load:
	uv run python -m closedesk.loader

run:
	uv run python -m closedesk.engine

test:
	uv run pytest

lint:
	uv run ruff check closedesk tests

demo:
	uv run streamlit run closedesk/app/ui.py

reset:
	rm -rf data
	./scripts/setup_exasol.sh
