"""Poll the cluster every few seconds and record HPA / pod / CPU state to CSV.

Start this just before the Locust run and stop it (Ctrl+C) after cool-down:

    python analysis/collect_metrics.py --out results/run1_k8s.csv

Columns: unix_ts, hpa_current_replicas, hpa_desired_replicas, hpa_cpu_pct,
pods_total, pods_ready, pods_pending, cpu_millicores_sum, nodes
"""
import argparse
import csv
import json
import subprocess
import sys
import time


def kubectl_json(*args):
    out = subprocess.run(["kubectl", *args, "-o", "json"], capture_output=True, text=True, timeout=20)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip())
    return json.loads(out.stdout)


def pod_cpu_sum(namespace, selector):
    """Sum of pod CPU in millicores from metrics-server (kubectl top)."""
    out = subprocess.run(
        ["kubectl", "top", "pods", "-n", namespace, "-l", selector, "--no-headers"],
        capture_output=True, text=True, timeout=20,
    )
    if out.returncode != 0:
        return ""  # metrics not available yet for new pods
    total = 0
    for line in out.stdout.splitlines():
        cpu = line.split()[1]
        total += int(cpu[:-1]) if cpu.endswith("m") else int(float(cpu) * 1000)
    return total


def sample(namespace, hpa_name, selector):
    hpa = kubectl_json("get", "hpa", hpa_name, "-n", namespace)
    status = hpa.get("status", {})
    cpu_pct = ""
    for metric in status.get("currentMetrics") or []:
        if metric.get("type") == "Resource" and metric["resource"]["name"] == "cpu":
            cpu_pct = metric["resource"]["current"].get("averageUtilization", "")

    pods = kubectl_json("get", "pods", "-n", namespace, "-l", selector)["items"]
    ready = pending = 0
    for pod in pods:
        if pod["status"].get("phase") == "Pending":
            pending += 1
        conds = {c["type"]: c["status"] for c in pod["status"].get("conditions", [])}
        if conds.get("Ready") == "True" and not pod["metadata"].get("deletionTimestamp"):
            ready += 1

    nodes = len(kubectl_json("get", "nodes")["items"])
    return [
        round(time.time(), 1),
        status.get("currentReplicas", ""),
        status.get("desiredReplicas", ""),
        cpu_pct,
        len(pods),
        ready,
        pending,
        pod_cpu_sum(namespace, selector),
        nodes,
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="k8s_metrics.csv")
    ap.add_argument("--interval", type=float, default=5)
    ap.add_argument("--namespace", default="flash-sale")
    ap.add_argument("--hpa", default="product-service")
    ap.add_argument("--selector", default="app=product-service")
    args = ap.parse_args()

    header = ["unix_ts", "hpa_current_replicas", "hpa_desired_replicas", "hpa_cpu_pct",
              "pods_total", "pods_ready", "pods_pending", "cpu_millicores_sum", "nodes"]
    with open(args.out, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        print(f"Writing to {args.out} every {args.interval}s. Ctrl+C to stop.")
        print("  time      replicas(cur/des)  cpu%  ready/total  pending  nodes")
        try:
            while True:
                t0 = time.time()
                try:
                    row = sample(args.namespace, args.hpa, args.selector)
                except (RuntimeError, subprocess.TimeoutExpired) as err:
                    print(f"  sample failed: {err}", file=sys.stderr)
                else:
                    writer.writerow(row)
                    fh.flush()
                    print(f"  {time.strftime('%H:%M:%S')}  {row[1]!s:>4}/{row[2]!s:<4}         "
                          f"{row[3]!s:>4}  {row[5]:>3}/{row[4]:<3}      {row[6]:>3}     {row[8]}")
                time.sleep(max(0.0, args.interval - (time.time() - t0)))
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
