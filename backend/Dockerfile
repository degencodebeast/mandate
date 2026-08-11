# syntax=docker/dockerfile:1.7

# Mandate uses the Circle CLI for testnet Payment Authorization and Arc writes.
# Keep the CLI and its Node runtime separate from the Python dependency build.
FROM node:22-bookworm-slim@sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436 AS node-tools

WORKDIR /opt/circle
COPY docker/package.json docker/package-lock.json ./
RUN npm ci --omit=dev --omit=optional --omit=peer --no-audit --no-fund

WORKDIR /opt/receipt-reader
COPY scripts/package.json scripts/package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund


FROM python:3.13-slim-bookworm@sha256:00faa2debb87529f9f0764e9491d8ba400a3678976616c3bd7cb193745ac20d1 AS python-dependencies

COPY --from=ghcr.io/astral-sh/uv:0.11.6@sha256:b1e699368d24c57cda93c338a57a8c5a119009ba809305cc8e86986d4a006754 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --frozen --no-dev


FROM python:3.13-slim-bookworm@sha256:00faa2debb87529f9f0764e9491d8ba400a3678976616c3bd7cb193745ac20d1 AS runtime

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd \
        --uid 10001 \
        --create-home \
        --home-dir /home/mandate \
        --shell /usr/sbin/nologin \
        mandate \
    && mkdir -p /home/mandate/.circle-cli /app/scripts \
    && chown -R mandate:mandate /home/mandate /app

WORKDIR /app

COPY --from=python-dependencies --chown=mandate:mandate /app/.venv ./.venv
COPY --from=node-tools /usr/local/bin/node /usr/local/bin/node
COPY --from=node-tools /opt/circle /opt/circle
COPY --from=node-tools --chown=mandate:mandate /opt/receipt-reader/node_modules ./scripts/node_modules
COPY --chown=mandate:mandate src ./src
COPY --chown=mandate:mandate migrations ./migrations
COPY --chown=mandate:mandate scripts/read-receipts.mjs ./scripts/read-receipts.mjs

ENV PATH="/app/.venv/bin:/opt/circle/node_modules/.bin:${PATH}" \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/mandate \
    CIRCLE_CLI_HOME=/home/mandate/.circle-cli \
    RECEIPT_READER_SCRIPT=/app/scripts/read-receipts.mjs \
    HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000
VOLUME ["/home/mandate/.circle-cli"]

USER mandate

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]

CMD ["python", "-m", "mandate.api.startup"]
