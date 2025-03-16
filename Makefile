.PHONY: format lint lint-fix test clean setup help check analyze

SHELL := /bin/bash

PYTHON := .venv/bin/python
PYTEST := .venv/bin/pytest
RUFF := .venv/bin/ruff

# Diretório de código
SRC_DIR := .

help:
	@echo "Comandos disponíveis:"
	@echo "make format     - Formata o código com ruff"
	@echo "make lint       - Executa o linter (ruff) sem corrigir"
	@echo "make lint-fix   - Executa o linter (ruff) e corrige problemas automaticamente"
	@echo "make test       - Executa os testes"
	@echo "make check      - Executa formatação e lint"
	@echo "make analyze    - Analisa dependências de importação do código com ruff"
	@echo "make clean      - Remove arquivos temporários"


format:
	$(RUFF) format $(SRC_DIR)

lint:
	$(RUFF) check $(SRC_DIR)

lint-fix:
	$(RUFF) check --fix $(SRC_DIR)

# Comando específico para ordenação de importações, caso queira executar separadamente
isort:
	$(RUFF) check --select I --fix $(SRC_DIR)

# Análise de dependências com ruff
analyze:
	$(RUFF) analyze graph $(SRC_DIR)

check: format lint

test:
	$(PYTEST) $(TEST_DIR) -v

clean:
	rm -rf .ruff_cache .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete