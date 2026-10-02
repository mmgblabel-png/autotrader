FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

COPY pyproject.toml README.md config.yaml ./
COPY autotrader ./autotrader
COPY tests ./tests

RUN python -m pip install --upgrade pip build \
    && python -m pip install -e ".[dev]" \
    && python -m pytest -q tests \
    && python -m build --wheel --outdir /wheels


FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    AUTOTRADER_CONFIG=/app/config.yaml \
    FUND_LEDGER_PATH=/data/fund_ledger.sqlite3 \
    EXECUTION_MODE=shadow \
    EMERGENCY_STOP=true \
    BITVAVO_DRY_RUN=true \
    BITVAVO_LIVE_TRADING=false \
    LIVE_EXECUTION_APPROVED=false \
    LIVE_EXECUTION_ADAPTER_INSTALLED=false \
    PORT=8000

WORKDIR /app

RUN groupadd --gid 10001 autotrader \
    && useradd --uid 10001 --gid autotrader --create-home --shell /usr/sbin/nologin autotrader \
    && mkdir -p /data /app/exports /app/logs \
    && chown -R autotrader:autotrader /data /app

COPY --from=builder /wheels /wheels
RUN python -m pip install /wheels/*.whl \
    && rm -rf /wheels

COPY --chown=autotrader:autotrader config.yaml /app/config.yaml

USER autotrader

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.getenv('PORT','8000'), timeout=3).read()"

CMD ["sh", "-c", "exec python -m uvicorn autotrader.api.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
