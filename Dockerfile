# Runtime image for the CLI: `docker run ... apiframework:dev run /job/job.yaml`.
# Installs the runtime extras only (yaml, socks, redis, otel); dlt is left out to keep it small.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd --create-home --uid 10001 apiframework

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv pip install --system --no-cache ".[yaml,socks,redis,otel]"

USER apiframework
WORKDIR /home/apiframework

ENTRYPOINT ["apiframework"]
CMD ["--help"]
