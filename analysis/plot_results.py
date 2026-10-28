"""Combine a Locust run and the cluster metrics into one figure plus a summary.

    python analysis/plot_results.py --locust results/run1_stats_history.csv \
                                    --k8s results/run1_k8s.csv --out results/run1.png

Summary metrics (measured, not assumed):
  * scale-out reaction  : load spike start -> HPA first asks for more replicas
  * scale-out to ready  : load spike start -> first extra pod Ready
  * time to peak pods   : load spike start -> max ready pods reached
  * scale-in            : load drop -> ready pods back at the minimum
  * availability        : 1 - failures / requests over the whole run
"""
import argparse

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402


def load_locust(path):
    df = pd.read_csv(path)
    df = df[df["Name"] == "Aggregated"].copy()
    df["t"] = pd.to_numeric(df["Timestamp"])
    return df


def first_time(df, mask):
    hits = df.loc[mask, "t"]
    return hits.iloc[0] if not hits.empty else None


def fmt(seconds):
    return "n/a" if seconds is None else f"{seconds:.0f} s"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--locust", required=True, help="<prefix>_stats_history.csv")
    ap.add_argument("--k8s", required=True, help="CSV from collect_metrics.py")
    ap.add_argument("--out", default="scaling.png")
    ap.add_argument("--spike-rps", type=float, default=50, help="RPS above which the sale is 'on'")
    args = ap.parse_args()

    lc = load_locust(args.locust)
    k8 = pd.read_csv(args.k8s)
    k8["t"] = k8["unix_ts"]

    t0 = min(lc["t"].min(), k8["t"].min())
    lc["rel"] = lc["t"] - t0
    k8["rel"] = k8["t"] - t0

    min_pods = k8["pods_ready"].iloc[0]
    spike_start = first_time(lc, lc["Requests/s"] > args.spike_rps)
    peak_rps = lc["Requests/s"].max()
    after_peak = lc[lc["t"] > lc.loc[lc["Requests/s"].idxmax(), "t"]]
    spike_end = first_time(after_peak, after_peak["Requests/s"] < args.spike_rps)

    summary = {}
    if spike_start is not None:
        k_after = k8[k8["t"] >= spike_start]
        desired_up = first_time(k_after, k_after["hpa_desired_replicas"] > min_pods)
        ready_up = first_time(k_after, k_after["pods_ready"] > min_pods)
        peak_pods = k8["pods_ready"].max()
        reach_peak = first_time(k_after, k_after["pods_ready"] >= peak_pods)
        summary["scale-out reaction (HPA decision)"] = fmt(desired_up and desired_up - spike_start)
        summary["scale-out to first new pod Ready"] = fmt(ready_up and ready_up - spike_start)
        summary[f"time to peak pods ({peak_pods})"] = fmt(reach_peak and reach_peak - spike_start)
    if spike_end is not None:
        k_end = k8[k8["t"] >= spike_end]
        back_down = first_time(k_end, k_end["pods_ready"] <= min_pods)
        summary["scale-in back to min pods"] = fmt(back_down and back_down - spike_end)

    last = lc.iloc[-1]
    total, fails = last["Total Request Count"], last["Total Failure Count"]
    summary["peak throughput"] = f"{peak_rps:.0f} req/s"
    summary["requests / failures"] = f"{int(total)} / {int(fails)}"
    summary["availability"] = f"{100 * (1 - fails / total):.3f} %" if total else "n/a"
    summary["peak p95 latency"] = f"{lc['95%'].max():.0f} ms"
    summary["peak HPA CPU"] = f"{pd.to_numeric(k8['hpa_cpu_pct'], errors='coerce').max():.0f} %"

    fig, axes = plt.subplots(4, 1, figsize=(11, 11), sharex=True)
    axes[0].plot(lc["rel"], lc["Requests/s"], label="requests/s")
    axes[0].plot(lc["rel"], lc["Failures/s"], label="failures/s", color="tab:red")
    axes[0].set_ylabel("req/s")
    axes[0].legend(loc="upper right")
    axes[0].set_title("Flash-sale load test: traffic, CPU and pod count")

    axes[1].plot(lc["rel"], pd.to_numeric(lc["50%"], errors="coerce"), label="p50")
    axes[1].plot(lc["rel"], pd.to_numeric(lc["95%"], errors="coerce"), label="p95")
    axes[1].set_ylabel("latency (ms)")
    axes[1].legend(loc="upper right")

    axes[2].plot(k8["rel"], pd.to_numeric(k8["hpa_cpu_pct"], errors="coerce"), color="tab:orange")
    axes[2].axhline(60, ls="--", color="grey", lw=1, label="HPA target 60%")
    axes[2].set_ylabel("avg CPU % of request")
    axes[2].legend(loc="upper right")

    axes[3].step(k8["rel"], k8["hpa_desired_replicas"], where="post", label="HPA desired")
    axes[3].step(k8["rel"], k8["pods_ready"], where="post", label="pods ready")
    axes[3].step(k8["rel"], k8["nodes"], where="post", label="nodes", ls=":")
    axes[3].set_ylabel("count")
    axes[3].set_xlabel("seconds since start")
    axes[3].legend(loc="upper right")

    for ax in axes:
        ax.grid(alpha=0.3)
        for marker in (spike_start, spike_end):
            if marker is not None:
                ax.axvline(marker - t0, color="tab:green", ls=":", lw=1)

    fig.tight_layout()
    fig.savefig(args.out, dpi=130)
    print(f"Figure -> {args.out}\n")
    for key, val in summary.items():
        print(f"  {key:<38} {val}")


if __name__ == "__main__":
    main()
