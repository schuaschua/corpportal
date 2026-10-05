# Build from the repo root:  docker build -f services/outbox-relay/Dockerfile .
FROM python:3.12-slim

ARG DEBIAN_FRONTEND=noninteractive
# Microsoft ODBC Driver 18 for SQL Server (Azure SQL in AKS, SQL Server 2022 locally).
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && . /etc/os-release \
 && curl -fsSL -o /tmp/packages-microsoft-prod.deb "https://packages.microsoft.com/config/debian/${VERSION_ID}/packages-microsoft-prod.deb" \
 && dpkg -i /tmp/packages-microsoft-prod.deb && rm /tmp/packages-microsoft-prod.deb \
 && apt-get update \
 && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 unixodbc \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.8 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
COPY services/common services/common
RUN uv sync --frozen --no-dev --group relay
COPY services/outbox-relay/app.py ./app.py

# /lake is the files-sink landing volume locally; owned by the runtime user so a fresh
# named volume inherits it.
RUN mkdir -p /lake/landing && chown -R 10001:10001 /lake

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    RELAY_SINK=eventhubs
USER 10001
CMD ["python", "app.py"]
