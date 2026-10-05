#!/usr/bin/env bash
# Jenkins VM agent, Release (primary only): schema, synthetic data and row-level security in
# Azure SQL, plus contained users for the services' workload identities. SQL only has a private endpoint, so init_db.py runs as a one-off Job in AKS
# (the accounts-api image carries db/ and the generator) with a short-lived SQL token of
# Jenkins' identity (a member of the AKS admin group, which is the SQL Entra admin).
# Re-runs keep existing data (init_db.py: RESEED=1 regenerates).
set -euo pipefail

outputs="${1:-reports/tf-outputs.json}"
: "${IMAGE_REPO:?}" "${IMAGE_TAG:?}"
py() { python3 ci/scripts/tf_outputs.py "$@"; }
export KUBECONFIG="$PWD/.kube/primary"

sql_fqdn="$(py get "$outputs" sql_fqdn)"
sql_db="$(py get "$outputs" sql_database_name)"
principals=""
for svc in accounts-api payments-api insights-api outbox-relay; do
  principals+="${principals:+,}id-corportal-$svc:$(py get "$outputs" workload_identity_client_ids "$svc")=db_datareader+db_datawriter"
done
# The Databricks jobs (service credential sc-portal-sql) write serving as pipeline_writer.
principals+=",id-corportal-databricks:$(py get "$outputs" databricks_access_connector_client_id)=pipeline_writer"

kubectl create namespace corportal --dry-run=client -o yaml | kubectl apply -f - >/dev/null
kubectl -n corportal create secret generic db-init-token \
  --from-literal=token="$(az account get-access-token --resource https://database.windows.net/ --query accessToken -o tsv)" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
trap 'kubectl -n corportal delete secret db-init-token --ignore-not-found >/dev/null' EXIT

kubectl -n corportal delete job db-init --ignore-not-found >/dev/null
kubectl -n corportal apply -f - <<YAML
apiVersion: batch/v1
kind: Job
metadata:
  name: db-init
spec:
  backoffLimit: 1
  ttlSecondsAfterFinished: 3600
  template:
    metadata:
      labels:
        app.kubernetes.io/part-of: corportal
        sidecar.istio.io/inject: "false"   # a one-off; SQL is reached directly
    spec:
      restartPolicy: Never
      containers:
        - name: db-init
          image: $IMAGE_REPO/accounts-api:$IMAGE_TAG
          command: ["python", "db/init_db.py"]
          env:
            - name: DB_URL
              value: "mssql+pyodbc://@$sql_fqdn:1433/$sql_db?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&Authentication=ActiveDirectoryAccessToken"
            - name: SQL_ACCESS_TOKEN
              valueFrom: {secretKeyRef: {name: db-init-token, key: token}}
            - name: SQL_PRINCIPALS
              value: "$principals"
          resources:
            requests: {cpu: 100m, memory: 256Mi}
            limits: {memory: 1Gi}
YAML

status=""
for _ in $(seq 180); do   # up to 15 minutes; stop at the first Complete or Failed
  status="$(kubectl -n corportal get job db-init -o jsonpath='{range .status.conditions[?(@.status=="True")]}{.type}{" "}{end}')"
  case "$status" in *Complete*|*Failed*) break ;; esac
  sleep 5
done
if [[ "$status" != *Complete* ]]; then
  kubectl -n corportal logs job/db-init --tail=50 || true
  echo "db-init did not complete (${status:-timed out})" >&2
  exit 1
fi
kubectl -n corportal logs job/db-init --tail=30
