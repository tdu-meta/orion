.PHONY: help install test test-unit test-integration test-cov lint format type-check clean pre-commit

# Detect if we have poetry or should use python directly
POETRY := $(shell command -v poetry 2> /dev/null)
VENV_PYTHON := .venv-3.12/bin/python3.12
PYTHON := $(shell test -f $(VENV_PYTHON) && echo $(VENV_PYTHON) || echo /opt/homebrew/bin/python3.12)

ifdef POETRY
    RUN = poetry run
    INSTALL_CMD = poetry install
else
    RUN = PYTHONPATH=src $(PYTHON) -m
    INSTALL_CMD = $(PYTHON) -m pip install -q -r requirements.txt -r requirements-dev.txt
endif

help:
	@echo "Orion Development Commands"
	@echo "=========================="
	@echo "install          Install dependencies"
	@echo "test             Run all tests"
	@echo "test-unit        Run unit tests only"
	@echo "test-integration Run integration tests only"
	@echo "test-cov         Run tests with coverage report"
	@echo "lint             Run linting checks (ruff)"
	@echo "format           Format code with black"
	@echo "type-check       Run mypy type checking"
	@echo "clean            Remove cache and build artifacts"
	@echo "pre-commit       Install pre-commit hooks"
	@echo "ci               Run all CI checks locally"
	@echo ""
	@echo "Using: $(if $(POETRY),Poetry,Python directly - $(PYTHON))"

install:
	$(INSTALL_CMD)

test:
	$(RUN) pytest -v

test-unit:
	$(RUN) pytest tests/unit/ -v

test-integration:
	$(RUN) pytest tests/integration/ -v -m integration

test-cov:
	$(RUN) pytest --cov=orion --cov-report=html --cov-report=term-missing

lint:
	$(RUN) ruff check src/ tests/

format:
	$(RUN) black src/ tests/

type-check:
	$(RUN) mypy src/

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -rf htmlcov/ .coverage coverage.xml
	rm -rf dist/ build/ *.egg-info

pre-commit:
	pip install pre-commit
	pre-commit install

ci: test
	@echo "✅ Tests passed! (Format, lint, type-check require all dependencies)"
	@echo "Run 'make install' first to enable full CI checks"
