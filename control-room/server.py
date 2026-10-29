"""Flash Sale Control Room: a traffic slider plus a live 3D view of the cluster.

    python control-room/server.py                              # simulation, no cloud
    python control-room/server.py --speed 4                    # simulation at 4x speed, for rehearsing
    python control-room/server.py --live --host http://<IP>    # real traffic against AKS

Then open http://localhost:8090.
"""
import sys

LIVE = "--live" in sys.argv
if LIVE:
    # Locust runs on gevent; patch before anything imports threading or sockets.
    from gevent import monkey

    monkey.patch_all()

import argparse  # noqa: E402
import pathlib  # noqa: E402
import webbrowser  # noqa: E402

from flask import Flask, jsonify, request, send_from_directory  # noqa: E402

STATIC = pathlib.Path(__file__).resolve().parent / "static"


def build_app(cluster):
    app = Flask(__name__, static_folder=None)

    @app.get("/")
    def index():
        return send_from_directory(STATIC, "index.html")

    @app.get("/api/state")
    def state():
        return jsonify(cluster.state())

    @app.post("/api/traffic")
    def traffic():
        users = int((request.get_json(silent=True) or {}).get("users", 0))
        cluster.set_users(max(0, min(users, 400)))
        return jsonify(target_users=cluster.target_users)

    return app


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="real traffic + real cluster (needs kubectl access)")
    ap.add_argument("--host", default="http://localhost:8080", help="Product Service base URL for --live")
    ap.add_argument("--speed", type=float, default=1.0, help="simulation speed multiplier")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    if args.live:
        from live import LiveCluster
        cluster = LiveCluster(args.host.rstrip("/"))
    else:
        from sim import SimCluster
        cluster = SimCluster(speed=args.speed)

    app = build_app(cluster)
    url = f"http://localhost:{args.port}"
    print(f"Control room ({cluster.mode}) on {url}")
    if not args.no_browser:
        webbrowser.open(url)
    if args.live:
        from gevent.pywsgi import WSGIServer
        WSGIServer(("127.0.0.1", args.port), app, log=None).serve_forever()
    else:
        app.run(host="127.0.0.1", port=args.port, threaded=True)


if __name__ == "__main__":
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    main()
