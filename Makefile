.PHONY: format lint lint-fix test clean setup help check analyze install

SHELL := /bin/bash

PYTHON := .venv/bin/python
PYTEST := .venv/bin/pytest
RUFF := .venv/bin/ruff
UV := uv
PRE_COMMIT := .venv/bin/pre-commit


# Source code directory
SRC_DIR := .

help:
	@echo "Available commands:"
	@echo "make install       - Install dependencies (uses uv if available, asks to use pip)"
	@echo "make format        - Format code with ruff"
	@echo "make lint          - Run linter (ruff) without fixes"
	@echo "make lint-fix      - Run linter (ruff) and auto-fix issues"
	@echo "make test          - Run tests"
	@echo "make check         - Run formatting and linting"
	@echo "make analyze       - Analyze code import dependencies with ruff"
	@echo "make clean         - Remove temporary files"
	@echo "make install-hooks - Install pre-commit hooks"
	@echo "make pre-commit    - Execute all pre-commit hooks manually"
	@echo "make update-hooks  - Update pre-commit hooks to the latest versions"


install:
	@if [ ! -d ".venv" ]; then \
		python -m venv .venv; \
	fi
	@if command -v $(UV) >/dev/null 2>&1; then \
		echo "Using uv to install dependencies..."; \
		$(UV) sync --frozen; \
	else \
		echo -e "\033[31mWARNING: uv not found!\033[0m"; \
		echo -e "It's recomended to install uv: https://docs.astral.sh/uv/getting-started/installation/"; \
		echo -e "\033[33mInstallation via pip is slower and may have version issues.\033[0m"; \
		read -p "Continue with pip? [y/N] " choice; \
		case "$$choice" in \
			y|Y ) \
				echo "Installing with pip..."; \
				.venv/bin/pip install -r requirements.txt; \
				;; \
			* ) \
				echo -e "\n\033[31mInstallation canceled."; \
				exit 1; \
				;; \
		esac; \
	fi

install-hooks:
	${UV} add pre-commit
	${PRE_COMMIT} install

update-hooks:
	${PRE_COMMIT} autoupdate

pre-commit:
	${PRE_COMMIT} run --all-files

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