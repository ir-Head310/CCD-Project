"""Live backend: drives Locust in-process against the real service and reads the
real cluster with kubectl.

Must be imported after gevent monkey-patching (server.py does this for --live).
Per-pod load comes from the X-Served-By header on every response, so it updates
every second; pod CPU from metrics-server is shown too, but AKS only refreshes it
about once a minute.
"""
import collections
import importlib.util
import json
import pathlib
import subprocess
import time

import gevent
from locust.env import Environment

LOCUSTFILE = pathlib.Path(__file__).resolve().parent.parent / "loadtest" / "locustfile.py"
WINDOW_S = 5          # per-pod and total req/s are averaged over this window
POLL_S = 2            # kubectl get pods/nodes/hpa
TOP_POLL_S = 10       # kubectl top pods
POD_CPU_LIMIT_M = 500
CPU_PER_REQUEST_MS = 2.5  # measured in run2: ~750m at 300 req/s


def _load_user_class():
    spec = importlib.util.spec_from_file_location("flashsale_locustfile", LOCUSTFILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.FlashSaleShopper


def _kubectl_json(*args):
    out = subprocess.run(["kubectl", *args, "-o", "json"], capture_output=True, text=True, timeout=15)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip().splitlines()[-1] if out.stderr.strip() else "kubectl failed")
    return json.loads(out.stdout)


class LiveCluster:
    mode = "live"

    def __init__(self, host, namespace="flash-sale", selector="app=product-service"):
        self.host = host
        self.namespace = namespace
        self.selector = selector
        self.env = Environment(user_classes=[_load_user_class()], host=host)
        self.runner = self.env.create_local_runner()
        self.env.events.request.add_listener(self._on_request)
        self.started = time.time()
        self.target_users = 0
        self.hits = collections.deque()  # (time, pod, failed, response_ms)
        self.total = 0
        self.failures = 0
        self.k8s = {"pods": [], "nodes": [], "hpa": None, "cpu": {}, "error": None}
        gevent.spawn(self._poll_loop)
        gevent.spawn(self._top_loop)

    # --- traffic -------------------------------------------------------------------
    def set_users(self, n):
        self.target_users = max(0, int(n))
        if self.target_users == 0:
            self.runner.stop()
        else:
            self.runner.start(self.target_users, spawn_rate=10)

    def _on_request(self, response=None, exception=None, response_time=None, **_):
        pod = None
        if response is not None and exception is None:
            pod = response.headers.get("X-Served-By")
        self.hits.append((time.time(), pod, exception is not None, response_time or 0))
        self.total += 1
        self.failures += exception is not None

    def _window(self):
        cutoff = time.time() - WINDOW_S
        while self.hits and self.hits[0][0] < cutoff:
            self.hits.popleft()
        return list(self.hits)

    # --- cluster -------------------------------------------------------------------
    def _poll_loop(self):
        while True:
            try:
                pods = _kubectl_json("get", "pods", "-n", self.namespace, "-l", self.selector)["items"]
                nodes = _kubectl_json("get", "nodes")["items"]
                try:
                    hpa = _kubectl_json("get", "hpa", "product-service", "-n", self.namespace)
                except RuntimeError:
                    hpa = None
                self.k8s.update(pods=[self._pod_view(p) for p in pods],
                                nodes=[self._node_view(n) for n in nodes],
                                hpa=self._hpa_view(hpa) if hpa else None, error=None)
            except (RuntimeError, subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as err:
                self.k8s["error"] = f"cluster unreachable: {err}"
            gevent.sleep(POLL_S)

    def _top_loop(self):
        while True:
            try:
                out = subprocess.run(["kubectl", "top", "pods", "-n", self.namespace, "-l", self.selector,
                                      "--no-headers"], capture_output=True, text=True, timeout=15)
                if out.returncode == 0:
                    cpu = {}
                    for line in out.stdout.splitlines():
                        name, value = line.split()[:2]
                        cpu[name] = int(value[:-1]) if value.endswith("m") else int(float(value) * 1000)
                    self.k8s["cpu"] = cpu
            except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
                pass
            gevent.sleep(TOP_POLL_S)

    @staticmethod
    def _pod_view(pod):
        status = pod.get("status", {})
        conditions = {c["type"]: c["status"] for c in status.get("conditions", [])}
        if pod["metadata"].get("deletionTimestamp"):
            phase = "Terminating"
        elif not pod.get("spec", {}).get("nodeName"):
            phase = "Pending"
        elif conditions.get("Ready") == "True":
            phase = "Running"
        else:
            phase = "Starting"
        return {"name": pod["metadata"]["name"], "phase": phase, "node": pod.get("spec", {}).get("nodeName")}

    @staticmethod
    def _node_view(node):
        ready = any(c["type"] == "Ready" and c["status"] == "True" for c in node["status"].get("conditions", []))
        return {"name": node["metadata"]["name"], "status": "Ready" if ready else "NotReady"}

    @staticmethod
    def _hpa_view(hpa):
        spec, status = hpa.get("spec", {}), hpa.get("status", {})
        cpu = None
        for metric in status.get("currentMetrics") or []:
            if metric.get("type") == "Resource" and metric["resource"]["name"] == "cpu":
                cpu = metric["resource"]["current"].get("averageUtilization")
        target = next((m["resource"]["target"].get("averageUtilization") for m in spec.get("metrics", [])
                       if m.get("type") == "Resource"), 60)
        return {"current": status.get("currentReplicas", 0), "desired": status.get("desiredReplicas", 0),
                "cpu_pct": cpu or 0, "target_pct": target, "min": spec.get("minReplicas", 1),
                "max": spec.get("maxReplicas", 1)}

    # --- API -----------------------------------------------------------------------
    def state(self):
        hits = self._window()
        per_pod = collections.Counter(pod for _, pod, failed, _ in hits if not failed)
        fails = sum(1 for _, _, failed, _ in hits if failed)
        times = sorted(ms for _, _, failed, ms in hits if not failed)
        p95 = times[int(len(times) * 0.95) - 1] if times else 0

        pods = [dict(p) for p in self.k8s["pods"]]
        known = {p["name"] for p in pods}
        if self.k8s["error"]:
            # No cluster access (e.g. testing against a local app): show the responders we can see.
            pods += [{"name": name, "phase": "Running", "node": "unknown"} for name in per_pod if name not in known]
        nodes = self.k8s["nodes"] or ([{"name": "unknown", "status": "Ready"}] if pods else [])
        for pod in pods:
            pod["rps"] = round(per_pod.get(pod["name"], 0) / WINDOW_S, 1)
            pod["cpu_m"] = self.k8s["cpu"].get(pod["name"])

        hpa = self.k8s["hpa"] or {"current": len(pods), "desired": len(pods), "cpu_pct": 0, "target_pct": 60,
                                  "min": None, "max": None}
        return {
            "mode": self.mode,
            "host": self.host,
            "time": round(time.time() - self.started, 1),
            "speed": 1,
            "users": self.runner.user_count,
            "target_users": self.target_users,
            "rps": round(sum(per_pod.values()) / WINDOW_S, 1),
            "fail_rps": round(fails / WINDOW_S, 1),
            "p95_ms": round(p95),
            "total": self.total,
            "failures": self.failures,
            "pod_capacity_rps": round(POD_CPU_LIMIT_M / CPU_PER_REQUEST_MS),
            "pods": pods,
            "nodes": nodes,
            "hpa": hpa,
            "error": self.k8s["error"],
        }
