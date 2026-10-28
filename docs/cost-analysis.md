# Cost analysis

All prices are **approximate pay-as-you-go list prices (USD, late 2025/2026) and need checking** in the
[Azure Pricing Calculator](https://azure.microsoft.com/pricing/calculator/) for your region before you quote them in
the report. Prices change, and Central India differs slightly from US regions.

## 1. What this demo costs to run

| Resource                         | Unit price (approx.)          | Per hour (2 nodes) |
|----------------------------------|-------------------------------|--------------------|
| AKS control plane, Free tier     | $0                            | $0.000             |
| 2 × Standard_B2s nodes           | ~$0.046 /h each               | $0.092             |
| 2 × 30 GB OS managed disks       | ~$2.4 /month each             | $0.007             |
| Standard Load Balancer (≤5 rules)| ~$0.025 /h                    | $0.025             |
| Standard public IP               | ~$0.005 /h                    | $0.005             |
| ACR Basic                        | ~$0.167 /day                  | $0.007             |
| Log Analytics ingestion          | ~$2.3–2.8 /GB (capped at 1 GB/day) | ~$0.00–0.01  |
| **Total**                        |                               | **≈ $0.14 /h ≈ $3.3 /day** |

A 12-minute load-test session, including about an hour of setup and teardown, costs well under $1. The $100 Azure for
Students credit covers the whole project as long as you run `terraform destroy` between sessions.

**For comparison, the same setup on AWS:** EKS control plane $0.10/h + 2 × t3.medium about $0.083/h + a NAT gateway
about $0.045/h (needed for private node subnets) + ELB about $0.025/h, so roughly **$0.25/h**. That is close to double,
and the EKS fee is charged even when no pods are running. This is why the project moved to Azure.

## 2. Fixed-capacity vs. autoscaling (theoretical)

Model a store whose baseline traffic needs **B** nodes, while flash sales need **P** nodes for **H** hours a year.
Node price is **c** $/h, and a year has 8,760 h.

- Fixed capacity sized for the peak: `P × 8760 × c`
- Autoscaling: `B × 8760 × c + (P − B) × H × c`
- Saving: `1 − [B × 8760 + (P − B) × H] / (P × 8760)`

**Worked example:** B = 2 nodes, P = 20 nodes (a 10× surge in compute), 10 sale days × 6 h = 60 h/year,
c = $0.046/h.

| Strategy                      | Calculation                                   | Annual cost |
|-------------------------------|-----------------------------------------------|-------------|
| Fixed for peak                | 20 × 8760 × 0.046                             | **$8,059**  |
| Fixed for baseline            | 2 × 8760 × 0.046 — outage during every sale   | $806        |
| Autoscaling (HPA + node autoscaler) | 2 × 8760 × 0.046 + 18 × 60 × 0.046      | **$856**    |

Autoscaling costs about **89% less** than provisioning for the peak. It also keeps the peak capacity that a
baseline-sized fleet lacks. The saving grows as the surge ratio P/B grows and as sale hours H shrink. Under this
model, autoscaling stays cheaper as long as H < 8,760 h, i.e. unless the "peak" lasts all year.

**Caveats to discuss in the report:**

- Scale-out is not instant. The HPA reacts in seconds, but a new node takes ~1–3 min. Real platforms pre-scale before
  a sale they know about, or keep a buffer, and either adds cost to the autoscaling line. Use the measured
  scale-out times from `analysis/plot_results.py` to justify the size of that buffer.
- Reserved or savings-plan pricing makes baseline capacity cheaper. The comparison gets stronger if the baseline is
  reserved and only the surge is pay-as-you-go.
- Per-pod CPU requests drive packing efficiency. Lower requests fit more pods per node but give the HPA a noisier
  signal.

## 3. Actual billing

After each session, open **Cost Management → Cost analysis** and filter on the resource group `rg-flashsale-*`. Group
by *Service name* to put measured spend next to the estimate in §1.
