#!/usr/bin/env bash
# Jenkins VM agent: `databricks bundle deploy` of databricks/databricks.yml (architecture 5b).
# The CLI binary comes from ci/scripts/vm-tools.sh (.bin/). DEMO_MODE=true switches the batch cadence to 30 s.
set -euo pipefail

outputs="$PWD/${1:-reports/tf-outputs.json}"
tf() { python3 ci/scripts/tf_outputs.py get "$outputs" "$@"; }

DATABRICKS_HOST="$(tf databricks_host)"
case "$DATABRICKS_HOST" in https://*) ;; *) DATABRICKS_HOST="https://$DATABRICKS_HOST" ;; esac
# Auth: the short-lived Entra token release-auth.sh wrote for Jenkins' identity (it created the
# workspace, so it is a workspace admin). The node's ARM_* variables are hidden from the CLI:
# with both it refuses ("more than one authorization method": azure and pat).
DATABRICKS_TOKEN="$(cat .tokens/databricks)"
export DATABRICKS_HOST DATABRICKS_TOKEN DATABRICKS_AUTH_TYPE=pat
unset ARM_USE_MSI ARM_CLIENT_ID ARM_TENANT_ID ARM_SUBSCRIPTION_ID
# Use the VM's Terraform: the CLI's own download fails its checksum check (expired signing key).
DATABRICKS_TF_EXEC_PATH="$(command -v terraform)"
DATABRICKS_TF_VERSION="$(terraform version -json | python3 -c 'import json,sys; print(json.load(sys.stdin)["terraform_version"])')"
export DATABRICKS_TF_EXEC_PATH DATABRICKS_TF_VERSION
eventhub_namespace="$(tf eventhub_namespace_fqdn)"
sql_server="$(tf sql_fqdn)"

if [ "${DEMO_MODE:-false}" = "true" ]; then
  cadence=30;  schedule="0/30 * * * * ?"
else
  cadence=300; schedule="0 0/5 * * * ?"
fi

cd databricks
../.bin/databricks bundle deploy -t prod \
  --var="eventhub_namespace=$eventhub_namespace" \
  --var="sql_server=$sql_server" \
  --var="batch_cadence_seconds=$cadence" \
  --var="batch_schedule=$schedule"
