#!/usr/bin/env bash
# After Terraform (Jenkins VM agent, managed identity): for every AKS cluster, fetch a
# kubeconfig, list the cluster for the release stage and write its generated Helm values.
# Needs az, kubectl and kubelogin on the VM (`az aks install-cli`).
set -euo pipefail

outputs="${1:-reports/tf-outputs.json}"
: "${ARM_CLIENT_ID:?}" "${ARM_TENANT_ID:?}"
py() { python3 ci/scripts/tf_outputs.py "$@"; }

az login --identity --client-id "$ARM_CLIENT_ID" --output none
[ -n "${ARM_SUBSCRIPTION_ID:-}" ] && az account set --subscription "$ARM_SUBSCRIPTION_ID"
mkdir -p reports .kube
: > reports/aks-clusters.txt

for region in $(py regions "$outputs"); do
  name="$(py get "$outputs" aks_clusters "$region" name)"
  rg="$(py get "$outputs" aks_clusters "$region" resource_group)"
  kc=".kube/$region"
  echo "$region $rg $name" >> reports/aks-clusters.txt
  az aks get-credentials --resource-group "$rg" --name "$name" --file "$kc" --overwrite-existing --output none
  kubelogin convert-kubeconfig --kubeconfig "$kc" -l msi --client-id "$ARM_CLIENT_ID"
  py helm-values "$outputs" "$region" > "reports/values-tf-$region.yaml"
  echo "[$region] AKS $name: API server https://$(py get "$outputs" aks_clusters "$region" fqdn)"
done
