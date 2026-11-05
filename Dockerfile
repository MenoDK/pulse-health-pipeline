# syntax=docker/dockerfile:1.7

# ---- builder: resolves and installs dependencies into an isolated virtualenv ----------------------
FROM python:3.12-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
# The cache mount keeps wheels out of the image layer, which is the point of --no-cache-dir.
# hadolint ignore=DL3042
RUN --mount=type=cache,target=/root/.cache/pip pip install .

# ---- runtime: no compiler, no pip cache, no root ----------------------------------------------------
FROM python:3.12-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app \
    && mkdir /certs && chown 10001:10001 /certs
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
# The migrations and the landing page + lab UI: plain files. The site is served only when SITE_DIR points at it.
COPY --chown=root:root alembic.ini ./
COPY --chown=root:root alembic ./alembic
COPY --chown=root:root --chmod=0755 site ./site
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import sys, urllib.request as u; sys.exit(0 if u.urlopen('http://127.0.0.1:8000/health/live', timeout=2).status == 200 else 1)"]
CMD ["uvicorn", "pulse.api.app:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
