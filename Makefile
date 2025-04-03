.PHONY: format lint lint-fix test clean setup help check analyze install install-dev

SHELL := /bin/bash

# Python executables
PYTHON_DOCKER := .venv/bin/python
PYTHON_DEV := .venv-dev/bin/python
PYTEST_DOCKER := .venv/bin/pytest
PYTEST_DEV := .venv-dev/bin/pytest
RUFF_DOCKER := .venv/bin/ruff
RUFF_DEV := .venv-dev/bin/ruff
UV := uv

# Use dev environment by default for local development
PYTHON := $(PYTHON_DEV)
PYTEST := $(PYTEST_DEV)
RUFF := $(RUFF_DEV)


# Source code directory
SRC_DIR := .

help:
	@echo "Available commands:"
	@echo "make install     - Install dependencies in Docker environment (uses uv if available, asks to use pip)"
	@echo "make install-dev - Install dependencies in development environment (uses uv if available, asks to use pip)"
	@echo "make format      - Format code with ruff"
	@echo "make lint        - Run linter (ruff) without fixes"
	@echo "make lint-fix    - Run linter (ruff) and auto-fix issues"
	@echo "make test        - Run tests"
	@echo "make check       - Run formatting and linting"
	@echo "make analyze     - Analyze code import dependencies with ruff"
	@echo "make clean       - Remove temporary files"


install:
	@if command -v $(UV) >/dev/null 2>&1; then \
		echo "Using uv to create and install dependencies in Docker environment..."; \
		$(UV) venv .venv; \
		$(UV) sync --frozen; \
	else \
		echo -e "\033[31mWARNING: uv not found!\033[0m"; \
		echo -e "It's recommended to install uv: https://docs.astral.sh/uv/getting-started/installation/"; \
		echo -e "\033[33mInstallation via standard venv+pip is slower and may have version issues.\033[0m"; \
		read -p "Continue with standard venv+pip? [y/N] " choice; \
		case "$$choice" in \
			y|Y ) \
				echo "Creating venv and installing with pip..."; \
				python -m venv .venv; \
				.venv/bin/pip install -r requirements.txt; \
				;; \
			* ) \
				echo -e "\n\033[31mInstallation canceled."; \
				exit 1; \
				;; \
		esac; \
	fi
	@echo "Done! Use 'make install-dev' for local development environment."

install-dev:
	@if command -v $(UV) >/dev/null 2>&1; then \
		echo "Using uv to create and install dependencies in development environment..."; \
		$(UV) venv .venv-dev; \
		$(UV) sync --frozen --python .venv-dev/bin/python; \
	else \
		echo -e "\033[31mWARNING: uv not found!\033[0m"; \
		echo -e "It's recommended to install uv: https://docs.astral.sh/uv/getting-started/installation/"; \
		echo -e "\033[33mInstallation via standard venv+pip is slower and may have version issues.\033[0m"; \
		read -p "Continue with standard venv+pip? [y/N] " choice; \
		case "$$choice" in \
			y|Y ) \
				echo "Creating venv and installing with pip..."; \
				python -m venv .venv-dev; \
				.venv-dev/bin/pip install -r requirements.txt; \
				;; \
			* ) \
				echo -e "\n\033[31mInstallation canceled."; \
				exit 1; \
				;; \
		esac; \
	fi
	@echo "Done!"

format:
	$(RUFF) format $(SRC_DIR)

lint:
	$(RUFF) check $(SRC_DIR)

lint-fix:
	$(RUFF) check --fix $(SRC_DIR)

# Specific command for import sorting (to run separately)
isort:
	$(RUFF) check --select I --fix $(SRC_DIR)

# Dependency analysis with ruff
analyze:
	$(RUFF) analyze graph $(SRC_DIR)

check: format lint

test:
	$(PYTEST) $(TEST_DIR) -v

clean:
	rm -rf .ruff_cache .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	@echo "Note: Use 'git clean -fdx' to remove virtual environments"
