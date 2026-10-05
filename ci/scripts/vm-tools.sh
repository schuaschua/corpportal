#!/usr/bin/env bash
# Jenkins VM agent: put the pinned Trivy and Databricks CLI binaries in the workspace's .bin/
# (no change to the shared host). Re-runs reuse what is already there.
set -euo pipefail

TRIVY_VERSION=0.74.0   # v0.65.0 is no longer published on GitHub
DATABRICKS_VERSION=0.266.0
mkdir -p .bin

if ! .bin/trivy --version 2>/dev/null | grep -q "$TRIVY_VERSION"; then
  curl -fsSL "https://github.com/aquasecurity/trivy/releases/download/v$TRIVY_VERSION/trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz" \
    | tar -xz -C .bin trivy
fi

if ! .bin/databricks --version 2>/dev/null | grep -q "$DATABRICKS_VERSION"; then
  curl -fsSLo .bin/databricks.zip "https://github.com/databricks/cli/releases/download/v$DATABRICKS_VERSION/databricks_cli_${DATABRICKS_VERSION}_linux_amd64.zip"
  unzip -oq .bin/databricks.zip databricks -d .bin && rm .bin/databricks.zip
fi

.bin/trivy --version | head -1
.bin/databricks --version
