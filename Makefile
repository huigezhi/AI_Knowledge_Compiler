# AI Knowledge Compiler — developer entry points.
# Run `make help` for the full list.

PYTHON ?= python
NPM    ?= npm
BACKEND_DIR   := apps/backend
EXTENSION_DIR := apps/extension

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show available targets
	@echo "AKC developer targets"
	@echo "  make bootstrap        Install backend + extension dependencies"
	@echo "  make backend-install  Create venv and install backend deps"
	@echo "  make backend-run      Start the local FastAPI service on 127.0.0.1:38127"
	@echo "  make backend-test     Run backend pytest suite"
	@echo "  make ext-install      Install extension dependencies"
	@echo "  make ext-build        Build the Chrome MV3 bundle"
	@echo "  make ext-test         Run extension unit tests (vitest)"
	@echo "  make fixtures         Regenerate adapter HTML fixtures"
	@echo "  make test             Run every test suite"
	@echo "  make lint             Type-check both workspaces"

.PHONY: bootstrap
bootstrap: backend-install ext-install ## Install everything

.PHONY: backend-install
backend-install:
	cd $(BACKEND_DIR) && $(PYTHON) -m venv .venv && ./.venv/Scripts/python -m pip install -U pip && ./.venv/Scripts/python -m pip install -e ".[dev]"

.PHONY: backend-run
backend-run:
	cd $(BACKEND_DIR) && ./.venv/Scripts/python -m akc

.PHONY: backend-test
backend-test:
	cd $(BACKEND_DIR) && ./.venv/Scripts/python -m pytest -q

.PHONY: ext-install
ext-install:
	cd $(EXTENSION_DIR) && $(NPM) install

.PHONY: ext-build
ext-build:
	cd $(EXTENSION_DIR) && $(NPM) run build

.PHONY: ext-test
ext-test:
	cd $(EXTENSION_DIR) && $(NPM) run test

.PHONY: fixtures
fixtures:
	cd $(EXTENSION_DIR) && $(NPM) run fixtures

.PHONY: test
test: backend-test ext-test ## Run all tests

.PHONY: lint
lint:
	cd $(EXTENSION_DIR) && $(NPM) run typecheck
	cd $(BACKEND_DIR) && ./.venv/Scripts/python -m compileall akc
