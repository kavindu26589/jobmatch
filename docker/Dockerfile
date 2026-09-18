# jobmatcher server image.
#
# The web UI is a Vite + React app built in a Node stage and copied into the
# Python package's `static/` directory so the wheel ships it too. The app
# (jobmatcher) imports the sibling `opencode-gateway` package, so the build
# installs both from source. All config comes from environment variables at
# runtime (see root .env.example).

# syntax=docker/dockerfile:1

FROM node:22-alpine AS web-build
WORKDIR /build
COPY web/ ./web/
RUN cd web && npm ci && npm run build

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    REPORT_DIR=/opt/jobmatcher/reports

WORKDIR /opt/jobmatcher

COPY gateway/ ./gateway/
COPY app/ ./app/
COPY --from=web-build /build/app/src/jobmatcher/server/static/ \
    ./app/src/jobmatcher/server/static/

# lxml (python-docx) ships manylinux wheels, pypdf is pure Python and pdf
# rendering is reportlab (manylinux wheels), so no apt packages are needed on
# the slim base.
RUN pip install --no-cache-dir ./gateway ./app \
    && addgroup --system --gid 1001 jobmatcher \
    && adduser --system --uid 1001 --ingroup jobmatcher jobmatcher \
    && mkdir -p /opt/jobmatcher/reports \
    && chown -R jobmatcher:jobmatcher /opt/jobmatcher

USER jobmatcher

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]

CMD ["uvicorn", "jobmatcher.server.app:app", "--host", "0.0.0.0", "--port", "8000"]