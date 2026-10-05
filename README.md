# corpportal

## Run

Local stack (SQL Server 2022, synthetic data, `accounts-api` on :8001, `payments-api` on :8002,
`insights-api` on :8003, the portal on :8088, plus the event flow: `outbox-relay` and the
`pipelines` medallion with the ML tasks):

```sh
cp .env.example .env
docker compose up -d --build
open http://localhost:8088          # sign in as Priya; switch to Tom or Omar from the user menu
curl -si -H 'X-Demo-User: priya' localhost:8001/dashboard
```

The portal (`web/`, React + Fluent UI v9) is served by nginx, which also proxies
`/api/accounts/*`, `/api/payments/*` and `/api/insights/*` to the APIs, so calls are same-origin and the region
badge can read `X-Served-From`. Its runtime config is written to `/config.js` from env at
container start (`VITE_AUTH_MODE`, `VITE_LINEAGE_URL`, `VITE_ENTRA_CLIENT_ID`,
`VITE_ENTRA_AUTHORITY`, `VITE_ENTRA_KNOWN_AUTHORITY`, `VITE_ENTRA_API_SCOPE`), so one image
works everywhere. In compose it runs with `VITE_AUTH_MODE=dev` (the `X-Demo-User` header);
`entra` uses MSAL sign-in and a bearer token.

Portal development against the compose APIs: `cd web && npm ci && npm run dev` (Vite on :5173
proxies to :8001/:8002/:8003; defaults to Entra sign-in unless `VITE_AUTH_MODE=dev`, e.g.
`VITE_AUTH_MODE=dev npm run dev`). Build and test: `npm run build && npx vitest run`.

The `db-init` job creates the `corportal` database, applies `db/schema.sql`, loads the
synthetic data (`SEED`, `AS_OF` in `.env`) and applies `db/rls.sql`. Data is kept across
restarts; set `RESEED=1` to regenerate. Locally, `X-Demo-User` (`priya`, `tom`, `omar`, …)
stands in for sign-in (`AUTH_MODE=dev`).

Try the payment flow:

```sh
curl -s -H 'X-Demo-User: priya' -H 'Content-Type: application/json' localhost:8002/payments \
  -d '{"from_account_id": 2, "to_account_id": 1, "amount": "450000.00", "reference": "Payroll top-up"}'
curl -s -X POST -H 'X-Demo-User: tom' localhost:8002/payments/<id>/approve
```

### Event flow (piece 3)

An approved payment travels ledger → outbox → Event Hubs → bronze → silver → gold → SQL
`serving`, and the portal's **Behind the scenes** drawer ticks each stage for the latest payment
(`GET /api/accounts/pipeline/trace/{payment_id}`, polled every 5 s, with a "Next batch in mm:ss"
countdown).

- `services/outbox-relay/`: publishes unpublished `ops.outbox` rows in id order, then sets
  `published_at` (at-least-once; the lake dedupes on the outbox id). `RELAY_SINK=eventhubs`
  (`azure-eventhub`, `DefaultAzureCredential` with `EVENTHUB_NAMESPACE`, or
  `EVENTHUB_CONNECTION_STRING` for the emulator) or `files` (JSON lines in `LANDING_DIR`, used
  in compose).
- `databricks/`: a Databricks Asset Bundle (`databricks.yml`: one job with bronze, silver, gold
  and serving tasks (plus `score`, see ML below) on a single-node job cluster, on a schedule, draining Event Hubs'
  Kafka endpoint with `availableNow`) and the PySpark + Delta code in
  `src/corp_pipelines/`. Tables: `corportal.bronze.events`, `corportal.silver.transactions`,
  `corportal.silver.payments`, `corportal.gold.cash_position_daily`,
  `corportal.gold.payment_features`, `corportal.gold.daily_flows` (Unity Catalog on Databricks; Delta directories under
  `LAKE_DIR` locally). The serving writer replaces each moved company's row in
  `serving.cash_position` with the generator's Available definition, connecting as
  `pipeline_writer`, the database role `db/rls.sql` exempts from row-level security.
- In compose, `pipelines` (`databricks/Dockerfile.local`: Python, OpenJDK 17, PySpark 3.5,
  delta-spark) reads the relay's files from the shared `lake` volume and runs one batch every
  `BATCH_CADENCE_SECONDS` (60 locally, 300 by default). Every batch writes a row to
  `ops.pipeline_runs`, even when nothing was new.

```sh
# approve a payment (above), wait up to 2 batch intervals, then:
curl -s -H 'X-Demo-User: priya' localhost:8088/api/accounts/pipeline/trace/<id>   # 6 stages
docker compose logs -f pipelines
```

Unity Catalog objects the bundle needs come from Terraform (`infra/main/unity_catalog.tf`): the
catalog `corportal` on the lake container (external location without validation, since the lake
is private) and the service credentials `sc-portal-eventhubs` and `sc-portal-sql`, all on the
access connector's user-assigned identity, which db-init adds to `pipeline_writer` in SQL.

Bundle (needs the Databricks CLI and a workspace login; Jenkins deploys it later):
`cd databricks && databricks bundle validate -t dev`. Set the schedule with `batch_schedule`
(Quartz cron) to match `batch_cadence_seconds`.

Pipeline and ML tests need a JVM (and scikit-learn/MLflow) and are skipped without them; run
the whole suite in the pipelines image:

```sh
docker compose build pipelines
docker run --rm -u 0 -e HOME=/home/pipelines -v "$PWD":/src -w /src corportal/pipelines:local \
  sh -c 'pip install -q pytest httpx fastapi "pyjwt[crypto]" && pip install -q --no-deps -e services/common \
         && python -m pytest -q --basetemp=/tmp/pytest'
```

### ML: cash forecast and anomaly detection (piece 4)

Two scikit-learn models, tracked and registered with MLflow, batch-scored into SQL `serving`
and served by `insights-api` (microservice #4). No deep learning, no LLMs, no serving
endpoints. Code: `databricks/src/corp_pipelines/ml/`.

- **Backfill** (`backfill.py`, once): the generator's 90 days of payments and ledger postings
  predate the outbox, so they are appended to bronze as events keyed `seed-<table>-<id>`
  (bronze `source`; the numeric event id is a deterministic negative number), then silver and
  gold run. Re-running adds nothing.
- **Gold features**: `gold.daily_flows` (per company per Gulf day, non-Reserve net flow split
  into other / supplier / payroll / transfer) and `gold.payment_features` (amount, ratio to the
  beneficiary's mean, Gulf hour, weekend flag, first-time beneficiary, same-day duplicates).
- **`cash_forecast`**: the typical daily net flow by company and weekday (mean and SD), then a
  30-day projection of the non-Reserve balance from today's balance, applying known
  `scheduled_payments` and payroll on their dates, with an 80% band. Approving a large payment
  moves the next scoring run's path.
- **`payment_anomaly`**: an Isolation Forest (seeded, every tree sees every payment); score in
  [0, 1], flagged at 0.65, with a one-line reason naming the strongest feature (for example
  `Unusual: 4× this supplier's average`). Flags never block a payment.
- **Train** (manual or daily) logs params, metrics (backtest MAE and band coverage; flag rate)
  and the model to MLflow, registers a new version (alias `champion`) as
  `corportal.ml.cash_forecast` / `corportal.ml.payment_anomaly`, and writes `serving.models`.
  **Score** (every batch after gold) replaces `serving.forecast` and `serving.anomalies`;
  every row carries the model name and version. Without a registered model it skips and
  leaves serving as it is.
- Locally the `pipelines` service backfills and, if the registry is empty, trains at start-up;
  MLflow is a file store in the `lake` volume (`/lake/mlruns`). On Databricks: the
  `corportal-backfill` job (manual), `corportal-ml-train` (manual; daily schedule, paused by
  default) and the `score` task in the medallion job, all on the same single-node cluster
  definition; tracking in the workspace, registry in Unity Catalog (`<catalog>.ml`).

```sh
curl -s -H 'X-Demo-User: priya' localhost:8003/forecast     # 30 days, model cash_forecast vN
curl -s -H 'X-Demo-User: priya' localhost:8003/anomalies    # flagged payments, score + reason
curl -s -H 'X-Demo-User: priya' localhost:8003/models       # name, version, trained_at, metrics
docker compose exec pipelines python -m corp_pipelines.cli train --run-id manual-1   # retrain
```

Generator only: `uv run python data/generator/generate.py --seed 42 --as-of 2026-10-05`.

API tests (SQLite, no SQL Server needed): `uv run pytest -q`.

## CI/CD

Two environments from the same code, on the existing Jenkins VM (architecture 5a–6c). No other
CI, no GitOps controller: Jenkins pushes the deploys.

| | **dev** (branch `develop`) | **prod** (branch `main`) |
|---|---|---|
| Regions | westus2 only | westus3, + northcentralus with `REGION_SECONDARY_ENABLED` |
| Way in | Kong's public IP over HTTPS: `https://corportal-poc01d-primary.westus2.cloudapp.azure.com` (Let's Encrypt via cert-manager) | Front Door Standard → Kong (Kong accepts only our `X-Azure-FDID`) |
| Terraform | `infra/main` + `environments/dev.tfvars`, state `dev.tfstate` | `environments/prod.tfvars`, state `prod.tfstate` |
| Resource groups | `rg-corportal-dev-{primary,data}` | `rg-corportal-{primary,secondary,data}` |
| Helm values | `deploy/helm/values-dev-primary.yaml` | `values-prod-{primary,secondary}.yaml` |

dev runs in its own region so it can be up next to prod (separate vCPU quota).

**Pipelines** (multibranch jobs in the `corportal` folder; branches `main`, `develop`,
`feature/*`; `main` → prod, `develop` → dev, `feature/*` → checks only):

| Job | Jenkinsfile | What it does |
|---|---|---|
| `corportal/infra` | [`ci/Jenkinsfile.infra`](ci/Jenkinsfile.infra) | Tests, Checkov, Terraform plan → **Approve** (`approver`; also for `DESTROY`) → apply, Cluster access, Platform add-ons, `<service>:<env>` image tags, Database (db-init Job), Helm (all services), Databricks bundle |
| `corportal/<service>` ×5 | [`ci/Jenkinsfile.service`](ci/Jenkinsfile.service) (shared; the service is the job's name) | Only when the service's files changed (or started by hand): tests, `az acr build`, Trivy gate, then on `develop`/`main` the moving tag `<service>:<env>` and a rolling `helm upgrade --reuse-values` of that one service |

Image tags: every build is `<service>:<git sha>`; the service pipeline points `<service>:dev` /
`:prod` at it after Trivy. The infra pipeline deploys `global.imageTag=<env>`
(`--reset-then-reuse-values`, so a service its own pipeline deployed keeps its sha tag); an
environment's first deploy seeds missing `<env>` tags from `:latest`.

Parameters (infra): `REGION_SECONDARY_ENABLED` (prod only: region 2 AKS, second Front Door origin,
second Helm deploy), `DESTROY` (plan -destroy → approval → destroy; no deploy), `DEMO_MODE` (Databricks
cadence 30 s; pods move off spot nodes).

Files: `ci/scripts/` (one small script per step), `ci/jenkins/` (job definitions and
`create-jobs.sh`), the chart `deploy/helm/corportal/`. Check the chart locally:

```sh
helm lint deploy/helm/corportal -f deploy/helm/values-dev-primary.yaml
helm template x deploy/helm/corportal -f deploy/helm/values-prod-primary.yaml --set global.frontDoorId=x
```

**Jenkins set-up** (plugins: Pipeline, Pipeline: Multibranch, Git; nothing else, nothing global):

- The VM is an agent labelled `corportal-vm` with `git`, `az`, `terraform`, `uv`, `python3`,
  `helm`, `openssl`, `kubectl` and `kubelogin` (`az aks install-cli`), and the managed identity
  `id-corportal-jenkins` attached (`infra/bootstrap/bootstrap.sh` does this; re-run its
  `az vm identity assign` line if the VM's own Terraform removed it).
- Node environment of `corportal-vm` (never Jenkins global: the Jenkins is shared with
  another project): the `jenkins_env` output of `infra/bootstrap` (`ARM_USE_MSI`,
  `ARM_CLIENT_ID`, `ARM_SUBSCRIPTION_ID`, `ARM_TENANT_ID`), and
  `TF_VAR_aks_admin_group_object_ids` (see below). `JENKINS_PUBLIC_IP` only if neither instance
  metadata nor the VM's outbound address gives the right IP.
- Jobs: `ci/jenkins/create-jobs.sh` (with `.work/jenkins/jenkins.env`) creates `corportal/infra`
  and the five service jobs; `--delete-legacy` removes the old single job `corportal/corportal`.

**First run of an environment:**

1. The subscription Owner has run `infra/bootstrap` (it holds both environments' resource groups) and created
   an Entra group for AKS admins containing `id-corportal-jenkins` (and the owner); its object ID goes
   into `TF_VAR_aks_admin_group_object_ids='["<id>"]'`. `infra/entra/setup.sh` registers both
   environments' URLs as sign-in redirects.
2. Run `corportal/infra` on the environment's branch and approve the plan. It provisions,
   installs the platform, seeds the image tags, initialises the database and deploys everything.
3. From then on a change to a service deploys just that service (its own job).

Saturday (prod): `corportal/infra` on `main` with `REGION_SECONDARY_ENABLED=true`.
Sunday 4 Oct: `DESTROY=true` on `main` and on `develop` (P-9).

### Platform add-ons

The "Platform add-ons" stage (`ci/scripts/platform-addons.sh`, VM agent) installs into every AKS
cluster, from `deploy/platform/`, with the chart versions pinned in
`deploy/platform/versions.env` (same in every region). Re-runs are no-ops. If a step fails, the
build log says which one (`Platform add-ons FAILED: [<region>] <component>`).

- **Kong OSS** (`kong/kong`, namespace `kong`, `kong-values.yaml`): DB-less ingress controller,
  class `kong`, in the mesh. Its proxy is a LoadBalancer on the region's static public IP
  (`kong_public_ips`, the Front Door origin). P-7: the corportal Ingresses match only our
  `X-Azure-FDID`; everything else lands on a catch-all route whose `request-termination` plugin
  answers **403**. A global `rate-limiting` plugin limits each client IP (50/s, 1200/min).
- **HashiCorp Vault** (`hashicorp/vault`, namespace `vault`, `vault-values.yaml`): one standalone
  server, Raft on a 1 Gi PVC, auto-unseal with the Key Vault key `vault-unseal` through the
  workload identity `id-corportal-vault` (Key Vault Crypto User), the Agent injector, never dev
  mode. `ci/scripts/vault-bootstrap.sh` initialises it once with one recovery key share, and puts
  the root token and the recovery key straight into Key Vault (`vault-root-token-<region>`,
  `vault-recovery-key-<region>`); an initialised Vault skips init. It then enables KV v2 at
  `secret/` and Kubernetes auth, writes one policy and role per service account (`accounts-api`,
  `payments-api`, `insights-api`, `outbox-relay`; namespace `corportal`), and seeds
  `secret/corportal/<service>` with `DB_URL` (Entra sign-in as the service's workload identity),
  which the chart's Vault Agent renders to `/vault/secrets/env`.
- **Prometheus and Grafana** (`kube-prometheus-stack`, namespace `monitoring`,
  `monitoring-values.yaml`): slim (no Alertmanager, node exporter or default rules). Prometheus
  scrapes the Istio sidecars' `istio_requests_total`, labelled with the cluster region. Grafana
  has one provisioned dashboard, **Requests per second by region**
  (`dashboards/rps-by-region.json`), and runs in region 1 only. With `REGION_SECONDARY_ENABLED`,
  region 2's Prometheus sits behind an internal load balancer and the primary Prometheus
  federates it over the VNet peering, so the dashboard shows both regions. kube-state-metrics
  and the kubelet's cAdvisor give pod and container data (phase, restarts, ready, OOMKilled,
  requests and limits, CPU and memory use), labelled `region`; the primary federates region 2's
  copy too.
- **Prometheus API** (prod only, `prometheus-api.yaml`): `https://<Front Door endpoint>/prometheus/...`
  through Kong, GET only, with our `X-Azure-FDID` and an API key in the `apikey` header (Kong
  key-auth). Front Door is active-passive, so this is the primary's Prometheus. The key lives
  in `.work/secrets/prometheus-api-key` (git-ignored) and in the Jenkins credential
  `corportal-prometheus-api-key` (Secret text, `corportal` folder, never global); prod's
  Platform add-ons stage fails without it.

Nothing is public except Kong's proxy (and, behind it in prod, the keyed Prometheus API):

```sh
curl -s -H "apikey: $(cat .work/secrets/prometheus-api-key)" \
  "https://<Front Door endpoint>/prometheus/api/v1/query?query=kube_pod_status_phase"
```

Reach Grafana with a port-forward (user `admin`, password
in Key Vault as `grafana-admin-password`; Key Vault only admits the Jenkins VM's IP, so read it
there or through the Azure portal from an allowed network):

```sh
az keyvault secret show --vault-name kv-corportal-<suffix> --name grafana-admin-password --query value -o tsv
kubectl --kubeconfig .kube/primary -n monitoring port-forward svc/monitoring-grafana 3000:80
# http://localhost:3000 -> corportal / Requests per second by region
```

**Deviation from stack.md ("Kong validating Entra tokens"):** Kong OSS has no OpenID Connect
plugin (it is Enterprise-only) and Kong Enterprise is out of scope. Kong enforces the Front Door
check and rate limits; Entra token validation stays in the services (`corp_common.auth`), which
already reject any request without a valid token.

Offline checks (no cluster): pull the pinned charts into `.work/charts`, then the smoke tests in
`tests/test_helm_chart.py` render them with our values (they skip if the charts are missing):

```sh
set -a; . deploy/platform/versions.env; set +a
helm repo add kong "$KONG_CHART_REPO"; helm repo add hashicorp "$VAULT_CHART_REPO"
helm repo add prometheus-community "$MONITORING_CHART_REPO"; helm repo update
mkdir -p .work/charts
helm pull "$KONG_CHART" --version "$KONG_CHART_VERSION" --untar -d .work/charts
helm pull "$VAULT_CHART" --version "$VAULT_CHART_VERSION" --untar -d .work/charts
helm pull "$MONITORING_CHART" --version "$MONITORING_CHART_VERSION" --untar -d .work/charts
uv run pytest -q tests/test_helm_chart.py
```

## Infrastructure

Terraform only (architecture 5d), in two parts:

- `infra/bootstrap/`: run once by the owner (subscription Owner) from a laptop, local state. Creates what
  Jenkins may not create for itself: the resource groups `rg-corportal-{primary,secondary,data}`,
  Jenkins' managed identity `id-corportal-jenkins` (Contributor on those groups, plus role
  assignments limited to an allowed-roles list), AcrPush on `exampleacr`, the state container
  `corportal` and the provider registrations. Its outputs `jenkins_env` and `backend_config` go
  into Jenkins.
- `infra/main/`: the platform, applied **only by Jenkins** (P-2), state
  `stexampletfstate/corportal/main.tfstate`. It uses the bootstrap resource groups as data sources
  and never creates resource groups. Modules:
  - `network`: a VNet per region; AKS subnet (NSG: web traffic only from Front Door), and in
    region 1 the private endpoint subnet and the two Databricks subnets with a NAT gateway.
  - `data`: ADLS Gen2, Event Hubs Standard (1 TU, `portal-events`), Key Vault (RBAC), Azure SQL
    Basic with an Entra-only admin; public access off, private endpoints and private DNS zones
    for all four (P-5); no shared keys or local auth (P-3). Key Vault also holds Vault's
    auto-unseal key `vault-unseal`; its firewall denies everything except the Jenkins VM's
    public IP (`jenkins_public_ip`), so Jenkins can write the key and Vault's init secrets
    (Key Vault Secrets Officer), while the workloads use the private endpoint.
  - `aks`: node auto-provisioning, CNI Overlay + Cilium, managed Istio, OIDC issuer and workload
    identity, one B2s system node, Entra admin groups with local accounts off, API server
    limited to the Jenkins VM, AcrPull for its kubelet identity, and Kong's static public IP.
  - `databricks`: Premium, VNet-injected, no public IP, Access Connector with Storage Blob Data
    Contributor on ADLS and Event Hubs Data Receiver. No clusters (the bundle's job clusters).
  - `edge`: Front Door Standard, one origin per region (Kong), priority order.
  - `identity`: a workload identity per service and one for Vault, federated to each cluster.
  - Tags on everything: `application`, `costCentre`, `dataClassification`, `environment`,
    `owner`, `destroyBy` (P-9). Regions are variables (P-11).

Variables Jenkins supplies: `secondary_region_enabled` (the `REGION_SECONDARY_ENABLED`
parameter), `jenkins_public_ip` (instance metadata or `JENKINS_PUBLIC_IP`), and
`aks_admin_group_object_ids` (`TF_VAR_aks_admin_group_object_ids`). Optional, as `TF_VAR_*` in
Jenkins' environment:
`enable_sql_failover` (the failover dry run: S0 tier, a server in region 2, a failover group;
`sql_fqdn` becomes the listener), `databricks_metastore_id` (assign a Unity Catalog metastore;
needs account-admin rights), `name_suffix` (globally unique names), `extra_authorized_ip_ranges`.

Offline checks (no Azure credentials; nothing here ever runs `plan` or `apply` against Azure):

```sh
terraform fmt -check -recursive infra/
terraform -chdir=infra/main init -backend=false
terraform -chdir=infra/main validate
terraform -chdir=infra/main test          # mocked providers: 6 runs
uvx checkov -d infra/main --soft-fail --compact
```

Lifecycle: bootstrap (the owner) → Jenkins runs per environment (see CI/CD) → Saturday `REGION_SECONDARY_ENABLED=true`
→ Sunday 4 Oct `DESTROY=true` (plan -destroy, the owner approves, destroy). The bootstrap is destroyed
last, by the owner.
