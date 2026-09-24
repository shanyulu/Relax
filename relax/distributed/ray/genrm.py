# Copyright (c) 2026 Relax Authors. All Rights Reserved.

"""GenRM Manager for Generative Reward Model Service.

This module implements a simplified manager for genRM engines, built on top of
``MultiEngineManager`` (parallel bring-up, health check, dead-engine recovery,
onload/offload) with GenRM-specific placement and engine wiring.
"""

import logging
import threading

import ray

from relax.backends.sglang.sglang_engine import GenRMEngine
from relax.core.node_group_affinity import with_control_plane_affinity
from relax.distributed.ray.multi_engine_manager import MultiEngineManager, _is_engine_dead  # noqa: F401
from relax.distributed.ray.utils import NOSET_VISIBLE_DEVICES_ENV_VARS_LIST, Lock
from relax.utils.http_utils import init_http_client
from relax.utils.logging_utils import get_logger


logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = get_logger(__name__)

_GENRM_PORT_BASE = 16000
_GENRM_PORT_WINDOW_SIZE = 1000
_MAX_PORT = 65535


@ray.remote
class GenRMManager(MultiEngineManager):
    """Manager for GenRM engines.

    This is a simplified version of RolloutManager focused on:
    - Initializing genRM engines
    - Health checking
    - Onload/offload operations
    """

    def __init__(self, args, pg, bundle_offset: int = 0, port_window_index: int = 0):
        init_http_client(args)

        num_gpu_per_engine = min(args.genrm_num_gpus_per_engine, args.num_gpus_per_node)
        num_slots = 0 if args.debug_train_only else args.genrm_num_gpus // num_gpu_per_engine
        nodes_per_engine = max(1, args.genrm_num_gpus_per_engine // args.num_gpus_per_node)

        self.pg = pg
        self.num_gpu_per_engine = num_gpu_per_engine
        self.bundle_offset = bundle_offset
        self.port_window_index = port_window_index

        super().__init__(
            args,
            num_slots=num_slots,
            nodes_per_engine=nodes_per_engine,
            engine_actor_cls=GenRMEngine,
            skip_init=args.debug_train_only,
            log_prefix="GenRM",
        )
        self.num_new_engines = len(self.engines)
        self.genrm_engine_lock = Lock.options(
            **with_control_plane_affinity(self.args, {"num_cpus": 1, "num_gpus": 0})
        ).remote()

        # Task 4 elastic-scaling state. The scale lifecycle runs in daemon
        # threads so long engine bring-up never blocks the actor's method
        # queue (get_engine_hosts_ports / health stay responsive while a new
        # replica loads); all shared state is guarded by ``_scale_lock``.
        self._scale_lock = threading.RLock()
        self._scale_progress: dict = {}
        self._scale_op_params: dict = {}
        self._scale_abort: dict = {}
        self._scale_added_ranks: list = []
        self._candidate_ranks: set = set()
        self._draining_ranks: set = set()
        self._scale_placements: dict = {}
        self._scale_drain_confirmed: dict = {}
        self._scale_drain_timeout_s = float(getattr(args, "genrm_scale_drain_timeout_s", 600.0))

    def get_genrm_engines_and_lock(self):
        return self.engines, self.genrm_engine_lock, self.num_new_engines

    def get_engine_hosts_ports(self):
        """Return a list of (host, port) tuples for each live, routable genRM
        engine.

        This is used by the GenRM service to send HTTP generation requests
        directly to the underlying SGLang servers.

        The host/port information is captured during engine initialization
        from the addr_and_ports dict passed to ``_allocate_engine_addr_and_ports``.

        ``all_engines`` holds one entry per *node*, so a multi-node engine
        (genrm_num_gpus_per_engine > num_gpus_per_node) occupies
        ``nodes_per_engine`` consecutive ranks. Only node_rank 0 of each group
        runs the SGLang HTTP server -- the followers are compute-only workers
        and answer /generate with 404 -- so stride the same way the
        ``engines`` property does and return head nodes only.

        The list is also compacted over dead engines, so callers must swap it
        and any derived round-robin state together. Scale-out candidates that
        have not passed their health check and scale-in victims that are
        draining are not routable and are skipped here -- this is the
        admission boundary of a scale operation.
        """
        results = []
        for rank in range(0, len(self.all_engines), self.nodes_per_engine):
            engine = self.all_engines[rank]
            with self._scale_lock:
                hidden = rank in self._candidate_ranks or rank in self._draining_ranks
            if engine is not None and not hidden and rank in self._engine_addr_and_ports:
                info = self._engine_addr_and_ports[rank]
                results.append((info["host"], info["port"]))
        return results

    # ------------------------------------------------------------------
    # Task 4 elastic scaling: manager-side physical lifecycle.
    #
    # The contract with the component is intentionally small:
    #   begin_scale_op(request_id, direction, target)   - register parameters
    #   execute_genrm_scale_out/in(request_id)          - fire-and-forget hook
    #   get_scale_progress(request_id)                  - polled by the watcher
    #   confirm_scale_drained(request_id)               - component drain proof
    #   abort_scale_op(request_id)                      - watcher deadline
    #
    # The component owns the operation registry (HTTP status queries); this
    # manager owns the physical lifecycle and reports progress only.
    # ------------------------------------------------------------------

    def begin_scale_op(self, request_id: str, direction: str, target: int) -> None:
        """Register the parameters of one scale operation before the hook."""
        with self._scale_lock:
            self._scale_op_params[request_id] = {
                "direction": direction,
                "target": int(target),
            }

    def execute_genrm_scale_out(self, request_id: str) -> None:
        """Scale-out hook: bring up (target - current) new engines, one at a
        time, each on its own placement group, published only after its health
        check passes. Runs in a daemon thread; progress via
        ``get_scale_progress``."""
        with self._scale_lock:
            self._scale_progress[request_id] = self._new_progress("CREATING")
            self._scale_abort[request_id] = threading.Event()
        threading.Thread(
            target=self._scale_out_lifecycle, args=(request_id,), daemon=True,
            name=f"genrm-scale-out-{request_id}",
        ).start()

    def execute_genrm_scale_in(self, request_id: str) -> None:
        """Scale-in hook: drain and remove (current - target) newest scale-added
        engines one at a time. Admission closes as soon as a victim enters
        ``_draining_ranks``; actual removal waits for the component's drain
        confirmation (its in-flight counter for the victim reached zero)."""
        with self._scale_lock:
            self._scale_progress[request_id] = self._new_progress("DRAINING")
            self._scale_abort[request_id] = threading.Event()
        threading.Thread(
            target=self._scale_in_lifecycle, args=(request_id,), daemon=True,
            name=f"genrm-scale-in-{request_id}",
        ).start()

    def get_scale_progress(self, request_id: str) -> dict:
        """Snapshot of one operation's progress (empty dict while unknown)."""
        with self._scale_lock:
            return dict(self._scale_progress.get(request_id) or {})

    def confirm_scale_drained(self, request_id: str) -> None:
        """Component-side drain proof: no in-flight request targets the
        current victim any more."""
        with self._scale_lock:
            event = self._scale_drain_confirmed.get(request_id)
        if event is not None:
            event.set()

    def abort_scale_op(self, request_id: str) -> None:
        """Ask the lifecycle thread to stop at the next safe point. Draining
        victims stay unroutable and keep their resources (failure isolation);
        no new engine is created after the abort."""
        with self._scale_lock:
            event = self._scale_abort.get(request_id)
        if event is not None:
            event.set()

    # -- internals -------------------------------------------------------

    def _new_progress(self, phase: str) -> dict:
        current = ready = self._live_published_count()
        return {
            "phase": phase,
            "created": 0,
            "removed": 0,
            "failed": 0,
            "current": current,
            "ready": ready,
            "victim": None,
            "error": None,
        }

    def _live_published_count(self) -> int:
        count = 0
        for rank in range(0, len(self.all_engines), self.nodes_per_engine):
            with self._scale_lock:
                hidden = rank in self._candidate_ranks or rank in self._draining_ranks
            if self.all_engines[rank] is not None and not hidden:
                count += 1
        return count

    def _update_progress(self, request_id: str, **fields) -> None:
        with self._scale_lock:
            progress = self._scale_progress.get(request_id)
            if progress is None:
                return
            progress.update(fields)
            progress["current"] = self._live_published_count()
            progress["ready"] = progress["current"]

    def _scale_target(self, request_id: str):
        with self._scale_lock:
            params = self._scale_op_params.get(request_id) or {}
        return params.get("target"), params.get("direction")

    def _create_scale_pg(self):
        """Create one dedicated single-GPU placement group for a scale-out
        engine (RFC: new replicas request free resources on their own PG)."""
        from ray.util.placement_group import placement_group, remove_placement_group, wait_for_ready

        pg = placement_group([{"GPU": 1.0, "CPU": 2.0}], strategy="STRICT_PACK")
        if not wait_for_ready(pg, timeout_s=120):
            remove_placement_group(pg)
            raise RuntimeError("scale-out placement group did not become ready within 120s")
        # Local bundle/gpu indices: the engine actor sees exactly the one GPU
        # of this bundle, so base_gpu_id 0 is the correct local index.
        return (pg, [0], [0])

    def _scale_out_lifecycle(self, request_id: str) -> None:
        abort = self._scale_abort[request_id]
        target, direction = self._scale_target(request_id)
        if direction != "scale_out" or target is None:
            self._update_progress(request_id, phase="FAILED", error="scale-out parameters were not registered")
            return
        if self.num_gpu_per_engine != 1:
            self._update_progress(
                request_id, phase="FAILED",
                error=f"elastic scale-out supports single-GPU engines only (num_gpu_per_engine={self.num_gpu_per_engine})",
            )
            return

        created = 0
        try:
            while self._live_published_count() < target:
                if abort.is_set():
                    raise RuntimeError("aborted")
                self._update_progress(request_id, phase="CREATING")
                self._scale_out_add_one(request_id)
                created += 1
                self._update_progress(request_id, created=created)
            self._update_progress(request_id, phase="ACTIVE", created=created, failed=0)
        except Exception as exc:
            logger.exception(f"GenRM scale-out {request_id} failed")
            # First failure stops the operation (RFC): keep what was
            # published, report PARTIAL when at least one replica made it.
            self._update_progress(request_id, phase="PARTIAL" if created > 0 else "FAILED",
                                  created=created, failed=1, error=str(exc))

    def _scale_out_add_one(self, request_id: str) -> int:
        """Bring up one candidate engine and publish it after its health check.
        Raises on failure after cleaning the candidate up. Progress phases may
        oscillate per engine (CREATING -> HEALTH_CHECKING); the component's
        watcher maps them onto the registry's monotonic chain."""
        pg_tuple = self._create_scale_pg()
        with self._scale_lock:
            rank = len(self.all_engines)
            self.all_engines.append(None)
            self._scale_placements[rank] = pg_tuple
            self._candidate_ranks.add(rank)
        try:
            # _init_engines creates the actor on the scale PG, inits it, and
            # on failure kills it and removes the owned PG for us.
            self._init_engines([rank])
            self._update_progress(request_id, phase="HEALTH_CHECKING")
            engine = self.all_engines[rank]
            healthy = False
            try:
                healthy = ray.get(engine.health_generate.remote(), timeout=120)
            except Exception as exc:
                logger.warning(f"GenRM scale-out health check raised for rank={rank}: {exc}")
            if not healthy:
                raise RuntimeError(f"health check failed for scaled-out engine rank={rank}")
            with self._scale_lock:
                self._candidate_ranks.discard(rank)
                self._scale_added_ranks.append(rank)
            logger.info(f"GenRM scale-out {request_id}: engine rank={rank} published")
            return rank
        except Exception:
            with self._scale_lock:
                self._candidate_ranks.discard(rank)
                engine = self.all_engines[rank]
                self.all_engines[rank] = None
            if engine is not None:
                try:
                    ray.get(engine.shutdown.remote(), timeout=30)
                except Exception:
                    pass
                try:
                    ray.kill(engine)
                except Exception:
                    pass
            self._remove_owned_pg(rank)
            with self._scale_lock:
                self._scale_placements.pop(rank, None)
            raise

    def _scale_in_lifecycle(self, request_id: str) -> None:
        abort = self._scale_abort[request_id]
        target, direction = self._scale_target(request_id)
        if direction != "scale_in" or target is None:
            self._update_progress(request_id, phase="FAILED", error="scale-in parameters were not registered")
            return

        removed = 0
        try:
            while self._live_published_count() > target:
                if abort.is_set():
                    raise RuntimeError("aborted")
                with self._scale_lock:
                    candidates = [
                        r for r in self._scale_added_ranks
                        if r not in self._draining_ranks and self.all_engines[r] is not None
                    ]
                if not candidates:
                    raise RuntimeError("no scale-added engine left to remove")
                victim = max(candidates)  # newest first (RFC)
                # Register the drain event before the victim becomes
                # visible: the watcher can observe DRAINING + victim and
                # confirm within the same poll cycle, so the event must
                # already exist (a dropped confirm would stall the lifecycle
                # until the drain timeout).
                event = threading.Event()
                with self._scale_lock:
                    self._scale_drain_confirmed[request_id] = event
                    self._draining_ranks.add(victim)
                    info = self._engine_addr_and_ports.get(victim) or {}
                victim_addr = [info.get("host"), info.get("port")]
                self._update_progress(request_id, victim=victim_addr)
                # admission is closed for the victim (get_engine_hosts_ports
                # skips it from here on); wait for the component's drain proof.
                if not event.wait(timeout=self._scale_drain_timeout_s):
                    # Keep the victim unroutable with resources retained;
                    # recovery is reconcile / shutdown, never auto-restore.
                    raise RuntimeError("drain confirmation timed out")
                if abort.is_set():
                    raise RuntimeError("aborted")
                self._update_progress(request_id, phase="REMOVING", victim=victim_addr)
                self._retire_engines([victim])
                with self._scale_lock:
                    self._draining_ranks.discard(victim)
                    if victim in self._scale_added_ranks:
                        self._scale_added_ranks.remove(victim)
                    self._scale_placements.pop(victim, None)
                removed += 1
                self._update_progress(request_id, phase="DRAINING", removed=removed, victim=None)
            self._update_progress(request_id, phase="COMPLETED", removed=removed, failed=0)
        except Exception as exc:
            logger.exception(f"GenRM scale-in {request_id} failed")
            self._update_progress(request_id, phase="FAILED", removed=removed, failed=1, error=str(exc))
        finally:
            with self._scale_lock:
                self._scale_drain_confirmed.pop(request_id, None)

    # ------------------------------------------------------------------
    # MultiEngineManager hooks.
    # ------------------------------------------------------------------

    def _resolve_placement(self, rank):
        with self._scale_lock:
            scale_pg = self._scale_placements.get(rank)
        if scale_pg is not None:
            # Engine slot created by a scale-out operation: it owns its own
            # dedicated placement group (removed on retire/shutdown).
            return scale_pg, True, 0
        gpu_idx = rank * self.num_gpu_per_engine + self.bundle_offset
        shared_with_rollout = getattr(self.args, "_genrm_colocate_with_rollout", False)
        if not self.args.fully_async and not shared_with_rollout:
            gpu_idx += self.args.rollout_num_gpus

        return self.pg, False, gpu_idx

    def _ray_resource_kwargs(self, rank):
        # Lower default fractional-GPU footprint when sharing bundles with
        # rollout (rollout uses 0.2 per actor; 0.2 + 0.2 risks Ray scheduler
        # rejection).
        shared_with_rollout = getattr(self.args, "_genrm_colocate_with_rollout", False)
        default_ray_num_gpus = 0.1 if shared_with_rollout else 0.2
        num_gpus = getattr(self.args, "genrm_ray_num_gpus", default_ray_num_gpus)
        return {"num_cpus": num_gpus, "num_gpus": num_gpus}

    def _build_engine_env_vars(self):
        env_vars = {name: "1" for name in NOSET_VISIBLE_DEVICES_ENV_VARS_LIST} | {
            "SGL_JIT_DEEPGEMM_PRECOMPILE": "false",
            "SGLANG_JIT_DEEPGEMM_PRECOMPILE": "false",
            # See rollout.py: recent SGLang reads SGLANG_ENABLE_TP_MEMORY_INBALANCE_CHECK
            # (default True) and the deprecation shim value-copies SGL_DISABLE_* into it,
            # so the old DISABLE vars re-enable the check. Set ENABLE=false directly.
            "SGLANG_ENABLE_TP_MEMORY_INBALANCE_CHECK": "false",
            "SGLANG_MEMORY_SAVER_CUDA_GRAPH": "true",
            "SGLANG_BATCH_INVARIANT_OPS_ENABLE_MM_FALLBACK_VARIANT": "true",
            "SGLANG_ENABLE_HEALTH_ENDPOINT_GENERATION": "false",
            "SGLANG_ENABLE_STRICT_MEM_CHECK_DURING_IDLE": "false",
            # NOTE: disable custom all-reduce-v2, same as rollout.py — avoids
            # custom_all_reduce.cuh:37: CUDA error: invalid argument during CUDA graph capture.
            "SGLANG_OPT_USE_CUSTOM_ALL_REDUCE_V2": "0",
        }
        if getattr(self.args, "fp16", False):
            env_vars["SGLANG_MAMBA_CONV_DTYPE"] = "float16"
        return env_vars

    def _allocate_engine_addr_and_ports(self, *, new_engines):
        return _allocate_genrm_engine_addr_and_ports(
            args=self.args,
            new_engines=new_engines,
            port_window_index=self.port_window_index,
        )


def _allocate_genrm_engine_addr_and_ports(*, args, new_engines, port_window_index=0):
    """Allocate network addresses and ports for genRM engines.

    Similar to _allocate_rollout_engine_addr_and_ports_normal but for genRM.

    ``port_window_index`` selects a disjoint range per GenRM instance (multi-instance
    --genrm-instances): every instance is a separate GenRMManager that probes
    for free ports independently and in parallel during Serve replica
    initialization, so two instances starting from the same base port can both
    see a given port as free (probe-then-bind race) and then collide when
    their SGLang servers actually bind it.
    """
    window_start = _GENRM_PORT_BASE + port_window_index * _GENRM_PORT_WINDOW_SIZE
    window_end = window_start + _GENRM_PORT_WINDOW_SIZE - 1
    if port_window_index < 0 or window_end > _MAX_PORT:
        raise ValueError(
            f"GenRM port window index {port_window_index} is out of range; "
            f"at most {(_MAX_PORT - _GENRM_PORT_BASE + 1) // _GENRM_PORT_WINDOW_SIZE} instances are supported."
        )

    num_engines_per_node = max(1, min(args.num_gpus_per_node, args.genrm_num_gpus) // args.genrm_num_gpus_per_engine)
    addr_and_ports = {}

    visited_nodes = set()
    for rank, engine in new_engines:
        if rank // num_engines_per_node in visited_nodes:
            continue
        visited_nodes.add(rank // num_engines_per_node)
        num_engines_on_this_node = num_engines_per_node - (rank % num_engines_per_node)

        def get_addr_and_ports(engine):
            # Use a different, bounded port range from rollout (15000).
            start_port = window_start

            def port(consecutive=1):
                nonlocal start_port
                _, port = ray.get(
                    engine._get_current_node_ip_and_free_port.remote(
                        start_port=start_port,
                        consecutive=consecutive,
                        max_port=window_end,
                    )
                )
                start_port = port + consecutive
                return port

            def addr():
                addr, _ = ray.get(engine._get_current_node_ip_and_free_port.remote())
                return addr

            return addr, port

        get_addr, get_port = get_addr_and_ports(engine)

        for i in range(num_engines_on_this_node):
            current_rank = rank + i
            addr_and_ports.setdefault(current_rank, {})
            addr_and_ports[current_rank]["host"] = get_addr()
            addr_and_ports[current_rank]["port"] = get_port()
            addr_and_ports[current_rank]["nccl_port"] = get_port()

        if args.genrm_num_gpus_per_engine > args.num_gpus_per_node:
            num_node_per_engine = args.genrm_num_gpus_per_engine // args.num_gpus_per_node
            if rank % num_node_per_engine == 0:
                # First node in the engine, allocate dist_init_addr port
                dist_init_addr = f"{get_addr()}:{get_port(30 + args.sglang_dp_size)}"
                for i in range(num_node_per_engine):
                    addr_and_ports.setdefault(rank + i, {})
                    addr_and_ports[rank + i]["dist_init_addr"] = dist_init_addr
        else:
            for i in range(num_engines_on_this_node):
                addr_and_ports.setdefault(rank + i, {})
                addr_and_ports[rank + i]["dist_init_addr"] = f"{get_addr()}:{get_port(30 + args.sglang_dp_size)}"

    for rank, _ in new_engines:
        for key in ["port", "nccl_port", "dist_init_addr"]:
            assert key in addr_and_ports[rank], f"GenRM engine rank={rank} {key} is not set."
        logger.info(f"Ports for genRM engine rank={rank}: {addr_and_ports[rank]}")

    return addr_and_ports
