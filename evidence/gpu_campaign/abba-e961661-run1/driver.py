import json
import pathlib
import sys

sys.path.insert(0, "/root/autodl-tmp/relax-work/task11_evidence")
import run_abba_sessions as D  # noqa: E402

# Unified acceptance protocol: the formal 6-pair AB/BA campaign at the
# preregistered product head, 48 steps per arm, SAVE=0 both arms.
EXPECTED = "e961661bbdf662016a658d0fc2283d200a899a96"
D.NUM_ROLLOUT = "48"
D.EXPECTED_HEAD = EXPECTED

OUT = pathlib.Path("/root/autodl-tmp/relax-work/task11_evidence/gpu_campaign/abba-e961661-run1")
OUT.mkdir(parents=True, exist_ok=True)

state = D.assert_clean_expected_head(EXPECTED)
print(f"[campaign] head {state['commit'][:12]} clean={not state['dirty']}", flush=True)

plan = D.arm_plan()
print(f"[campaign] {len(plan)} arms: " + ", ".join(f"{e['session']}-{e['arm']}({e['order']})" for e in plan), flush=True)

session_ports = {}
for entry in plan:
    session = entry["session"]
    prior_path = OUT / f"{session}-{entry['arm']}" / "manifest.json"
    if prior_path.exists():
        try:
            prior = json.loads(prior_path.read_text())
        except Exception:
            prior = {}
        if prior.get("valid") and prior.get("exit_code") == 0:
            print(f"[resume] {session}-{entry['arm']}: valid manifest present, skipping", flush=True)
            continue
    if session not in session_ports:
        session_ports[session] = D.free_port()
    manifest = D.run_arm(entry, OUT, session_ports[session], dry_run=False)
    if not manifest.get("valid") and not manifest.get("first_step_seen"):
        print(
            f"[retry] {session}-{entry['arm']}: pre-training failure "
            f"({manifest.get('invalid_reason')}); retrying once",
            flush=True,
        )
        D.wait_for_ray_head()
        manifest = D.run_arm(entry, OUT, session_ports[session], dry_run=False)
    print(
        f"[campaign] {session}-{entry['arm']}: exit={manifest.get('exit_code')} "
        f"valid={manifest.get('valid')} reason={manifest.get('invalid_reason')} "
        f"wall={manifest.get('wall_seconds')} envelopes={manifest.get('observer_envelopes')}",
        flush=True,
    )

print("CAMPAIGN-ARMS-DONE", flush=True)
sys.exit(0)
