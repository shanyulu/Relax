# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Build a self-contained, measured-sample replay for the Task 11 demo."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from diagnosis import Diagnosis


CASES = ("control", "compute_slow", "compute_recovery", "load_skew", "host_stall")
STAGES = ("forward", "backward", "collective_interval", "optimizer")


def replay_payload(result: dict[str, Any]) -> dict[str, Any]:
    world = result["environment"]["world_size"]
    interval = result["config"]["interval"]
    samples = [row for row in result["samples"] if row["case"] in CASES]
    if not samples:
        raise ValueError("result has no diagnostic samples")
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in samples:
        grouped[row["case"], row["step"]].append(row)
    cases = []
    for case in CASES:
        steps = sorted(step for name, step in grouped if name == case)
        if not steps:
            continue
        frames = []
        for step in steps:
            rows = sorted(grouped[case, step], key=lambda row: row["rank"])
            stage_sets = {tuple(sorted(row.get("stages_ms", {}))) for row in rows}
            same_stages = len(stage_sets) == 1 and stage_sets != {()}
            workloads = [row["workload"] for row in rows]
            reason = None
            if len(rows) != world:
                reason = "missing_peer"
            elif len({row["cohort"] for row in rows}) != 1:
                reason = "cohort_mismatch"
            elif not same_stages:
                reason = "stage_set_mismatch"
            elif max(workloads) > 1.05 * min(workloads):
                reason = "workload_mismatch"
            frames.append({"step": step, "rows": rows, "comparable": reason is None, "reason": reason})
        cases.append({"name": case, "frames": frames})
    alerts = [row for row in result["diagnosis"]["alerts"] if row["case"] in CASES]
    uncertain = [row for row in result["diagnosis"]["uncertain"] if row["case"] in CASES]
    missing = None
    recovered_at = None
    recovery = next((case for case in cases if case["name"] == "compute_recovery"), None)
    recovery_alerts = [
        row for row in alerts if row["case"] == "compute_recovery" and row["rank"] == 1 and row["stage"] == "forward"
    ]
    if recovery and recovery_alerts:
        streak = 0
        for frame in recovery["frames"]:
            if frame["step"] <= recovery_alerts[0]["step"] or not frame["comparable"]:
                continue
            by_rank = {row["rank"]: row for row in frame["rows"]}
            if 0 not in by_rank or 1 not in by_rank:
                streak = 0
                continue
            peer = by_rank[0]["stages_ms"]["forward"]
            observed = by_rank[1]["stages_ms"]["forward"]
            slow = observed >= peer * result["config"]["ratio"] and observed - peer >= result["config"]["absolute_ms"]
            streak = 0 if slow else streak + 1
            if streak == 2:
                recovered_at = frame["step"]
                break
    if recovery and len(recovery["frames"]) >= 3:
        target = recovery["frames"][len(recovery["frames"]) // 2]["step"]
        dropped = next(
            (row for row in samples if row["case"] == "compute_recovery" and row["step"] == target and row["rank"] == 1),
            None,
        )
        if dropped:
            detector = Diagnosis(world, ratio=result["config"]["ratio"],
                                 absolute_ms=result["config"]["absolute_ms"], sampling_interval=interval)
            for row in sorted(
                (sample for sample in samples if sample is not dropped),
                key=lambda row: (row["case"], row["step"], row["rank"]),
            ):
                detector.ingest(row)
            summary = detector.summary()
            missing = {
                "case": "compute_recovery", "step": target, "rank": 1,
                "uncertain": [row for row in summary["uncertain"] if row["case"] == "compute_recovery"],
                "alerts": [row for row in summary["alerts"] if row["case"] == "compute_recovery"],
            }
    return {
        "scope": result["scope"],
        "source_sha256": result["source_sha256"],
        "world_size": world,
        "interval": interval,
        "telemetry": result["telemetry"],
        "paired_parameter_mismatches": result["paired_parameter_mismatches"],
        "max_paired_final_loss_difference": result["max_paired_final_loss_difference"],
        "cases": cases,
        "alerts": alerts,
        "uncertain": uncertain,
        "missing_peer_simulation": missing,
        "observed_forward_recovery_step": recovered_at,
        "stages": STAGES,
    }


HTML = r'''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Relax · Straggler replay</title>
<style>
:root{color-scheme:dark;font-family:Inter,ui-sans-serif,system-ui,sans-serif;background:#09131d;color:#e9f2f5}
*{box-sizing:border-box}body{margin:0}main{max-width:1260px;margin:auto;padding:38px 24px 70px}
header{display:flex;justify-content:space-between;align-items:start;gap:25px;border-bottom:1px solid #27404d;padding-bottom:25px}
.eyebrow{font-size:12px;letter-spacing:.16em;color:#66d1bf;text-transform:uppercase;font-weight:700}
h1{font-size:clamp(30px,4vw,48px);letter-spacing:-.04em;margin:8px 0 7px}h2{font-size:19px;margin:0 0 16px}
p{color:#aec3cd;line-height:1.55;margin:0}.pill{border:1px solid #397768;color:#8df0d1;border-radius:999px;padding:8px 13px;white-space:nowrap;font-size:12px}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:25px 0}.card,.panel{background:#101f2a;border:1px solid #29414d;border-radius:16px}
.card{padding:18px}.card span{display:block;color:#9bb4bf;font-size:12px}.card strong{font-size:26px;display:block;margin-top:9px;font-variant-numeric:tabular-nums}
.panel{padding:23px;margin:16px 0}.controls{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0}.controls button,.mode{background:#192f3c;color:#d5e5e9;border:1px solid #34525e;border-radius:9px;padding:9px 13px;cursor:pointer;font:inherit;font-size:13px}
.controls button.active,.mode.active{background:#166e62;color:#fff;border-color:#40ad9b}.row{display:flex;justify-content:space-between;gap:16px;align-items:center}
input[type=range]{width:100%;accent-color:#53ceb6;margin:20px 0 8px}.muted{color:#8da5b2;font-size:12px}.step{font-variant-numeric:tabular-nums;color:#8af2d3;font-weight:700}
.table{display:grid;grid-template-columns:90px repeat(4,minmax(0,1fr)) 100px;gap:1px;background:#29414d;overflow:hidden;border-radius:10px;margin-top:20px}
.cell{background:#122532;padding:13px;font-size:13px;font-variant-numeric:tabular-nums}.head{color:#93aebb;background:#1b3440;font-size:11px;text-transform:uppercase;letter-spacing:.04em}
.bar{display:block;height:5px;margin-top:9px;background:#244655;border-radius:8px;overflow:hidden}.bar i{display:block;height:100%;background:#48b9ac}.warn .bar i{background:#f6a758}.rank{font-weight:700}.tag{font-size:11px;color:#b0c6cc}
.finding{border-left:3px solid #57caba;padding:12px 16px;background:#17303b;border-radius:0 8px 8px 0;margin-top:17px;line-height:1.5;font-size:14px}.finding.warn{border-color:#f2a45a;background:#362c29}.finding.unknown{border-color:#829bac}
svg{display:block;width:100%;height:220px;margin:18px 0 0;background:#0d1d28;border-radius:10px}.legend{display:flex;gap:19px;font-size:12px;color:#a4bec8;margin-top:9px}
.legend b{display:inline-block;width:12px;height:3px;vertical-align:middle;margin-right:6px}.footer{font-size:12px;color:#89a3af;border-top:1px solid #27404d;margin-top:22px;padding-top:18px;line-height:1.6}
@media(max-width:750px){.kpis{grid-template-columns:repeat(2,1fr)}.table{overflow-x:auto;display:block}.cell{display:inline-block;min-width:115px}.row,header{align-items:start;flex-direction:column}}
</style>
<main>
<header><div><div class="eyebrow">Relax / Task 11 / measured replay</div><h1>Where does the step slow down?</h1><p>Rank and stage intervals from a local two-GPU run. Select a scenario, then scrub its sampled steps.</p></div><div class="pill">Standalone mechanism · no Relax integration</div></header>
<section class="kpis"><div class="card"><span>Samples received</span><strong id="samples"></strong></div><div class="card"><span>World size</span><strong id="world"></strong></div><div class="card"><span>Final parameter mismatches</span><strong id="params"></strong></div><div class="card"><span>Max paired loss difference</span><strong id="loss"></strong></div></section>
<section class="panel"><div class="row"><div><div class="eyebrow">01 / Observation</div><h2 style="margin-top:6px">Compare equivalent ranks</h2></div><div id="position" class="step"></div></div>
<div id="cases" class="controls"></div><input id="step" type="range" min="0" value="0"><p id="caseNote" class="muted"></p>
<div id="rankTable" class="table"></div><div id="finding" class="finding"></div></section>
<section class="panel"><div class="row"><div><div class="eyebrow">02 / Trace</div><h2 style="margin-top:6px">Stage duration across sampled steps</h2></div><select id="stage" class="mode"></select></div><svg id="plot" viewBox="0 0 900 220" role="img" aria-label="Stage duration by rank"></svg><div class="legend"><span><b style="background:#57caba"></b>Rank 0</span><span><b style="background:#f6a758"></b>Rank 1</span></div></section>
<section class="panel"><div class="row"><div><div class="eyebrow">03 / Failure drill</div><h2 style="margin-top:6px">Drop one report at the receiver</h2></div><button id="missing" class="mode">Simulate missing peer</button></div><p id="drill" style="margin-top:10px"></p></section>
<div class="footer">CUDA Event stream intervals can include peer wait. The host-stall case may alert on backward with cause undetermined. Receiver-drop mode is a counterfactual replay of recorded samples. These data do not measure MetricsService delivery latency, a Relax recipe, or the official &lt;0.5% target. Source SHA-256 values are embedded in this file.</div>
</main><script id="payload" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('payload').textContent), names={control:'Normal',compute_slow:'Extra forward',compute_recovery:'Slow → recovered',load_skew:'Unequal workload',host_stall:'Host stall'};
let selected=D.cases[0], index=0, drop=false; const $=id=>document.getElementById(id);
$('samples').textContent=`${D.telemetry.received}/${D.telemetry.planned}`;$('world').textContent=D.world_size;
$('params').textContent=D.paired_parameter_mismatches;$('loss').textContent=D.max_paired_final_loss_difference;
for(const name of D.stages){let option=document.createElement('option');option.value=name;option.textContent=name.replace('_interval',' interval');$('stage').append(option)}
function node(tag,text,cls){const n=document.createElement(tag);n.textContent=text;if(cls)n.className=cls;return n}
function render(){const frames=selected.frames,frame=frames[index],step=frame.step,m=D.missing_peer_simulation;
 const affected=drop&&m&&selected.name===m.case,rows=affected&&step===m.step?frame.rows.filter(r=>r.rank!==m.rank):frame.rows;
 $('position').textContent=`step ${step} · sample ${index+1}/${frames.length}`;$('step').max=frames.length-1;$('step').value=index;
 $('caseNote').textContent=selected.name==='compute_recovery'?'One measured run: rank 1 slows only in the middle half, then returns to baseline.':selected.name==='load_skew'?'Workload differs; peer-relative timing is withheld.':'Measured CUDA stream intervals; stage duration is not a root-cause verdict.';
 const table=$('rankTable');table.replaceChildren();['Rank',...D.stages.map(x=>x.replace('_interval',' interval')),'Workload'].forEach(s=>table.append(node('div',s,'cell head')));
 const maxByStage=Object.fromEntries(D.stages.map(s=>[s,Math.max(.001,...rows.map(r=>r.stages_ms[s]||0))]));
 for(let rank=0;rank<D.world_size;rank++){const row=rows.find(r=>r.rank===rank);table.append(node('div',`Rank ${rank}`,'cell rank'));
 for(const stage of D.stages){const cell=node('div',row&&stage in row.stages_ms?`${row.stages_ms[stage].toFixed(3)} ms`:'—','cell');
 if(row&&stage in row.stages_ms){const bar=node('span','','bar'),fill=node('i','');fill.style.width=`${100*row.stages_ms[stage]/maxByStage[stage]}%`;bar.append(fill);cell.append(bar)}table.append(cell)}
 table.append(node('div',row?String(row.workload):'missing','cell'))}
 const sourceAlerts=affected?m.alerts:D.alerts,sourceUncertain=affected?m.uncertain:D.uncertain;
 let alert=sourceAlerts.filter(a=>a.case===selected.name&&a.step===step), uncertain=sourceUncertain.filter(a=>a.case===selected.name&&a.step===step);
 const finding=$('finding');finding.className='finding';
 if(affected&&step===m.step){finding.textContent='Simulated receiver drop: rank 1 report missing. This window is incomplete; the next complete window records missing_peer and resets persistence.';finding.classList.add('unknown')}
 else if(alert.length){finding.textContent=alert.map(a=>`Rank ${a.rank} ${a.stage}: ${a.observed_ms} ms vs peer ${a.peer_median_ms} ms (${a.ratio}×). Cause: ${a.cause}.`).join(' ');finding.classList.add('warn')}
 else if(uncertain.length){finding.textContent=`Not comparable: ${[...new Set(uncertain.map(x=>x.reason))].join(', ')}.`;finding.classList.add('unknown')}
 else if(selected.name==='compute_recovery'&&D.observed_forward_recovery_step===step){finding.textContent='Rank 1 forward interval has returned to peer range for two samples. This is derived from measurements; the detector emits no explicit resolution event.'}
 else finding.textContent=frame.comparable?'No new persistent peer-relative alert at this step. This does not establish that all ranks are healthy.':`Not comparable: ${frame.reason||'insufficient evidence'}.`;
 drawPlot();renderDrill()}
function drawPlot(){const stage=$('stage').value,svg=$('plot'),frames=selected.frames,ns='http://www.w3.org/2000/svg';svg.replaceChildren();
 const values=frames.flatMap(f=>f.rows.map(r=>r.stages_ms[stage]||0)),max=Math.max(.001,...values)*1.12;
 function add(tag,attrs,label){const e=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);if(label)e.textContent=label;svg.append(e)}
 for(let i=0;i<4;i++){let y=20+i*53;add('line',{x1:44,y1:y,x2:880,y2:y,stroke:'#25404d'})}
 for(let rank=0;rank<D.world_size;rank++){let segment=[];
 function flush(){if(segment.length>1)add('polyline',{points:segment.join(' '),fill:'none',stroke:rank===0?'#57caba':'#f6a758','stroke-width':2.5,'stroke-linejoin':'round'});segment=[]}
 frames.forEach((f,i)=>{const missing=drop&&D.missing_peer_simulation&&selected.name===D.missing_peer_simulation.case&&f.step===D.missing_peer_simulation.step&&rank===D.missing_peer_simulation.rank;
 const row=missing?null:f.rows.find(r=>r.rank===rank);if(!row||!(stage in row.stages_ms)){flush();return}
 const x=44+i*836/Math.max(1,frames.length-1),y=201-178*(row.stages_ms[stage]/max);segment.push(`${x},${y}`)});flush()}
 if(selected.name==='compute_recovery'&&stage==='forward'){
 const start=D.alerts.find(a=>a.case==='compute_recovery'&&a.rank===1&&a.stage==='forward');
 for(const mark of [[start?.step,'detected'],[D.observed_forward_recovery_step,'back in range']]){
 if(mark[0]===undefined||mark[0]===null)continue;const at=frames.findIndex(f=>f.step===mark[0]);if(at<0)continue;
 const x=44+at*836/Math.max(1,frames.length-1);add('line',{x1:x,y1:18,x2:x,y2:202,stroke:'#7690a1','stroke-dasharray':'3 5'});
 add('text',{x:x+5,y:34,fill:'#a9bdc8','font-size':11},mark[1])}}
 const x=44+index*836/Math.max(1,frames.length-1);add('line',{x1:x,y1:19,x2:x,y2:202,stroke:'#e8f3f5','stroke-dasharray':'4 5',opacity:.7})}
function renderDrill(){const m=D.missing_peer_simulation,btn=$('missing');btn.disabled=!m;btn.classList.toggle('active',drop);
 $('drill').textContent=!m?'Run a result with the recovery scenario to enable this drill.':drop?`Counterfactual only: omit rank ${m.rank} at step ${m.step} of the recovery run. Receiver diagnosis reports ${m.uncertain.filter(x=>x.reason==='missing_peer').length} missing-peer window(s); this says nothing about GPU health or training continuity.`:'Recorded run has no receiver drop. Click to replay one omitted report; no source measurements are altered.'}
function select(i){selected=D.cases[i];const first=D.alerts.find(a=>a.case===selected.name);
 index=selected.name==='compute_recovery'&&first?Math.max(0,selected.frames.findIndex(f=>f.step===first.step)):0;
 document.querySelectorAll('#cases button').forEach((b,j)=>b.classList.toggle('active',i===j));render()}
D.cases.forEach((c,i)=>{const b=node('button',names[c.name]||c.name);b.onclick=()=>select(i);$('cases').append(b)});
$('step').oninput=e=>{index=Number(e.target.value);render()};$('stage').onchange=render;
$('missing').onclick=()=>{drop=!drop;if(drop){const i=D.cases.findIndex(c=>c.name==='compute_recovery');if(i>=0){select(i);
 index=Math.max(0,selected.frames.findIndex(f=>f.step===D.missing_peer_simulation.step));render();return}}render()};
select(Math.max(0,D.cases.findIndex(c=>c.name==='compute_recovery')));
</script></html>'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = json.loads(args.result.read_text(encoding="utf-8"))
    payload = replay_payload(result)
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(HTML.replace("__DATA__", serialized), encoding="utf-8")


if __name__ == "__main__":
    main()
