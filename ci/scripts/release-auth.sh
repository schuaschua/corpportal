#!/usr/bin/env bash
# Jenkins VM agent, before the release: sign in with the VM's managed identity (P-3, no stored
# keys) and write into the workspace what the release steps need:
#   .kube/<region>         kubeconfig per AKS cluster (kubelogin msi)
#   .tokens/databricks     short-lived Databricks access token (about an hour)
set -euo pipefail

clusters="${1:-reports/aks-clusters.txt}"   # "<region> <resource group> <name>" lines
: "${ARM_CLIENT_ID:?}"

az login --identity --client-id "$ARM_CLIENT_ID" --output none
[ -n "${ARM_SUBSCRIPTION_ID:-}" ] && az account set --subscription "$ARM_SUBSCRIPTION_ID"

mkdir -p .kube .tokens
chmod 700 .tokens
while read -r region rg name; do
  [ -n "$region" ] || continue
  az aks get-credentials --resource-group "$rg" --name "$name" --file ".kube/$region" --overwrite-existing --output none
  kubelogin convert-kubeconfig --kubeconfig ".kube/$region" -l msi --client-id "$ARM_CLIENT_ID"
done < "$clusters"

# 2ff814a6-...: the Azure Databricks first-party application (Entra token audience).
az account get-access-token --resource 2ff814a6-3304-4ab8-85cb-cd0e6f879c1d \
  --query accessToken --output tsv > .tokens/databricks
echo "release-auth: kubeconfigs in .kube/ and the Databricks token ready"
