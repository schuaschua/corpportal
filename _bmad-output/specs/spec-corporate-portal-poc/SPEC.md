---
id: SPEC-corporate-portal-poc
companions:
  - demo-script.md
  - stack.md
  - cost-budget.md
  - architecture-diagrams.md
  - ../../planning-artifacts/ux-designs/ux-corportal-2026-09-30/DESIGN.md
  - ../../planning-artifacts/ux-designs/ux-corportal-2026-09-30/EXPERIENCE.md
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Corporate Portal PoC — Standalone Digital Bank

## Why

A mandate plus an opportunity: we must show a client, whose Head of AI & Data is strong, that we can build a B2B corporate banking portal on Azure. It has to use an Azure Data Lake medallion architecture and ML, include enterprise-grade security and multi-region resilience, and be spun up fast from Terraform. It is a showcase, not a product. It needs to work and look credible in a live demo, built by two people (the owner + Claude) by Saturday night.

## Capabilities

- **CAP-1**
  - **intent:** Users of a fake business sign in and see only their own company's data.
  - **success:** A Northwind user signs in through Entra and sees only Northwind accounts. A request for another company's data is blocked and logged.
- **CAP-2**
  - **intent:** A treasurer sees the company's cash position and liquidity at a glance.
  - **success:** The dashboard shows totals and a liquidity trend read from the serving layer, loading in under 2 s.
- **CAP-3**
  - **intent:** A treasurer browses accounts, balances and transactions.
  - **success:** The accounts screen lists every account for the company with its balance and recent transactions.
- **CAP-4**
  - **intent:** A treasurer creates a payment and a second user approves it.
  - **success:** A payment moves from created, to approved (by a different user), to executed in the operational ledger. The balance changes, and self-approval is refused.
- **CAP-5**
  - **intent:** A payment event visibly travels through the lake layers.
  - **success:** After approval, a "behind the scenes" panel shows bronze ✓, silver ✓ and gold ✓, and the dashboard figure updates within one batch interval.
- **CAP-6**
  - **intent:** The Head of AI & Data can trace a dashboard figure back to its raw events.
  - **success:** Unity Catalog lineage shows the path from the gold table through silver and bronze to the Event Hubs source for a displayed position.
- **CAP-7**
  - **intent:** A treasurer sees an ML cash forecast for their company.
  - **success:** The forecast screen shows a forward balance projection from a model tracked in MLflow and registered in Unity Catalog. Approving a large payment changes the next forecast.
- **CAP-8**
  - **intent:** Unusual payments are flagged automatically.
  - **success:** The anomaly model flags all 3 planted anomalies in the synthetic data, and they appear in the portal.
- **CAP-9**
  - **intent:** A believable synthetic world drives every screen.
  - **success:** 8 fake UAE businesses (LLCs, with AED accounts and UAE IBANs) with payroll cycles, suppliers, seasonality and 3 planted anomalies are generated reproducibly from a seed.
- **CAP-10**
  - **intent:** The whole platform is provisioned from Jenkins with Terraform, using least-privilege identity.
  - **success:** A Jenkins job creates the environment with no stored secrets, and its identity is denied when it tries to act outside its resource groups.
- **CAP-11**
  - **intent:** Microservices are built and published in parallel by Jenkins.
  - **success:** One pipeline run builds every service image on Kubernetes agents and pushes it to the existing container registry.
- **CAP-12**
  - **intent:** The portal survives the loss of its primary region's compute.
  - **success:** When the region-1 ingress is deleted, Front Door serves the portal from region 2 within about 1 minute. The region badge and the Grafana requests-per-second-by-region panel both show the switch, and the user's data is still there.
- **CAP-13**
  - **intent:** The database can fail over across regions.
  - **success:** On the Saturday-night dry run, one Terraform flag creates the failover group. A forced failover leaves the portal working, and the flag then removes it.
- **CAP-14**
  - **intent:** The security controls can be demonstrated.
  - **success:** The demo can show each of these:
    - mTLS STRICT between services.
    - Kong rejecting invalid tokens.
    - Secrets served from Vault and Key Vault, with none in the repo.
    - Private endpoints on the lake, SQL, Key Vault and Event Hubs.
    - Ingress rejecting traffic that doesn't come from our Front Door.
- **CAP-15**
  - **intent:** Nothing keeps costing money after the PoC.
  - **success:** `terraform destroy` removes every created resource. The Databricks cluster policy makes it impossible to run a cluster without auto-stop.

## Constraints

- Deadline is Saturday 3 Oct 2026, night. Only the owner and Claude are building it.
- Synthetic data only. It will never go to production.
- All money is in UAE dirham (AED). There is no multi-currency support.
- Azure, one subscription, split into resource groups. No management groups.
- ADLS Gen2 with a bronze/silver/gold medallion and Databricks (Premium, VNet-injected, Unity Catalog) are mandatory. They are the point of the demo.
- Writes go to Azure SQL, then through an outbox to Event Hubs Standard and into the lake. The portal reads from a `serving` schema in the same Azure SQL.
- Services are stateless. The SQL hostname and the batch cadence are configuration values, not code.
- Spend is about US$45–60 from Wednesday to Saturday. That rules out:
  - always-on Databricks,
  - a second region before Saturday,
  - Front Door Premium,
  - a Databricks SQL warehouse or model-serving endpoints,
  - a separate DevOps cluster.
  See `cost-budget.md`.
- Regions: West US 3 (primary) and North Central US (secondary, Saturday only). They're the cheapest for AKS nodes.
- Existing assets: Jenkins VM `jenkins-vm` (Southeast Asia, B2s), registry `exampleacr` (Basic, so no private endpoint) and Terraform state in `stexampletfstate`, container `corportal`. Jenkins gets its own new identity; it doesn't reuse another project's identities.
- No secrets in code or the repo. Use managed or workload identities, and no storage account keys.
- Code quality doesn't matter, Terraform included. The UI is minimal: Fluent UI with five screens.

## Non-goals

- Production readiness, automated test suites and code quality.
- Multi-bank aggregation, open banking to other banks, or any competitive differentiation.
- Integration with legacy systems.
- Real customer data, consent, PSD2 or PCI compliance.
- Azure API Management, Purview, Microsoft Fabric, Databricks serverless and management-group landing zones.
- Real-time streaming during development. Micro-batching is fine.
- Data failover in the live demo. SQL failover is proven only in the Saturday dry run.

## Success signal

- By Saturday night, the owner runs all five demo acts end to end twice without intervention. That includes the region-1 ingress deletion, after which the portal keeps serving from region 2, and a successful SQL failover dry run. Everything is destroyed on Sunday 4 Oct, with spend of about US$60 or less.

## Assumptions

- "Only one run instance at a time" means one replica per service.
- Fake business users sign in with Entra External ID.
- The HashiCorp Vault Community licence (BSL) counts as "free".
- A 4th private endpoint on Event Hubs is included.
- Bank name "Contoso Digital Bank". Users: Priya Nair (Treasurer) and Tom Okafor (CFO, approver). There is a PoC-only user switcher.

## Open Questions

- When is the actual client demo? Is the environment rebuilt from Terraform for it after the Sunday destroy?
- Vault, Prometheus and Grafana now run in the region-1 AKS cluster. If only the ingress is deleted they stay up, but if the whole cluster were lost, region 2 would lose its secrets. Is that acceptable?
- What are the microservice boundaries?
- What does "self-service" from the original portal list cover?
- Does SQL Basic support geo-replication and failover groups? This needs checking before Saturday.
