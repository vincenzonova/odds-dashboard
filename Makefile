SHELL := /bin/bash
.DEFAULT_GOAL := help

.PHONY: help run dev lint format type-check test test-cov install install-dev clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install runtime dependencies
	uv sync --no-dev

install-dev: ## Install all dependencies (runtime + dev)
	uv sync

run: ## Start the server locally
	uvicorn main:app --reload --host 0.0.0.0 --port 8000

lint: ## Run Ruff linter
	ruff check .

format: ## Auto-format code with Ruff
	ruff format .
	ruff check --fix .

type-check: ## Run MyPy type checker
	mypy main.py settings.py middleware.py

test: ## Run tests
	pytest test_main.py -v

test-cov: ## Run tests with coverage (fails under 80%)
	pytest test_main.py --cov=. --cov-report=term-missing --cov-fail-under=80

clean: ## Remove caches and build artifacts
	rm -rf __pycache__ .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
