# Makefile

.PHONY: all format check validate test test-cov test-integration test-integration-proxy

# Default target: runs format and check
all: validate test

# Format the code using ruff
format:
	ruff format --check --diff .

reformat-ruff:
	ruff format .

# Check the code using ruff
check:
	ruff check .

fix-ruff:
	ruff check . --fix

fix: reformat-ruff fix-ruff
	@echo "Updated code."

test:
	pytest tests/unit

test-cov:
	pytest tests/unit \
		--cov=dtos \
		--cov=sessions \
		--cov=metrics \
		--cov=bottle_plugins \
		--cov-report=xml \
		--cov-report=term-missing \
		--cov-fail-under=85

test-integration:
	pytest -m integration tests/integration; \
	status=$$?; \
	if [ $$status -eq 5 ]; then \
		echo "No integration tests collected (likely missing optional integration dependencies)."; \
		exit 0; \
	fi; \
	exit $$status

test-integration-proxy:
	docker compose -f docker-compose.integration.yml up -d --build
	for i in $$(seq 1 30); do \
		if curl -fsS --proxy http://127.0.0.1:8888 https://example.com >/dev/null && \
		   curl -fsS --socks5-hostname 127.0.0.1:1080 https://example.com >/dev/null; then \
			echo "Proxies are ready"; \
			break; \
		fi; \
		if [ $$i -eq 30 ]; then \
			echo "Proxy readiness check failed"; \
			docker compose -f docker-compose.integration.yml logs; \
			docker compose -f docker-compose.integration.yml down -v --remove-orphans; \
			exit 1; \
		fi; \
		sleep 2; \
	done
	pytest -m integration tests/integration/test_api.py -k "proxy_http_param or proxy_http_param_with_credentials or proxy_socks_param" -vv; \
	status=$$?; \
	docker compose -f docker-compose.integration.yml down -v --remove-orphans; \
	if [ $$status -eq 5 ]; then \
		echo "No integration proxy tests collected (likely missing optional integration dependencies)."; \
		exit 0; \
	fi; \
	exit $$status

vulture:
	vulture src/metrics.py src/sessions.py src/bottle_plugins --ignore-names "error_plugin,logger_plugin,setup,prometheus_plugin,SessionsStorage,session_ids"

complexity:
	radon cc . -a -nc

xenon:
	xenon -b D -m B -a B .

bandit:
	bandit -c pyproject.toml -r src -x src/undetected_chromedriver,src/build_package.py,src/utils.py,src/flaresolverr.py

pyright:
	pyright src/metrics.py src/bottle_plugins

# Validate the code (format + check)
validate: format check complexity bandit pyright vulture
	@echo "Validation passed. Your code is ready to push."
