FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml /app/pyproject.toml
COPY autotrader /app/autotrader
COPY tests/test_aihf_ecosystem_access.py /app/tests/test_aihf_ecosystem_access.py
COPY ecosystem-token/config /app/ecosystem-token/config

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -e '.[dev]' \
    && python -m compileall -q autotrader \
    && python -m pytest -q tests/test_aihf_ecosystem_access.py \
    && python -c "import autotrader.api.server; print('server-import-ok')"

CMD ["sh", "-lc", "python -m http.server ${PORT:-8080}"]
