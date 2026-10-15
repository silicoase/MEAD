"""Local, read-only experiment dashboard. No API calls or experiment mutations."""
import argparse
import json
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


class Progress:
    def __init__(self, batch):
        self.batch = batch
        self.streams = {}

    def snapshot(self):
        manifest = json.loads((self.batch / "manifest.json").read_text())
        rows = []
        for run in manifest["runs"]:
            state = self.streams.setdefault(run["run_id"], {
                "offset": 0, "experiments": 0, "submissions": 0, "cost": 0,
                "limited": False, "frozen": False, "reset_at": 0,
                "paused_seconds": 0, "freeze_started_at": None,
            })
            path = self.batch / run["run_id"] / "events.jsonl"
            if path.exists():
                with path.open("rb") as stream:
                    stream.seek(state["offset"])
                    while True:
                        line = stream.readline()
                        if not line or not line.endswith(b"\n"):
                            break
                        event = json.loads(line)
                        state["offset"] = stream.tell()
                        kind = event["kind"]
                        stamp = datetime.fromisoformat(event["timestamp"]).timestamp()
                        if kind == "experiment_completed":
                            state["experiments"] += 1
                        elif kind == "submission":
                            state["submissions"] += 1
                        elif kind == "provider_response_metadata":
                            state["cost"] += (event["metadata"].get("usage") or {}).get("cost") or 0
                        elif kind in {"cohort_pause_requested", "cohort_pause_started"}:
                            state["limited"] = True
                            state["reset_at"] = max(state["reset_at"], stamp + event["reset_wait_seconds"])
                            if kind == "cohort_pause_started":
                                state["frozen"] = True
                                state["freeze_started_at"] = stamp
                        elif kind == "cohort_pause_clock_resumed":
                            state.update(limited=False, frozen=False, reset_at=0,
                                         freeze_started_at=None)
                        if "paused_seconds" in event:
                            state["paused_seconds"] = event["paused_seconds"]
            config_path = self.batch / run["run_id"] / "config.json"
            config = json.loads(config_path.read_text()) if config_path.exists() else {}
            row = {"pause_limit_seconds": config.get("harness", {}).get("max_pause_seconds", 5400), **run, **{k: v for k, v in state.items() if k != "offset"}}
            if run["status"] != "running":
                row.update(limited=False, frozen=False)
            rows.append(row)
        return {"name": manifest["name"], "status": manifest["status"], "runs": rows, "server_time": time.time()}


PAGE = r'''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MEAD · Discovery garden</title>
<style>
:root{color-scheme:dark;font-family:ui-sans-serif,system-ui;background:#101622;color:#e9f0fc}*{box-sizing:border-box}body{margin:0;padding:12px;max-width:1500px;margin:auto}header{display:flex;justify-content:space-between;align-items:start;gap:12px}h1{font-size:28px;letter-spacing:-1.3px;margin:0}p{color:#a7b5cb;margin:4px 0}small{color:#a7b5cb}#connection{font-size:13px;color:#7de3b8}.stats{display:flex;gap:8px;margin:8px 0;flex-wrap:wrap}.stat{background:#1a2435;padding:8px 16px;border-radius:16px;min-width:170px}.stat strong{font-size:26px;display:block;font-variant-numeric:tabular-nums}.stat span{font-size:12px;color:#a7b5cb}.legend{display:flex;gap:16px;margin:6px 0;font-size:13px}.dot{display:inline-block;width:9px;height:9px;border-radius:3px;margin-right:7px}.mint{background:#67dfb0}.violet{background:#ba9bff}.scroll{overflow:auto}table{border-collapse:separate;border-spacing:0 2px;width:100%;min-width:850px}th{text-align:left;color:#a7b5cb;font-size:12px;font-weight:600;padding:4px 10px}td{background:#182233;padding:6px 10px;vertical-align:top}td:first-child{border-radius:12px 0 0 12px;width:165px}td:last-child{border-radius:0 12px 12px 0}.run-name{font-size:14px;font-weight:650}.set{font-size:12px;color:#a7b5cb}.count{font-size:13px;display:flex;justify-content:space-between;gap:12px;margin-bottom:4px;font-variant-numeric:tabular-nums}.tiles{display:grid;grid-template-columns:repeat(20,1fr);gap:3px}.submissions{grid-template-columns:repeat(10,1fr)}.tile{height:7px;background:#2a3549;border-radius:2px;transition:background .3s,box-shadow .3s}.submissions .tile{height:15px}.control .on{background:#67dfb0}.interact .on{background:#ba9bff}.new{box-shadow:0 0 12px currentColor}.cool{color:#ffc77d;font-size:11px;margin-top:3px;min-height:0}.limited td{border-top:1px solid #b08044;border-bottom:1px solid #b08044}.pending{opacity:.45}.pill{font-size:10px;letter-spacing:.6px;text-transform:uppercase;color:#7de3b8;display:block;margin-top:2px}.error .pill{color:#ff9caa}footer{font-size:12px;color:#a7b5cb;margin-top:8px}button{background:#25334b;color:#e9f0fc;border:1px solid #40516c;border-radius:9px;padding:9px 13px;cursor:pointer}button[aria-pressed=true]{border-color:#67dfb0}@media(max-width:650px){body{padding:8px}h1{font-size:28px}header{display:block}.stat{min-width:135px;flex:1}}@media(prefers-reduced-motion:reduce){*{transition:none!important}}
table{border-spacing:0 1px}td{padding:4px 8px;line-height:1.15}td:first-child{border-radius:4px 0 0 4px}td:last-child{border-radius:0 4px 4px 0}.tiles{gap:2px}.tile{height:5px}.submissions .tile{height:10px}.count{margin-bottom:3px}.cool:empty{display:none}.cool{margin-top:2px}.run-name{font-size:13px}.set{font-size:11px}.pill{margin-top:1px}
.cell-progress{display:flex;align-items:center;gap:8px}.cell-progress .count{flex:0 0 60px;margin:0;white-space:nowrap;font-size:12px}.cell-progress .tiles{flex:1;min-width:0}
.tile{height:4px}.submissions .tile{height:28px}.cell-progress{gap:6px}.cell-progress .count{flex-basis:54px}
table{table-layout:fixed;min-width:850px}td:first-child{width:auto}th:nth-child(n),td:nth-child(n){width:auto}.cell-progress .tiles{height:28px;grid-template-rows:repeat(5,4px)}.cell-progress .tiles.submissions{grid-template-rows:28px}.cell-progress .tiles.submissions .tile{height:28px}
table{width:100%;min-width:0}.run-name,.set,.pill{white-space:nowrap}.cell-progress .tiles{width:0}.count{font-size:11px!important}.cell-progress .count{flex-basis:50px}td{padding:4px 6px}.cool{white-space:normal}
.state-icon{color:#67dfb0}.pending .state-icon{color:#a7b5cb}.limited .state-icon{color:#ffc77d}.error .state-icon{color:#ff9caa}
</style>
<header><div><small>MEAD / EXPERIMENT TRACKER</small><h1>Discovery garden <small style="font-size:12px;letter-spacing:0">compact</small></h1><p>Every filled tile is one completed experiment or final submission.</p></div><div><div id="connection" role="status">Connecting…</div><p><button id="active" aria-pressed="false">Show active rows only</button></p></div></header>
<div class="stats"><div class="stat"><strong id="experiments">—</strong><span id="experiment-total">EXPERIMENTS</span></div><div class="stat"><strong id="submissions">—</strong><span id="submission-total">SUBMISSIONS</span></div><div class="stat"><strong id="finished">—</strong><span id="run-total">FINISHED RUNS</span></div><div class="stat"><strong id="cost">—</strong><span>REPORTED API COST</span></div></div>
<div class="legend"><span><i class="dot mint"></i>Control</span><span><i class="dot violet"></i>Interact</span><span>100 experiment tiles + 10 submission tiles per condition</span></div>
<div class="scroll"><table><colgroup><col style="width:16%"><col style="width:27%"><col style="width:15%"><col style="width:27%"><col style="width:15%"></colgroup><thead><tr><th rowspan="2">MODEL / MATCHED SET</th><th colspan="2">CONTROL</th><th colspan="2">INTERACT</th></tr><tr><th>Experiments</th><th>Submissions</th><th>Experiments</th><th>Submissions</th></tr></thead><tbody id="rows"></tbody></table></div>
<footer>Reads local logs every second. Rate-limit countdown is the latest recorded reset estimate; it can extend. Frozen time is excluded from agent active-time limits. Reported cost can omit unreported charges. Agents may submit without using all 10 experiments.</footer>
<script>
let data=null,activeOnly=false;const previous=new Map();
const names={haiku:'Claude Haiku 5.5',luna6:'GPT-6 Luna',sol61:'GPT-6.1 Sol'};
const fmt=n=>n.toLocaleString(),duration=n=>`${Math.floor(Math.max(0,n)/60)}m ${Math.floor(Math.max(0,n)%60).toString().padStart(2,'0')}s`;
function cells(run,kind){const n=kind==='experiments'?100:10,v=run[kind],old=previous.get(run.run_id+kind)??v;let tiles='';for(let i=0;i<n;i++)tiles+=`<span class="tile ${i<v?'on':''} ${i>=old&&i<v?'new':''}" title="${kind==='experiments'?'Experiment':'Submission'} ${i+1}${i<v?' completed':''}"></span>`;previous.set(run.run_id+kind,v);return `<td class="${run.condition}"><div class="cell-progress"><div class="count"><span>${v} / ${n}</span></div><div class="tiles ${kind==='submissions'?'submissions':''}" role="img" aria-label="${v} of ${n} ${kind} completed">${tiles}</div></div>${kind==='experiments'?`<div class="cool" data-run="${run.run_id}"></div>`:''}</td>`}
function clock(){if(!data)return;for(const el of document.querySelectorAll('[data-run]')){const r=data.runs.find(r=>r.run_id===el.dataset.run);if(!r.limited){el.textContent='';continue}const left=r.reset_at-Date.now()/1000;el.textContent=`${r.frozen?'❄ Rate limited':'⏳ Draining for cooldown'} · ${left>0?duration(left)+' to reset':'waiting to resume'} · ${duration(r.paused_seconds+(r.freeze_started_at?Math.max(0,Date.now()/1000-r.freeze_started_at):0))} frozen / ${duration(r.pause_limit_seconds)}`;}}
function render(){document.getElementById('experiment-total').textContent='EXPERIMENTS / '+fmt(data.runs.reduce((n,r)=>n+r.agents*r.experiment_budget,0));document.getElementById('submission-total').textContent='SUBMISSIONS / '+fmt(data.runs.reduce((n,r)=>n+r.agents,0));document.getElementById('run-total').textContent='FINISHED RUNS / '+data.runs.length;const pairs=new Map();for(const r of data.runs){const key=r.model_key+'-'+r.repetition;if(!pairs.has(key))pairs.set(key,{});pairs.get(key)[r.condition]=r}let html='';for(const pair of pairs.values()){const c=pair.control,i=pair.interact;if(activeOnly&&![c,i].some(r=>r.status==='running'))continue;const pending=[c,i].every(r=>r.status==='pending'),limited=c.limited||i.limited,error=[c,i].some(r=>r.status==='error');html+=`<tr class="${pending?'pending':''} ${limited?'limited':''} ${error?'error':''}"><td><div class="run-name"><span class="state-icon" title="${error?'Needs attention':limited?'Cooling off':pending?'Queued':[c,i].every(r=>r.status==='finished')?'Complete':'Active'}" aria-label="${error?'Needs attention':limited?'Cooling off':pending?'Queued':[c,i].every(r=>r.status==='finished')?'Complete':'Active'}">${error?'⚠':limited?'❄':pending?'○':[c,i].every(r=>r.status==='finished')?'✓':'●'}</span> ${names[c.model_key]||c.model_key}</div><div class="set">Matched set ${String(c.repetition).padStart(2,'0')}</div></td>${cells(c,'experiments')}${cells(c,'submissions')}${cells(i,'experiments')}${cells(i,'submissions')}</tr>`}document.getElementById('rows').innerHTML=html;for(const key of ['experiments','submissions'])document.getElementById(key).textContent=fmt(data.runs.reduce((s,r)=>s+r[key],0));document.getElementById('finished').textContent=data.runs.filter(r=>r.status==='finished').length;document.getElementById('cost').textContent='$'+data.runs.reduce((s,r)=>s+r.cost,0).toFixed(3);clock()}
async function refresh(){try{const response=await fetch('/state',{cache:'no-store'});if(!response.ok)throw Error();data=await response.json();render();document.getElementById('connection').textContent=`● ${data.status} · updated ${new Date().toLocaleTimeString()}`;}catch{document.getElementById('connection').textContent='⚠ Connection lost · showing last update'}finally{setTimeout(refresh,1000)}}
document.getElementById('active').onclick=function(){activeOnly=!activeOnly;this.setAttribute('aria-pressed',activeOnly);if(data)render()};setInterval(clock,250);refresh();
</script></html>'''


def serve(batch, port):
    progress = Progress(batch)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                if self.path.split("?", 1)[0] == "/state":
                    body = json.dumps(progress.snapshot()).encode()
                    content_type = "application/json"
                elif self.path.split("?", 1)[0] == "/":
                    body, content_type = PAGE.encode(), "text/html; charset=utf-8"
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (OSError, ValueError):
                self.send_error(503)

        def log_message(self, *args):
            pass

    HTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch", type=Path)
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    serve(args.batch, args.port)
