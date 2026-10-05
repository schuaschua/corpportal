# Stack

## Azure layout
- One subscription with resource groups `rg-portal-primary`, `rg-portal-secondary` (Saturday only) and `rg-data`.
- Jenkins VM (existing) uses a managed identity scoped to those resource groups. It authenticates by workload identity or managed identity, with no service principal secrets.
- Existing container registry.

## Compute
- AKS with Node Auto Provisioning (Karpenter), which requires Azure CNI Overlay with Cilium. One regular system node, plus spot nodes for services during development. One replica per service.
- Region 2: the same Terraform module applied to North Central US, on Saturday only.
- In the cluster:
  - Kong OSS as the API gateway (ingress), validating Entra tokens.
  - Managed Istio add-on with mTLS STRICT.
  - HashiCorp Vault for app secrets, with Key Vault holding its auto-unseal key and root credentials.
  - Prometheus and Grafana.
- CI: Jenkins Kubernetes plugin creates one agent pod per service, and Kaniko builds the images.

## Edge
- Front Door Standard (Saturday only), with an origin per region and health probes.
- Ingress accepts only requests whose `X-Azure-FDID` header matches our Front Door.

## Data
- Azure SQL:
  - Operational ledger, including payment approval state and an outbox table.
  - A `serving` schema holding gold copies for the portal.
  - Basic tier during development.
  - `enable_sql_failover` flag: upgrades the tier and adds a server in region 2 plus a failover group.
- Services use a configurable SQL host (the failover group listener on Saturday).
- Outbox relay worker → Event Hubs Standard (1 TU, 7-day retention).
- Databricks Premium:
  - VNet-injected with a NAT gateway.
  - Unity Catalog, with an Access Connector managed identity to ADLS.
  - Reads Event Hubs over the Kafka endpoint.
- Medallion: ADLS Gen2, Delta tables, bronze → silver → gold, then gold is written to the SQL `serving` schema.
- ML:
  - Time-series cash forecast per company.
  - Isolation Forest anomaly detection on payments.
  - Batch scoring into `forecasts` and `anomalies` tables.
  - Tracked in MLflow and registered in Unity Catalog.
- Jobs deployed from Jenkins with Databricks Asset Bundles.
- Private endpoints: ADLS, SQL, Key Vault and Event Hubs, each with a private DNS zone.

## Databricks development pattern
- Develop PySpark and the models locally against the synthetic data.
- Batch all Databricks-dependent stories into one integration window: Event Hubs read, lineage, MLflow and SQL write.
- Cluster policy: single node, smallest VM, auto-stop after 10 minutes.
- Development runs are on demand (availableNow drains the Event Hubs backlog). Streaming is used on demo day only.

## Portal
- Fluent UI with five screens: Login, Dashboard, Accounts, Payments (with approval), Forecast.
- A "Serving from: <region>" badge and a behind-the-scenes stage panel.
- Entra External ID sign-in. Company isolation is enforced by row-level security in SQL.
