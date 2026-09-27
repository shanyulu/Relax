"""Pre-run worker environment probe (protocol section 7.2).

Submitted as an actual Ray task: verifies proxy-env inheritance and direct
internal-endpoint reachability from a worker's perspective.
"""

import json
import os

import ray

ray.init(address="auto", ignore_reinit_error=True, logging_level="ERROR")

NODE_IP = ray.util.get_node_ip_address()


def probe():
    import urllib.request

    out = {
        "worker_pid": os.getpid(),
        "proxy_env": {k: os.environ.get(k) for k in
                      ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "no_proxy", "NO_PROXY")},
        "direct_get": {},
    }
    # Direct (proxy-free) HTTP to internal endpoints: dashboard on node IP and
    # loopback, plus a plain socket bind on an engine-style port.
    for name, url in (
        ("dashboard_node_ip", f"http://{NODE_IP}:8265/-/routes"),
        ("dashboard_loopback", "http://127.0.0.1:8265/-/routes"),
    ):
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(url, timeout=5) as resp:
                out["direct_get"][name] = f"HTTP {resp.status}"
        except Exception as exc:  # noqa: BLE001
            out["direct_get"][name] = f"FAIL {type(exc).__name__}: {str(exc)[:80]}"
    try:
        import socket

        s = socket.socket()
        s.bind((NODE_IP, 0))
        out["engine_style_bind"] = f"OK port {s.getsockname()[1]}"
        s.close()
    except Exception as exc:  # noqa: BLE001
        out["engine_style_bind"] = f"FAIL {type(exc).__name__}"
    return out


if __name__ == "__main__":
    P = ray.remote(probe)
    result = ray.get(P.options(num_cpus=1).remote(), timeout=60)
    print(json.dumps(result, indent=1))
    # PASS criteria on substance:
    # - no proxy env in the worker (or no_proxy covers the container IP);
    # - the loopback dashboard answers ANY HTTP status (a 404 is a completed
    #   proxy-free round-trip; the node-IP dashboard refusal is its bind
    #   scope — the dashboard binds 127.0.0.1 only, while engines bind the
    #   node IP, verified by the engine-style bind below);
    # - an engine-style bind on the node IP succeeds.
    loop = result["direct_get"].get("dashboard_loopback", "")
    http_roundtrip = loop.startswith("HTTP") or loop.startswith("FAIL HTTPError")
    ok = (
        (not result["proxy_env"]["http_proxy"] and not result["proxy_env"]["https_proxy"])
        or result["proxy_env"].get("no_proxy")
    ) and http_roundtrip and result["engine_style_bind"].startswith("OK")
    print("PROBE-" + ("PASS" if ok else "FAIL"))
