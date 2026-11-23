.DEFAULT_GOAL := help
.PHONY: help check lint format typecheck test build docs notebooks clean

help: ## List the targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-z-]+:.*## / {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

check: lint typecheck test ## The gate of CI: lint, typecheck, test

lint: ## ruff check and format check
	uv run ruff check
	uv run ruff format --check

format: ## Format the code and fix what ruff can
	uv run ruff format
	uv run ruff check --fix

typecheck: ## mypy --strict
	uv run mypy

test: ## pytest with coverage (no key, no network)
	uv run pytest --cov --cov-report=term-missing

build: ## The wheel and the sdist, in dist/
	uv build

docs: ## The documentation site, in site/
	uv run --group docs mkdocs build --strict

# The notebooks download real data (170-290 MB each, once, into
# EGMS_DATA_DIR) and need the CLMS key: EGMS_SERVICE_KEY_FILE. They stay
# stored without outputs; each one saves its figure in docs/images/.
notebooks: ## Run every notebook (needs the CLMS key); figures go to docs/images/
	cd notebooks && for nb in *.ipynb; do \
		echo "== $$nb"; \
		uv run --group examples jupyter nbconvert --to notebook --execute --stdout "$$nb" > /dev/null || exit 1; \
	done

clean: ## Remove what the targets build (downloaded data stays)
	rm -rf dist site htmlcov .coverage .pytest_cache .mypy_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
