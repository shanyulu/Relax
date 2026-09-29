# C3 public-input reproduction — product `927c5de`

This directory retains both 48-step arms: the verdict/envelope JSONL and
collector/runtime status in deterministic `straggler.tar.gz` archives, plus
the TensorBoard event file, manifest and job log. The
public job logs differ from the original files only by replacement of RFC1918
addresses. `arms/*/TRANSFORM.json` records both hashes and confirms that the
native training metrics extracted before and after redaction are identical.
`PUBLIC_C3_LEDGER_20260929.json` fixes the SHA-256 of 11 direct objects and
18 archive members, and
the original hashes of the two logs. `C3_SCAN_REPORT_20260929.json` records
25/25 text-file scans with zero findings; the two TensorBoard event files are
binary and are checked by their hashes and scalar extraction.

From a clean checkout of this evidence commit, run in a Python environment
with `tensorboard` installed:

```bash
cd evidence/..
audit_dir=$(mktemp -d /tmp/task11-c3-audit.XXXXXX)
ledger=evidence/gpu_campaign/c2p-927c5de/c3-v2/PUBLIC_C3_LEDGER_20260929.json
root=evidence/gpu_campaign/c2p-927c5de/c3-v2
jq -r '.files[] | select(.path | contains("/straggler/") | not) | "\(.public_sha256)  evidence/gpu_campaign/c2p-927c5de/c3-v2/arms/\(.path)"' "$ledger" | sha256sum -c -
mkdir -p "$audit_dir/arms"
cp -a "$root/arms/C3-healthy-on" "$audit_dir/arms/"
cp -a "$root/arms/C3-slow-on" "$audit_dir/arms/"
tar -xzf "$audit_dir/arms/C3-healthy-on/straggler.tar.gz" -C "$audit_dir/arms/C3-healthy-on"
tar -xzf "$audit_dir/arms/C3-slow-on/straggler.tar.gz" -C "$audit_dir/arms/C3-slow-on"
jq --arg prefix "$audit_dir/arms/" -r '.files[] | select(.path | contains("/straggler/")) | "\(.public_sha256)  \($prefix)\(.path)"' "$ledger" | sha256sum -c -
python3 evidence/tools/c3_analyze_927c5de.py --healthy "$audit_dir/arms/C3-healthy-on" --slow "$audit_dir/arms/C3-slow-on" --lock "$root/C3_LOCK.json" --out "$audit_dir/C3_RESULT.json"
diff -u <(jq -S 'del(.healthy_tail.job_log_sha256,.slow_tail.job_log_sha256)' "$root/C3_RESULT.json") <(jq -S 'del(.healthy_tail.job_log_sha256,.slow_tail.job_log_sha256)' "$audit_dir/C3_RESULT.json")
python3 evidence/tools/c3_platform_record.py --arm "$audit_dir/arms/C3-healthy-on" --out "$audit_dir/C3_PLATFORM_HEALTHY.json"
python3 evidence/tools/c3_platform_record.py --arm "$audit_dir/arms/C3-slow-on" --out "$audit_dir/C3_PLATFORM_SLOW.json"
diff -u <(jq -S 'del(.arm)' "$root/C3_PLATFORM_HEALTHY.json") <(jq -S 'del(.arm)' "$audit_dir/C3_PLATFORM_HEALTHY.json")
diff -u <(jq -S 'del(.arm)' "$root/C3_PLATFORM_SLOW.json") <(jq -S 'del(.arm)' "$audit_dir/C3_PLATFORM_SLOW.json")
```

The two omitted `job_log_sha256` fields refer to the original private-address
logs; each must equal the corresponding `original_sha256` in `TRANSFORM.json`.
The platform extractor's `arm` field is an absolute local path, so the two
platform comparisons omit only that field. Everything else must match exactly.
This reproduces the recorded observations, not the still-pending maintainer
decision on whether rollout-cadence export counts as realtime.
