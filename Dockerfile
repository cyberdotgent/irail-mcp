# syntax=docker/dockerfile:1.7
# Build stage: install the package into a self-contained virtualenv with uv.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN uv venv /opt/venv && uv pip install --no-cache --python /opt/venv/bin/python .

# Runtime stage: minimal image, non-root user, HTTP transport by default.
FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.title="irail-mcp" \
      org.opencontainers.image.description="MCP server for Belgian railway data via the iRail API" \
      org.opencontainers.image.source="https://github.com/cyberdotgent/irail-mcp" \
      org.opencontainers.image.licenses="MIT"

RUN groupadd --system app && useradd --system --gid app --no-create-home app
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"

# Override CMD for stdio: docker run -i irail-mcp --transport stdio
ENTRYPOINT ["irail-mcp"]
CMD ["--transport", "http", "--host", "0.0.0.0", "--port", "8000"]
