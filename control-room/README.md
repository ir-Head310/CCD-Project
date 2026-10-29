# Flash Sale Control Room

A traffic slider plus a live 3D view of the cluster. Push the slider and watch requests stream out of the load
balancer, pods fill up, the HPA add pods, Pending pods wait for room, and the cluster autoscaler add a node. Pull it
back to watch everything scale in.

```
python control-room/server.py                              # SIMULATION: no cloud, free
python control-room/server.py --speed 4                    # simulation at 4x speed, for rehearsing
python control-room/server.py --live --host http://<IP>    # LIVE: real traffic against AKS
```

The control room opens at http://localhost:8090. It needs `pip install -r control-room/requirements.txt`, and an
internet connection to load three.js from the jsDelivr CDN.

## What you see

| In the scene | Meaning |
|---|---|
| Glowing ring at the front | The Azure load balancer |
| Particles | Requests. Their rate tracks real req/s, and each one flies to the pod that served it |
| Platforms | AKS nodes. An amber, pulsing outline means the node is Provisioning or NotReady |
| Glass cylinders | Product Service pods. **Liquid level = that pod's req/s against its ~200 req/s capacity** (green → amber → red) |
| Amber wireframe pods floating at the back | **Pending** pods: wanted by the HPA, but no node has room |
| Dimming red-ringed pods | Terminating (scale-in) |
| Red particles falling short | Failed requests |

The right panel shows throughput, p95 latency, pods ready vs wanted, nodes, availability, and the HPA's CPU figure
against its 60% target. The event log records every scale-out, scale-in and node change.

## Modes

**Live** (`--live`) runs Locust inside the server, using the same `FlashSaleShopper` as `loadtest/locustfile.py`,
which reconnects every 10 requests. It reads pods, nodes and the HPA with `kubectl` every 2 s, so run
`az aks get-credentials` first.
- **Liquid level is live** (updated every second). It comes from the `X-Served-By` header on each response.
- **Pod CPU is not.** The HPA's CPU figure comes from metrics-server, which AKS refreshes only about once a minute.
- **If kubectl can't reach a cluster,** the page says so and shows only the responders it can see. That is useful for
  testing against `python app/app.py` locally.

**Simulation** (the default) is a **model** for practising, building and demo backup. It is labelled SIMULATION on
screen and must not be presented as measured results. Its constants are calibrated to the real run on 2026-10-28;
see the docstring in `sim.py`. On the same flash-sale shape it reproduces run2 closely:

| | Simulator | Real run2 |
|---|---|---|
| First scale-out | 120 s | 154 s |
| Pods Pending, waiting for a node | 180 s | 210 s |
| New node registered | 275 s | 296 s |
| All pods Ready | 345 s | 366–373 s |
| Peak pods | 6 | 7 |
| Back to 2 pods | 600 s | 624 s |

## Demo script (live)

1. `terraform apply`, update `AZURE_CLIENT_ID` in GitHub, push or re-run the workflow, then `az aks get-credentials`.
2. Run `python control-room/server.py --live --host http://<EXTERNAL-IP>`.
3. Click **Normal day** (5 shoppers): 2 calm green pods.
4. Click **⚡ Flash sale** (300): the pods go red, the HPA scales out within about 1–2 min, 3 pods hang Pending, and
   a node boots. After about 3 min the new pods take traffic and everything turns green.
5. Click **Normal day** again: after the 2-minute stabilisation window the pods drain and disappear. The empty node
   is removed about 10 min later.
6. Optionally open `http://<EXTERNAL-IP>/shop` in another window to show the shopper's view.
