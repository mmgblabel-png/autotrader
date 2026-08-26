FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY requirements.txt pyproject.toml README.md ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY campaign_automaton ./campaign_automaton
COPY config ./config
COPY scripts ./scripts
COPY app.py main.py ./

RUN mkdir -p /data && chown -R app:app /app /data && chmod +x /app/scripts/start.sh

USER app

EXPOSE 8000

CMD ["/app/scripts/start.sh"]
