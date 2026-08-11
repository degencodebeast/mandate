#!/bin/sh
set -eu

suffix="$$"
image="mandate-container-test:${suffix}"
network="mandate-container-test-${suffix}"
database="mandate-container-db-${suffix}"
api="mandate-container-api-${suffix}"

cleanup() {
    docker rm -f "$api" "$database" >/dev/null 2>&1 || true
    docker network rm "$network" >/dev/null 2>&1 || true
    docker image rm "$image" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

docker build --file Dockerfile --tag "$image" .

docker run --rm "$image" sh -c '
    test "$(id -u)" -ne 0
    test "$(circle --version)" = "0.0.6"
    test "$(cd /opt/circle && node -p "require(\"ws/package.json\").version")" = "8.21.0"
    test ! -d /opt/circle/node_modules/typescript
    test ! -d /opt/circle/node_modules/@typescript
    circle services pay --help >/dev/null
    circle wallet execute --help >/dev/null
    circle wallet login --help >/dev/null
    cd /app/scripts
    node --input-type=module -e "await import(\"viem\")"
'

docker network create "$network" >/dev/null
docker run --detach \
    --name "$database" \
    --network "$network" \
    --env POSTGRES_USER=mandate \
    --env POSTGRES_PASSWORD=container-test \
    --env POSTGRES_DB=mandate \
    postgres:16.6-alpine >/dev/null

database_ready=false
for _attempt in $(seq 1 30); do
    if docker exec "$database" pg_isready --username mandate --dbname mandate >/dev/null 2>&1; then
        database_ready=true
        break
    fi
    sleep 1
done
if [ "$database_ready" != true ]; then
    docker logs "$database"
    exit 1
fi

docker run --detach \
    --name "$api" \
    --network "$network" \
    --env DATABASE_URL="postgresql://mandate:container-test@${database}:5432/mandate" \
    --env MANDATE_ENV=production \
    "$image" >/dev/null

api_ready=false
for _attempt in $(seq 1 40); do
    status="$(docker inspect --format '{{.State.Health.Status}}' "$api" 2>/dev/null || true)"
    if [ "$status" = healthy ]; then
        api_ready=true
        break
    fi
    if [ "$(docker inspect --format '{{.State.Running}}' "$api" 2>/dev/null || true)" = false ]; then
        break
    fi
    sleep 1
done
if [ "$api_ready" != true ]; then
    docker logs "$api"
    exit 1
fi

docker exec "$database" psql \
    --username mandate \
    --dbname mandate \
    --tuples-only \
    --command "SELECT count(*) FROM schema_migrations" \
    | grep -Eq '[1-9][0-9]*'

echo "Mandate container contract passed."
