.PHONY: setup data load run eval propose demo test lint schema reset full

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

eval:
	uv run python -m closedesk.eval

propose:
	uv run python -m closedesk.agent

demo:
	uv run streamlit run closedesk/app/ui.py

test:
	uv run pytest

lint:
	uv run ruff check closedesk tests

reset:
	rm -rf data
	./scripts/setup_exasol.sh

full: data schema load run propose eval
	@echo "Full pipeline complete. Run 'make demo' to open the dashboard."
