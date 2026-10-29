# Load-test results (2026-10-28)

Setup: AKS in `indiasouthcentral`, Standard_B2s nodes (cluster autoscaler 1–2), HPA 2–10 pods at 60% CPU of a 200m
request, `WORK_ITERATIONS=3000`. Load came from Locust on a laptop in Manipal running the 12-minute flash-sale shape
(5 → 300 users at ~1 req/s each → hold → 5). Raw CSVs and figures are in `results/` (git-ignored). Regenerate them with
`analysis/plot_results.py`.

| Metric                                  | run1 (persistent connections) | run2 (reconnect every 10 requests) |
|-----------------------------------------|-------------------------------|------------------------------------|
| Requests / failures                     | 86,395 / 0                    | 86,247 / 4                         |
| Availability                            | 100.000 %                     | 99.995 %                           |
| Peak throughput                         | 305 req/s                     | 304 req/s                          |
| p50 / p95 latency at peak (mean)        | 164 / 252 ms                  | 139 / 262 ms                       |
| Load spike → HPA first scales out       | 73 s                          | 70 s                               |
| Load spike → first new pod Ready        | 82 s                          | 75 s                               |
| Peak pods (nodes)                       | 6 (2)                         | 7 (2)                              |
| Pods Pending → new node joins           | ~90 s                         | ~86 s                              |
| HPA asks for pods → all Ready           | ~180 s                        | ~163 s                             |
| Load drop → back to 2 pods              | 177 s                         | 206 s                              |
| Pods that served traffic                | **2 of 6**                    | **7 of 7**                         |

## Findings

1. **Scale-out and scale-in happen without manual action.** The HPA added pods while CPU was above target. When the
   pods no longer fit, the cluster autoscaler added a node. Both scaled back after the 2-minute stabilisation window.
2. **The load balancer balances per connection, not per request.** In run1, every Locust user held one keep-alive
   connection opened before scale-out, so the 4 new pods received **no** traffic and CPU stayed above target on the 2
   original pods. In run2, users reconnected every ~10 s, as real shoppers come and go, and every pod served traffic.
   With long-lived clients, a layer-7 load balancer (ingress controller or Azure Application Gateway) would be needed
   to spread requests evenly.
3. **Capacity lags demand by 2–4 minutes.** AKS metrics-server reports CPU about once a minute (the step shape in the
   CPU panel). The HPA therefore first reacted about 70 s into the ramp. A new node took about 90 s, and the pods on it
   took another ~70 s, so the extra pods were ready only as the sale traffic was ending. For a scheduled flash sale,
   capacity should be pre-scaled (raise `minReplicas` before the event) rather than left to reactive scaling alone.
4. **Run2 had 4 failures, all `RemoteDisconnected`.** Three happened at about t = 300 s, the moment node 2 joined the
   cluster and its load-balancer backend pool. One happened at t ≈ 564 s, as pods were being removed during scale-in. The
   scale-in failure fits a known keep-alive race: a terminating pod closes idle connections while a client is reusing
   one. Making the `preStop` sleep longer than the client reconnect interval should remove it, so it has since been
   raised from 5 s to 15 s (`k8s/10-deployment.yaml`); this is not yet verified by a new run. The node-join cause is
   likely but not confirmed, and the preStop change does not address it.
