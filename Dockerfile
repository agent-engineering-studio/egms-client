# egms-client with every extra: the library, the command line, the MCP server,
# the API behind the page of a Comune (demo/api.py) and the notebooks. The page
# itself is another image, built from demo/web.
#
#   docker compose up            the page, on http://127.0.0.1:3003
#   docker build -t egms-client:local .
#
# The CLMS key is never copied in (.dockerignore): it comes at run time, as a
# file mounted read-only or as a variable (see compose.yaml and .env.example).
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /bin/uv

# rasterio brings its own GDAL, which needs libexpat from the system.
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    EGMS_DATA_DIR=/data

WORKDIR /app

# The dependencies first: this layer is rebuilt only when they change.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --all-extras --group demo --group examples --no-install-project

COPY README.md LICENSE ./
COPY src src
RUN uv sync --locked --no-dev --all-extras --group demo --group examples --no-editable

# Fail the build, not the first run, if a system library is missing.
RUN python -c "import rasterio, pyproj, pandas, mcp, starlette, uvicorn, egms_client"

COPY demo/api.py demo/notebook.sh demo/
COPY benchmarks benchmarks
COPY examples examples
COPY notebooks notebooks

RUN useradd --create-home egms && mkdir /data && chown egms /data /app/notebooks
USER egms
VOLUME /data

EXPOSE 8010
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8010/api/health', timeout=4)"]

CMD ["uvicorn", "--app-dir", "demo", "api:app", "--host", "0.0.0.0", "--port", "8010"]
