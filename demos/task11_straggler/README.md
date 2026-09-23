# Task 11: asynchronous straggler mechanism demo

This standalone experiment implements the narrow mechanism proposed in [RFC #357](https://github.com/redai-studio/Relax/issues/357): training threads record CUDA Events; one background collector per rank reads only completed pairs and sends bounded records; a receiver compares equivalent rank and workload samples. It does not modify Relax training, use MetricsService, or validate a full recipe.

Measured local runs, including the adverse trials, are in [EVIDENCE.md](EVIDENCE.md). A generated [rank × stage view](results/2gpu-v4-rank-view.md) shows the report a maintainer would inspect.

## Run

Requires two local CUDA GPUs and the repository's PyTorch installation. No extra package is needed.

```bash
cd demos/task11_straggler
python -m unittest -v test_diagnosis.py test_probe.py test_rank_view.py test_replay.py
python run_demo.py --gpus 2 --null-pairs 4 --output results/local-2gpu.json
python render_report.py results/local-2gpu.json --output results/local-2gpu.png
python render_rank_view.py results/local-2gpu.json --markdown results/local-rank-view.md --image results/local-rank-view.png
python render_replay.py results/local-2gpu.json --output results/local-replay.html
```

The run performs warmup, interleaved alternating off/on pairs and off/off controls, then five observed cases: control, one extra forward pass on rank 1, a run with the extra forward only in the middle half, unequal batch workload on rank 1, and a host stall before its collective. The receiver reports stage duration, peer median, coverage, ambiguity and dropped samples. The collective interval is an Event pair on the current stream; it is **not** a measured link transfer time or a hardware-fault diagnosis.

Open `results/local-replay.html` in a browser (GitHub's `blob` view shows the source; download the file or use a local checkout to run it). It embeds the measured diagnostic samples and lets a reviewer inspect each sampled step. The optional missing-peer drill removes one recorded rank report **only in the replay**, then reruns the receiver-side diagnosis; it is explicitly marked as a counterfactual, not a measured transport failure. A frame is comparable only when all ranks report the same stage set, cohort and workload class. For a short run, use `--pairs 1 --null-pairs 1 --steps 256 --injection-steps 64 --interval 8`. The published v4 performance numbers predate the additional recovery scenario and cannot be attributed to this current version.

The JSON contains every per-rank elapsed time, loss, final-parameter hash, sampled interval, collection counter, off/off control and source hash. Overhead is based on the slower rank for each pair. The bootstrap interval describes this local run only. A median below 0.5% here would still not satisfy the official criterion. That needs a frozen Relax recipe, repeated runs, loss/overlap checks and full reporting cost. The parent runner terminates unfinished workers and closes the result queue on failure or deadline. The PNG renderers require Matplotlib and NumPy; the mechanism does not.

There is no synchronization, training collective, or IPC send added to the training step by the probe. The benchmark uses its original gradient all-reduce and CUDA synchronization/barrier at trial boundaries to time a complete run. The parent process drains the result queue while workers train. The Event pool and result queue are bounded; skipped and dropped samples are counted. Missing reports and unmeasured counters are displayed as unknown.

After startup, a background readout exception disables the collector; a transport rejection drops that sample and counting continues. Both paths return status rather than rethrowing through `close()`. The close deadline stops polling unfinished Events, counts abandoned samples and does not recycle their slots. Startup and training-thread Event recording errors still propagate; complete instrumentation failure isolation remains integration work. The tests include identical parameter updates after an injected transport failure and collector exit when an Event never becomes ready.

JSON byte counts exclude multiprocessing framing. Report lag ends at collector readout before payload serialization and queue insertion, so it is not end-to-end alert latency; queue flushing after insertion may continue outside the timed loop. The published v4 performance figures belong to their [pinned source snapshot](https://github.com/shanyulu/Relax/tree/7718e036c7144b68a01a8b608a4b463eb8e16ddd/demos/task11_straggler); later lifecycle fixes have a separate smoke run and tests.
