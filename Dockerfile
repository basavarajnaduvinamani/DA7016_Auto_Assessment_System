FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    AUTOASSESS_DATA_DIR=/var/lib/secondread \
    AUTOASSESS_CACHE_DIR=/tmp/autoassess-cache \
    GRADIO_ANALYTICS_ENABLED=False

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY src/ src/
RUN --mount=type=secret,id=build_ca \
    if [ -f /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi \
    && pip install --no-cache-dir ".[web,ingest,annotate,postgres]" \
    && useradd --create-home --uid 10001 secondread \
    && mkdir -p /var/lib/secondread \
    && chown secondread:secondread /var/lib/secondread
USER secondread
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/healthz', timeout=4).read()"
CMD ["sh", "-c", "exec autoassess serve --host 0.0.0.0 --port \"${PORT:-8000}\""]
