# ---- 1. build the web UI (writes into src/ledger_agent/static) ---------------------------------
FROM node:22-slim AS ui
WORKDIR /src/ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

# ---- 2. build a wheel that contains the UI -----------------------------------------------------
FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml README.md ./
COPY src ./src
COPY --from=ui /src/src/ledger_agent/static ./src/ledger_agent/static
RUN pip install --no-cache-dir build && python -m build --wheel --outdir /dist

# ---- 3. minimal runtime: one process serves the UI and the API on :8000 ------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    LEDGER_DB_PATH=/data/ledger.db LEDGER_LOG_FORMAT=json
RUN useradd --create-home --uid 10001 ledger && mkdir /data && chown ledger /data
COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl
USER ledger
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
CMD ["ledger", "serve", "--host", "0.0.0.0", "--port", "8000"]
