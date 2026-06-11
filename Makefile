# One-command pipeline. Requires uv (https://docs.astral.sh/uv/).
PY := .venv/bin/python
ifeq ($(OS),Windows_NT)
PY := .venv/Scripts/python
endif

.PHONY: setup pipeline ingest chunk embed evals evals-full

setup:
	uv venv -p 3.12 .venv
	uv pip install -p .venv -r pipeline/requirements.txt pytest

pipeline: ingest chunk embed

ingest:
	$(PY) pipeline/ingest.py

chunk:
	$(PY) pipeline/chunk.py

embed:
	$(PY) pipeline/embed.py

evals:
	$(PY) evals/run_evals.py

evals-full:
	$(PY) evals/run_evals.py --mode full
