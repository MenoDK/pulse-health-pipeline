.DEFAULT_GOAL := help
PY ?= python3
# Use the virtualenv made by `make install` when it exists (CI has none and uses what is on PATH).
BIN := $(wildcard .venv/bin/)
API_PORT ?= 8300
DEV_COMPOSE := docker compose -f docker-compose.yml -f compose.dev.yml
# The database and Redis that `make test-integration` and `make eval` start on loopback (unusual ports on purpose).
DEV_ENV := DATABASE_URL=postgresql://pulse:$${DB_PASSWORD:-pulse}@localhost:$${DB_PORT:-15440}/pulse \
	REDIS_URL=redis://localhost:$${REDIS_PORT:-16395}/0
E2E_USER = --user $$(id -u):$$(id -g)
# The lab on, the site served, and a generated registry that is up to date to today (so the indicators do not age).
DEMO_ENV = LAB_MODE=true SITE_DIR=/app/site STANDIN_AS_OF=$$(date +%F)

help: ## list targets
	@grep -E '^[a-z0-9-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-18s %s\n", $$1, $$2}'

demo: ## build and start everything with the lab on, then print the address
	$(DEMO_ENV) docker compose up --build --wait --detach
	@echo ""
	@echo "  Ready: http://localhost:$(API_PORT)   (the lab needs no login; it answers only to localhost)"
	@echo "  Stop:  make down      Start from nothing: make reset"

down: ## stop the stack (keeps the database volume)
	docker compose --profile e2e down --remove-orphans

reset: ## stop the stack and delete its database volume
	docker compose --profile e2e down --volumes --remove-orphans

logs: ## follow the logs of the API, the worker and the scheduler
	docker compose logs -f api worker beat

install: ## create .venv and install with dev tools
	$(PY) -m venv .venv && .venv/bin/pip install -e '.[dev]'

lint: ## ruff (lint + format check)
	$(BIN)ruff check . && $(BIN)ruff format --check .

typecheck: ## mypy --strict
	$(BIN)mypy

test: ## tests that need no external service
	$(BIN)pytest -m "not integration"

test-integration: ## starts PostgreSQL+pgvector and Redis on loopback, then runs every test against them
	$(DEV_COMPOSE) up -d --wait db redis
	$(DEV_ENV) $(BIN)pytest -ra

numbers: ## fail if a figure printed on the landing page is not what the commands say
	$(BIN)python scripts/check_numbers.py

site-syntax: ## every script of the site must parse (a missing parenthesis once broke the lab, and no unit test could see it)
	@for f in site/*.js site/i18n/*.js; do node --check "$$f" || exit 1; done

check: lint typecheck test numbers site-syntax ## everything CI runs before Docker and the browser, minus the database tests

eval: ## print the search evaluation (36 labelled queries, four methods) from the real database
	$(DEV_COMPOSE) up -d --wait db
	$(DEV_ENV) $(BIN)pulse migrate && $(DEV_ENV) $(BIN)pulse index && $(DEV_ENV) $(BIN)pulse eval

mutate: ## break the code on purpose, one decision at a time; every break must turn a test red
	$(DEV_COMPOSE) up -d --wait db redis
	$(DEV_ENV) $(BIN)python scripts/sabotage.py

transcripts: ## re-record the tour on the landing page from the running code
	$(DEV_COMPOSE) up -d --wait db redis
	$(DEV_ENV) $(BIN)python scripts/record_transcripts.py

transcripts-check: ## fail if the tour on the landing page no longer matches what the code prints
	$(DEV_COMPOSE) up -d --wait db redis
	$(DEV_ENV) $(BIN)python scripts/record_transcripts.py --check

smoke: ## black-box checks against the running demo (make demo first)
	scripts/smoke.sh http://localhost:$(API_PORT)

e2e: ## browser tests (Playwright + axe) against the demo, in a container
	@mkdir -p docs/img  # Docker would create a missing bind-mount source as root
	$(DEMO_ENV) docker compose up --build --wait --detach
	$(DEMO_ENV) docker compose --profile e2e run --rm $(E2E_USER) e2e

screenshots: ## re-take the README screenshots (docs/img) from the running demo
	@mkdir -p docs/img
	$(DEMO_ENV) docker compose up --build --wait --detach
	$(DEMO_ENV) docker compose --profile e2e run --rm $(E2E_USER) -e SHOTS=1 e2e \
		bash -lc "npm ci --no-audit --no-fund && npx playwright test shots"

.PHONY: help demo down reset logs install lint typecheck test test-integration numbers site-syntax check eval mutate transcripts transcripts-check smoke e2e screenshots
