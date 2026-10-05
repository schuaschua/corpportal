# Azure: corportal

The Azure answers for [architecture.md](architecture.md). Principle numbers continue the shared sequence.

## Context

| # | Question | Answer | Source |
| --- | --- | --- | --- |
| 1c | Service model | PaaS: Azure SQL, Event Hubs Standard, ADLS Gen2, Azure Databricks Premium, Front Door Standard, Key Vault, Entra External ID; containers: AKS with Node Auto Provisioning | stack.md |
| 1d | Regions and availability | West US 3 (primary), North Central US (secondary, demo day only); single zone | SPEC.md §Constraints |
| 2d | Naming and tags | `<type>-corportal-<purpose>` (for example `rg-corportal-data`, `id-corportal-jenkins`); tags: application, costCentre, dataClassification, environment, owner, destroyBy | infra/bootstrap/variables.tf |
| 3d | Approved stack | AKS, Azure SQL, ADLS Gen2, Event Hubs, Azure Databricks, Front Door, Key Vault; Kong OSS, managed Istio add-on, HashiCorp Vault, Prometheus, Grafana in-cluster | stack.md |
| 4a | AI platform | Azure Databricks (MLflow, Unity Catalog) | SPEC.md CAP-7 |
| 5b | Deploy targets | AKS (Helm), Azure Databricks (Asset Bundles) | Da Vinci's pick, confirmed by the owner, 2026-09-30 |
| 6c | Pipeline identity and secret store | user-assigned managed identity `id-corportal-jenkins` on the Jenkins VM, scoped to the corportal resource groups; Key Vault and HashiCorp Vault | infra/bootstrap/main.tf |

## Principles

### P-5 Private data plane
- **Rule:** ADLS, Azure SQL, Key Vault and Event Hubs must be reachable only through private endpoints. The container registry (`exampleacr`, Basic) is the one accepted exception.
- **Why:** A visible network control for the client. Pillar: security.
- **Source:** SPEC.md §Constraints; the owner accepted the registry exception, 2026-09-30.
- **Applies to:** those four services.

### P-7 Front Door only ingress
- **Rule:** Cluster ingress must accept only requests carrying our Front Door's `X-Azure-FDID`.
- **Why:** No direct path to the clusters. Pillar: security.
- **Source:** SPEC.md CAP-14; stack.md §Edge.
- **Applies to:** Kong ingress in every region.

### P-10 Managed service first
- **Rule:** Use an Azure managed service unless an AD shows why none fits.
- **Why:** Less to run for a team of two. Pillar: operational excellence.
- **Source:** 1c.
- **Applies to:** every new component.

### P-11 US regions as a cost trade-off
- **Rule:** The PoC must run in West US 3 and North Central US. Region names must stay variables, so that a real rollout can move to UAE North and UAE Central with no code change.
- **Why:** These are the cheapest regions for the node sizes used, and the synthetic data carries no residency duty under the CBUAE guidance. Pillar: cost optimization.
- **Source:** the owner, 2026-09-30: "we will explain that it's a cost trade-off but can be easily changed".
- **Applies to:** all Terraform and configuration.

## Open questions
- None.

## Changes
| Date | Item | Change | Why |
| --- | --- | --- | --- |
| 2026-09-30 | All | First version | Agreed with the owner |
