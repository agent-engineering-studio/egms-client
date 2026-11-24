.DEFAULT_GOAL := help
.PHONY: help check lint format typecheck test build docs notebooks notebooks-offline bench up demo down logs clean

help: ## List the targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-z-]+:.*## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

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

# 04 and 05 run on the crops of the benchmark: no key, no download. CI runs them.
OFFLINE = 04_how_much_to_trust.ipynb 05_cells_for_a_model.ipynb
notebooks-offline: ## Run the notebooks that need no key (04, 05), as CI does
	cd notebooks && for nb in $(OFFLINE); do \
		echo "== $$nb"; \
		uv run --group examples jupyter nbconvert --to notebook --execute --stdout "$$nb" > /dev/null || exit 1; \
	done

bench: ## Score the known cases and the fidelity set offline, as CI does
	uv run python -m benchmarks.run --check
	uv run python -m benchmarks.faithful score --check

# Docker: every setting is in .env (cp .env.example .env). Ports on 127.0.0.1 only.
up: ## The page, the notebooks and the MCP server in Docker (http://127.0.0.1:3003)
	docker compose --profile notebook --profile mcp up -d --build
	@echo "page:      http://127.0.0.1:$${EGMS_UI_PORT:-3003}"
	@echo "back office: http://127.0.0.1:$${EGMS_ADMIN_PORT:-3004} (EGMS_ADMIN_* in .env)"
	@echo "notebooks: http://127.0.0.1:$${EGMS_NOTEBOOK_PORT:-8889} (token: make logs)"
	@echo "MCP:       http://127.0.0.1:$${EGMS_MCP_PORT:-8768}/mcp"

demo: ## Only the page, on the crops of the benchmark: no key needed
	EGMS_UI_SOURCE=demo docker compose up -d --build api ui
	@echo "page: http://127.0.0.1:$${EGMS_UI_PORT:-3003}"

admin-password: ## The hash of the administrator's password, for EGMS_ADMIN_PASSWORD_HASH in .env
	@uv run --group demo python demo/admin.py hash

down: ## Stop the containers (the downloaded tiles stay in the volume)
	docker compose --profile notebook --profile mcp --profile tools down

logs: ## Follow the logs of the containers
	docker compose --profile notebook --profile mcp logs -f --tail=50

clean: ## Remove what the targets build (downloaded data stays)
	rm -rf dist site htmlcov .coverage .pytest_cache .mypy_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
