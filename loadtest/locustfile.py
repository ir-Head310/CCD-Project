"""Flash-sale traffic for the Product Service.

Each simulated user sends ~1 request/second (constant_throughput(1)), so the
user count from FlashSaleShape is roughly the target requests/second:

    baseline ~5 rps -> ramp to ~300 rps -> hold -> ramp down -> cool-down

Run headless and keep the CSVs for analysis/plot_results.py:

    locust -f locustfile.py --host http://<EXTERNAL-IP> --headless \
           --csv results/run1 --csv-full-history

Set TIME_SCALE=0.1 for a quick 1/10-length smoke run, PEAK_USERS to change the peak.

Each user drops its keep-alive connection every RECONNECT_EVERY requests (default 10,
i.e. ~10 s). The Azure load balancer and kube-proxy balance per *connection*, so
without this the users connected before scale-out stay pinned to the original pods
and newly added pods receive no traffic (observed in run1). Real shoppers come and
go, so periodic reconnects are the more realistic model. Set RECONNECT_EVERY=0 to
disable and reproduce the pinned behaviour.
"""
import collections
import csv
import os
import random

from locust import HttpUser, LoadTestShape, constant_throughput, events, task

PRODUCT_IDS = [101, 102, 103, 104, 105, 201, 202, 203, 301, 302, 303, 401, 402, 501, 502]
HOT_DEALS = [101, 103, 104]  # most flash-sale traffic hits a few doorbuster items

TIME_SCALE = float(os.environ.get("TIME_SCALE", "1"))
PEAK_USERS = int(os.environ.get("PEAK_USERS", "300"))
BASE_USERS = int(os.environ.get("BASE_USERS", "5"))
RECONNECT_EVERY = int(os.environ.get("RECONNECT_EVERY", "10"))

served_by = collections.Counter()


class FlashSaleShopper(HttpUser):
    wait_time = constant_throughput(1)

    def on_start(self):
        # Stagger the first reconnect so users don't all reconnect in lockstep.
        self._sent = random.randrange(RECONNECT_EVERY) if RECONNECT_EVERY else 0

    def _get(self, path, name):
        if RECONNECT_EVERY and self._sent >= RECONNECT_EVERY:
            self.client.close()  # drop pooled connections; the next request opens a new one
            self._sent = 0
        self._sent += 1
        self.client.get(path, name=name)

    @task(6)
    def check_deal_price(self):
        pid = random.choice(HOT_DEALS) if random.random() < 0.7 else random.choice(PRODUCT_IDS)
        qty = random.choice([1, 1, 1, 2, 3])
        self._get(f"/products/{pid}/price?qty={qty}", "/products/[id]/price")

    @task(3)
    def view_product(self):
        self._get(f"/products/{random.choice(PRODUCT_IDS)}", "/products/[id]")

    @task(1)
    def browse_category(self):
        cat = random.choice(["electronics", "fashion", "home", "grocery", "books"])
        self._get(f"/products?category={cat}", "/products?category")


class FlashSaleShape(LoadTestShape):
    # (end_time_seconds, target_users, spawn_rate_per_second)
    stages = [
        (60, BASE_USERS, 5),     # 0-1 min: normal traffic
        (180, PEAK_USERS, 3),    # 1-3 min: sale opens, ramp to peak
        (360, PEAK_USERS, 10),   # 3-6 min: hold the peak
        (480, BASE_USERS, 5),    # 6-8 min: sale ends, ramp down
        (720, BASE_USERS, 5),    # 8-12 min: cool-down, watch scale-in
    ]

    def tick(self):
        run_time = self.get_run_time()
        for end, users, rate in self.stages:
            if run_time < end * TIME_SCALE:
                return users, rate
        return None


@events.request.add_listener
def _count_pod(response=None, exception=None, **_):
    if response is not None and exception is None:
        served_by[response.headers.get("X-Served-By", "unknown")] += 1


@events.test_stop.add_listener
def _write_distribution(environment, **_):
    """Write how many requests each pod served (shows load-balancer distribution)."""
    if not served_by:
        return
    prefix = environment.parsed_options.csv_prefix if environment.parsed_options else None
    path = f"{prefix}_served_by.csv" if prefix else "served_by.csv"
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["pod", "requests"])
        for pod, count in served_by.most_common():
            writer.writerow([pod, count])
    print(f"\nRequests per pod -> {path}")
    for pod, count in served_by.most_common():
        print(f"  {pod:<45} {count}")
