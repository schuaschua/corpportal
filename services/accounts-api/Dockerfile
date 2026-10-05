# Build from the repo root:  docker build -f services/accounts-api/Dockerfile .
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
RUN uv sync --frozen --no-dev
COPY services/accounts-api/app.py ./app.py
# db-init (ci/scripts/db-init.sh) runs `python db/init_db.py` from this image.
COPY db db
COPY data/generator data/generator

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    AUTH_MODE=entra \
    REGION=unknown
USER 10001
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
