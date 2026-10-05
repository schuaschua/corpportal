# Demo Script — Five Acts

Every build item must belong to an act. Anything not in an act is not built.

| Act | Shows | Capabilities |
|---|---|---|
| 1. Platform | Jenkins runs Terraform, and the parallel microservice build runs. Jenkins' identity is denied outside its resource groups. | CAP-10, CAP-11 |
| 2. Treasurer | A Northwind Logistics treasurer signs in and views the dashboard and accounts. They create a payment, and a second user approves it. | CAP-1, CAP-2, CAP-3, CAP-4 |
| 3. Behind the scenes | The payment moves bronze ✓ → silver ✓ → gold ✓. The dashboard updates. Unity Catalog lineage is shown. | CAP-5, CAP-6 |
| 4. Intelligence | The forecast shifts after the payment, and the planted anomalies are flagged. | CAP-7, CAP-8, CAP-9 |
| 5. Resilience & security | The region-1 ingress is deleted. The badge changes from West US 3 to North Central US, and Grafana requests per second shift to region 2. A cross-company access attempt is blocked. The mTLS, Front Door-only ingress and Vault controls are shown. | CAP-12, CAP-14 |

- Story device: Northwind Logistics has payroll due Thursday, a late client invoice and an unexpected cash dip.
- Demo day: batch cadence is set to 30 s. Run the Databricks streaming job with an availableNow or 30 s trigger. Use regular (non-spot) nodes.
- Failover step: delete the ingress only. A full `terraform destroy` of the region takes 5–10 minutes, which is too slow to show.
- SQL data failover (CAP-13) is proven in the Saturday-night dry run, not in the live acts.
