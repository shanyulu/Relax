# Task 4 contract demo

Run from this directory:

```bash
python -m unittest -v test_contract_demo.py
python contract_demo.py
python render_demo.py results/contract-demo.json --output results/contract-demo.html
```

Open `results/contract-demo.html` in a browser (GitHub's `blob` view shows the source; download the file or use a local checkout to run it). The page replays four deterministic scenarios: normal 1→2→1, health-check failure, backend still busy during drain, and cleanup failure followed by explicit reconciliation. Scrub the timeline to inspect route membership, admitted requests, PG ownership and the recovery boundary. The JSON is the exact event trace used by the page.

This exercises the proposed request and lifecycle contract, including unknown-request `404`, absolute-target validation, `409` while cleanup is unresolved, and an explicit retry/reconcile path. Engines, workers, health checks, admission, backend idleness and PGs are in-memory fakes; the `workers` field is a contract signal, not a real worker process. The demo has no Ray, SGLang, GPU, Autoscaler or real scoring. It does not establish that Task 3 supplies the required non-cancelling drain or full-worker cleanup, or that text training continues during scaling. Those remain integration and acceptance work for [RFC #351](https://github.com/redai-studio/Relax/issues/351).
