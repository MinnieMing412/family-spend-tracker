PYTHON := .venv/bin/python
PYTEST := .venv/bin/pytest
RUFF := .venv/bin/ruff
MYPY := .venv/bin/mypy

.PHONY: check test lint typecheck

check: test lint typecheck

test:
	$(PYTEST) -q

lint:
	$(RUFF) check .

typecheck:
	$(MYPY) src tests
	$(PYTHON) -m compileall -q src tests
