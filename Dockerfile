FROM python:3.11-slim AS base

RUN groupadd --gid 1000 scenetrace && \
    useradd --uid 1000 --gid scenetrace --create-home scenetrace

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --no-cache-dir .

RUN mkdir -p traces && chown scenetrace:scenetrace traces

USER scenetrace

ENTRYPOINT ["scenetrace"]
CMD ["--help"]
