.PHONY: test lint check docker-build docker-test docker-lint

test:
	.venv/bin/pytest

lint:
	.venv/bin/ruff check src tests

check: lint test

docker-build:
	docker compose build

docker-test:
	docker compose run --rm test

docker-lint:
	docker compose run --rm lint
