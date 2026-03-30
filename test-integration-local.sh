#!/bin/bash
# Local integration test runner

set -e

echo "Building FlareSolverr Docker image..."
docker build -t flaresolverr-local:test .

echo "Starting services with docker-compose..."
# Create a test compose file that includes FlareSolverr
cat > docker-compose.test.yml << 'EOF'
services:
  flaresolverr:
    image: flaresolverr-local:test
    ports:
      - "127.0.0.1:8191:8191"
    networks:
      - test-network

  proxy-http:
    build:
      context: .github/docker/tinyproxy
      dockerfile: Dockerfile
    ports:
      - "127.0.0.1:8888:8888"
    networks:
      - test-network

  proxy-socks:
    image: serjs/go-socks5-proxy:latest
    environment:
      - REQUIRE_AUTH=false
    ports:
      - "127.0.0.1:1080:1080"
    networks:
      - test-network

networks:
  test-network:
    driver: bridge
EOF

docker compose -f docker-compose.test.yml down -v 2>/dev/null || true
docker compose -f docker-compose.test.yml up -d

echo "Waiting for FlareSolverr to be ready..."
for i in {1..30}; do
    if curl -fsS http://127.0.0.1:8191/ >/dev/null 2>&1; then
        echo "FlareSolverr is ready!"
        break
    fi
    sleep 2
    if [ $i -eq 30 ]; then
        echo "FlareSolverr failed to start"
        docker compose -f docker-compose.test.yml logs flaresolverr
        docker compose -f docker-compose.test.yml down -v
        exit 1
    fi
done

echo "Waiting for proxies to be ready..."
for i in {1..30}; do
    if curl -fsS --proxy http://127.0.0.1:8888 https://example.com >/dev/null 2>&1 && \
       curl -fsS --socks5-hostname 127.0.0.1:1080 https://example.com >/dev/null 2>&1; then
        echo "Proxies are ready!"
        break
    fi
    sleep 2
    if [ $i -eq 30 ]; then
        echo "Proxies failed to start"
        docker compose -f docker-compose.test.yml logs
        docker compose -f docker-compose.test.yml down -v
        exit 1
    fi
done

echo "Running proxy tests with Docker internal network..."
cd "$(dirname "$0")"

# Run tests with Docker service names for proxy URLs
export FLARESOLVERR_URL=http://127.0.0.1:8191
export PROXY_HTTP_URL=http://proxy-http:8888
export PROXY_SOCKS_URL=socks5://proxy-socks:1080

# Install test deps if needed
uv sync --group dev --extra test 2>/dev/null || true

echo ""
echo "Running: test_v1_endpoint_request_get_proxy_http_param"
uv run pytest tests/integration/test_api.py::TestFlareSolverr::test_v1_endpoint_request_get_proxy_http_param -v || true

echo ""
echo "Running: test_v1_endpoint_request_get_proxy_socks_param"
uv run pytest tests/integration/test_api.py::TestFlareSolverr::test_v1_endpoint_request_get_proxy_socks_param -v || true

echo ""
echo "Cleaning up..."
docker compose -f docker-compose.test.yml down -v
rm -f docker-compose.test.yml

echo ""
echo "Test run complete!"
