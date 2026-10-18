# Production image for the API and the worker.
#
# Built once per commit by CI and pushed to GHCR; servers only pull it
# (docs/adr/0010-pull-based-deploys-from-ghcr.md). A local build from inside
# Iran still works: Python packages come from requirements.txt, exported from
# uv.lock WITH hashes, so any PyPI mirror can be used (PIP_INDEX_URL) without
# trusting it: pip refuses a package whose hash does not match.
# Pin the base image by digest once you have pulled it once:
#   FROM python:3.13-slim-bookworm@sha256:<digest>
FROM python:3.13-slim-bookworm AS runtime

ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --home-dir /app app

COPY requirements.txt ./
RUN python -m venv /app/.venv \
    && /app/.venv/bin/pip install --no-cache-dir --require-hashes \
       --index-url "$PIP_INDEX_URL" -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY scripts ./scripts
COPY alembic.ini main.py ./

RUN chown -R app:app /app
USER app

# The commit GET /health reports; CI passes it (--build-arg GIT_COMMIT=<sha>).
# Late in the file so a new commit does not invalidate the dependency layer.
ARG GIT_COMMIT=
ENV GIT_COMMIT=${GIT_COMMIT}

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:' + __import__('os').environ.get('PORT', '8000') + '/health', timeout=3)"

# Production runs several workers behind nginx (deploy/compose.prod.yml sets
# the command); this default is for local "docker compose up".
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips ${FORWARDED_ALLOW_IPS:-127.0.0.1}"]
