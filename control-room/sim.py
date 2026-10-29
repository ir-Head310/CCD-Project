"""Simulated AKS cluster for the control room: no cloud, no cost.

This is a *model*, not a measurement. Its constants come from the real runs on
2026-10-28 (docs/results.md, run2) so that it behaves like the real cluster did:

  * ~2.5 millicore-seconds of CPU per request (≈750m total at 300 req/s)
  * metrics-server publishes CPU about once a minute on AKS
  * HPA: 60% target, 2-10 pods, scale-up max(2x, +4)/15 s, scale-down window 120 s, -50%/30 s
  * first node fits 3 product pods; a new node fits 4
  * cluster autoscaler: ~85 s until the new node registers, ~20 s more until Ready,
    ~50 s image pull for the first pod on a fresh node
"""
import math
import random
import string
import threading
import time
from collections import deque

POD_CPU_REQUEST_M = 200
POD_CPU_LIMIT_M = 500
CPU_PER_REQUEST_MS = 2.5
BASE_CPU_M = 1
POD_CAPACITY_RPS = (POD_CPU_LIMIT_M - BASE_CPU_M) / CPU_PER_REQUEST_MS  # ~200 req/s per pod

HPA_TARGET_PCT = 60
HPA_MIN, HPA_MAX = 2, 10
HPA_PERIOD_S = 15
HPA_TOLERANCE = 0.1
METRICS_PERIOD_S = 60      # how often a new CPU figure is published
CPU_WINDOW_S = 30          # each figure averages the last ~30 s of usage
SCALE_DOWN_WINDOW_S = 120
SCALE_DOWN_PERIOD_S = 30

FIRST_NODE_SLOTS = 3
NODE_SLOTS = 4
MAX_NODES = 2
POD_START_S = 8
IMAGE_PULL_S = 50
CA_TRIGGER_S = 10
NODE_REGISTER_S = 85
NODE_READY_S = 20
NODE_UNNEEDED_S = 600
NODE_REMOVE_S = 15
POD_TERMINATE_S = 6

SPAWN_RATE = 10            # Locust users added/removed per second
RECONNECT_RAMP_S = 10      # users reconnect every ~10 requests, so new pods ramp up over ~10 s
NETWORK_MS = 100           # laptop <-> Hyderabad round trip seen in the real runs

REPLICASET = "product-service-59466b7c74"


def _suffix():
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=5))


class SimCluster:
    mode = "sim"

    def __init__(self, speed=1.0):
        self.speed = speed
        self.lock = threading.Lock()
        self.t = 0.0
        self.target_users = 0
        self.users = 0.0
        self.nodes = [self._node("aks-system-19526036-vmss000000", "Ready", slots=FIRST_NODE_SLOTS, pulled=True)]
        self.pods = []
        for _ in range(HPA_MIN):
            pod = self._pod()
            pod.update(phase="Running", node=self.nodes[0]["name"], ready_t=-100.0)
            self.pods.append(pod)
        self.replicas = HPA_MIN
        self.metric_cpu_pct = 0
        self.metric_t = 0.0
        self.cpu_samples = deque()
        self.next_metrics_t = METRICS_PERIOD_S
        self.next_hpa_t = HPA_PERIOD_S
        self.recommendations = deque()
        self.last_scale_down_t = -1e9
        self.rps = 0.0
        self.fail_rps = 0.0
        self.p95 = 0.0
        self.total = 0.0
        self.failures = 0.0
        threading.Thread(target=self._loop, daemon=True).start()

    # --- object factories ------------------------------------------------------
    def _node(self, name, status, slots=NODE_SLOTS, pulled=False):
        return {"name": name, "status": status, "slots": slots, "pulled_at": 0.0 if pulled else None,
                "status_until": None, "unneeded_since": None}

    def _pod(self):
        return {"name": f"{REPLICASET}-{_suffix()}", "phase": "Pending", "node": None, "created_t": self.t,
                "ready_at": None, "ready_t": None, "end_t": None, "rps": 0.0, "cpu_m": 0.0}

    # --- control ---------------------------------------------------------------
    def set_users(self, n):
        with self.lock:
            self.target_users = max(0, int(n))

    def _loop(self):
        step = 0.25
        while True:
            time.sleep(step)
            with self.lock:
                self._tick(step * self.speed)

    # --- simulation ------------------------------------------------------------
    def _tick(self, dt):
        self.t += dt
        t = self.t
        delta = self.target_users - self.users
        self.users += max(-SPAWN_RATE * dt, min(SPAWN_RATE * dt, delta))

        self._traffic(dt)
        self._metrics()
        self._hpa()
        self._reconcile()
        self._schedule()
        self._cluster_autoscaler()

        for pod in self.pods:
            if pod["phase"] == "Starting" and t >= pod["ready_at"]:
                pod.update(phase="Running", ready_t=t)
        self.pods = [p for p in self.pods if not (p["phase"] == "Terminating" and t >= p["end_t"])]

    def _traffic(self, dt):
        offered = self.users  # constant_throughput(1): one request per user per second
        running = [p for p in self.pods if p["phase"] == "Running"]
        weights = [min(1.0, max(0.05, (self.t - p["ready_t"]) / RECONNECT_RAMP_S)) for p in running]
        total_w = sum(weights) or 1.0
        lat_weighted = []
        served_total = fail_total = 0.0
        for pod in self.pods:
            pod["rps"] = 0.0
            pod["cpu_m"] = BASE_CPU_M if pod["phase"] in ("Running", "Terminating") else 0.0
        for pod, w in zip(running, weights):
            share = offered * w / total_w * random.uniform(0.93, 1.07)
            served = min(share, POD_CAPACITY_RPS)
            util = served / POD_CAPACITY_RPS
            latency = NETWORK_MS + 10 + 40 * util / (1 - min(util, 0.97))
            if share > POD_CAPACITY_RPS:
                latency = 2000 + 3000 * (share / POD_CAPACITY_RPS - 1)
            pod["rps"] = served
            pod["cpu_m"] = BASE_CPU_M + served * CPU_PER_REQUEST_MS
            served_total += served
            fail_total += share - served
            lat_weighted.append((latency, served))
        if not running:
            fail_total = offered
        self.rps, self.fail_rps = served_total, fail_total
        self.total += (served_total + fail_total) * dt
        self.failures += fail_total * dt
        self.p95 = self._p95(lat_weighted)
        if running:
            avg_pct = sum(p["cpu_m"] for p in running) / len(running) / POD_CPU_REQUEST_M * 100
            self.cpu_samples.append((self.t, avg_pct))

    @staticmethod
    def _p95(lat_weighted):
        total = sum(w for _, w in lat_weighted)
        if total <= 0:
            return 0.0
        acc = 0.0
        for latency, w in sorted(lat_weighted):
            acc += w
            if acc >= 0.95 * total:
                return latency * random.uniform(1.0, 1.15)
        return lat_weighted[-1][0]

    def _metrics(self):
        while self.cpu_samples and self.cpu_samples[0][0] < self.t - CPU_WINDOW_S:
            self.cpu_samples.popleft()
        if self.t >= self.next_metrics_t:
            self.next_metrics_t += METRICS_PERIOD_S
            if self.cpu_samples:
                self.metric_cpu_pct = round(sum(v for _, v in self.cpu_samples) / len(self.cpu_samples))
                self.metric_t = self.t

    def _hpa(self):
        if self.t < self.next_hpa_t:
            return
        self.next_hpa_t += HPA_PERIOD_S
        ratio = self.metric_cpu_pct / HPA_TARGET_PCT
        if ratio > 1:
            # Like the real HPA: when scaling up, pods without a usable metric yet (not running, or
            # ready only after the published sample was taken) count as using 0% CPU.
            measured = sum(1 for p in self.pods if p["phase"] == "Running"
                           and p["ready_t"] <= self.metric_t - CPU_WINDOW_S)
            ratio = ratio * measured / max(self.replicas, 1)
        rec = self.replicas if abs(ratio - 1) <= HPA_TOLERANCE else math.ceil(self.replicas * ratio)
        rec = max(HPA_MIN, min(HPA_MAX, rec))
        self.recommendations.append((self.t, rec))
        while self.recommendations[0][0] < self.t - SCALE_DOWN_WINDOW_S:
            self.recommendations.popleft()
        if rec > self.replicas:
            self.replicas = min(rec, max(self.replicas * 2, self.replicas + 4), HPA_MAX)
        else:
            stable = max(r for _, r in self.recommendations)
            if stable < self.replicas and self.t - self.last_scale_down_t >= SCALE_DOWN_PERIOD_S:
                self.replicas = max(stable, math.ceil(self.replicas * 0.5), HPA_MIN)
                self.last_scale_down_t = self.t

    def _reconcile(self):
        active = [p for p in self.pods if p["phase"] != "Terminating"]
        for _ in range(self.replicas - len(active)):
            self.pods.append(self._pod())
        surplus = len(active) - self.replicas
        if surplus > 0:
            # Kubernetes deletes unscheduled, then not-ready, then the newest ready pods first.
            order = {"Pending": 0, "Starting": 1, "Running": 2}
            victims = sorted(active, key=lambda p: (order[p["phase"]], -(p["ready_t"] or p["created_t"])))
            for pod in victims[:surplus]:
                pod.update(phase="Terminating", end_t=self.t + POD_TERMINATE_S)

    def _schedule(self):
        for pod in sorted((p for p in self.pods if p["phase"] == "Pending"), key=lambda p: p["created_t"]):
            for node in self.nodes:
                used = sum(1 for p in self.pods if p["node"] == node["name"])
                if node["status"] != "Ready" or used >= node["slots"]:
                    continue
                if node["pulled_at"] is None:
                    node["pulled_at"] = self.t + IMAGE_PULL_S
                pod.update(phase="Starting", node=node["name"],
                           ready_at=max(self.t + POD_START_S, node["pulled_at"]))
                break

    def _cluster_autoscaler(self):
        t = self.t
        for node in self.nodes:
            if node["status_until"] is not None and t >= node["status_until"]:
                if node["status"] == "Provisioning":
                    node.update(status="NotReady", status_until=t + NODE_READY_S)
                elif node["status"] == "NotReady":
                    node.update(status="Ready", status_until=None)
        self.nodes = [n for n in self.nodes if not (n["status"] == "Removing" and t >= n["status_until"])]

        waiting = [p for p in self.pods if p["phase"] == "Pending" and t - p["created_t"] >= CA_TRIGGER_S]
        provisioning = any(n["status"] in ("Provisioning", "NotReady") for n in self.nodes)
        if waiting and not provisioning and len(self.nodes) < MAX_NODES:
            name = f"aks-system-19526036-vmss{len(self.nodes):06d}"
            self.nodes.append(dict(self._node(name, "Provisioning"), status_until=t + NODE_REGISTER_S))

        for node in self.nodes[1:]:
            busy = any(p["node"] == node["name"] for p in self.pods)
            if node["status"] != "Ready" or busy:
                node["unneeded_since"] = None
            elif node["unneeded_since"] is None:
                node["unneeded_since"] = t
            elif t - node["unneeded_since"] >= NODE_UNNEEDED_S:
                node.update(status="Removing", status_until=t + NODE_REMOVE_S)

    # --- API ---------------------------------------------------------------------
    def state(self):
        with self.lock:
            active = [p for p in self.pods if p["phase"] != "Terminating"]
            return {
                "mode": self.mode,
                "time": round(self.t, 1),
                "speed": self.speed,
                "users": round(self.users),
                "target_users": self.target_users,
                "rps": round(self.rps, 1),
                "fail_rps": round(self.fail_rps, 1),
                "p95_ms": round(self.p95),
                "total": int(self.total),
                "failures": int(self.failures),
                "pod_capacity_rps": round(POD_CAPACITY_RPS),
                "pods": [{"name": p["name"], "phase": p["phase"], "node": p["node"], "rps": round(p["rps"], 1),
                          "cpu_m": round(p["cpu_m"])} for p in self.pods],
                "nodes": [{"name": n["name"], "status": n["status"]} for n in self.nodes],
                "hpa": {"current": len(active), "desired": self.replicas, "cpu_pct": self.metric_cpu_pct,
                        "target_pct": HPA_TARGET_PCT, "min": HPA_MIN, "max": HPA_MAX},
                "error": None,
            }
