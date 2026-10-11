import argparse
import collections
import csv
import html
import json
import pathlib

parser = argparse.ArgumentParser(
    description="Audit cross-provider agent termination and request/tool timing from recorded events."
)
parser.add_argument("batches", nargs="+", type=pathlib.Path)
parser.add_argument("--output", required=True, type=pathlib.Path)
args = parser.parse_args()
ROOT = pathlib.Path(__file__).resolve().parents[1]
rows = []
rollouts = []
for batch in args.batches:
    for p in sorted(batch.glob("*/summary.json")):
        s = json.loads(p.read_text())
        es = [json.loads(line) for line in (p.parent / "events.jsonl").open()]
        conf = es[0]["config"]
        for a in s["agents"]:
            aes = [e for e in es if e.get("agent") == a["agent"]]
            queues = []
            apis = []
            req = None
            started = None
            pendtool = None
            tooltime = 0
            errors = []
            pyempty = 0
            codes = collections.Counter()
            finishes = collections.Counter()
            receipts = []
            for e in aes:
                k = e["kind"]
                t = e["elapsed_seconds"]
                if k == "model_request":
                    req = t
                    started = None
                elif k == "provider_request_started":
                    if req is not None:
                        queues.append(t - req)
                    started = t
                elif k == "provider_response_metadata":
                    if started is not None:
                        apis.append(t - started)
                    req = started = None
                    receipts.append(e)
                    finishes.update([e["metadata"]["choices"][0]["finish_reason"]])
                elif k == "provider_request_failed":
                    if started is not None:
                        apis.append(t - started)
                    req = started = None
                elif k == "provider_request_retry":
                    req = t + e["backoff_seconds"]
                elif k == "tool_called":
                    pendtool = e
                    if e["tool"] == "python":
                        codes.update([e["arguments"].get("code", "")])
                elif k == "tool_result":
                    if pendtool:
                        tooltime += t - pendtool["elapsed_seconds"]
                    pendtool = None
                    r = e.get("result")
                    if (
                        e["tool"] == "python"
                        and isinstance(r, dict)
                        and not r.get("stdout", r.get("output", ""))
                        and r.get("exit_code") == 0
                    ):
                        pyempty += 1
                    if e.get("error") or (
                        isinstance(r, dict) and (r.get("error") or r.get("exit_code", 0) != 0)
                    ):
                        errors.append(
                            {
                                "sequence": e["sequence"],
                                "tool": e["tool"],
                                "result": r,
                                "error": e.get("error"),
                            }
                        )
            end = next(
                (e["elapsed_seconds"] for e in reversed(aes) if e["kind"] == "agent_finished"),
                aes[-1]["elapsed_seconds"],
            )
            st = next((e["elapsed_seconds"] for e in aes if e["kind"] == "agent_started"), None)
            pending = {"state": "none", "seconds": 0}
            if req is not None:
                if started is None:
                    pending = {"state": "local_request_queue", "seconds": end - req}
                    queues.append(end - req)
                else:
                    pending = {"state": "provider_inflight", "seconds": end - started}
                    apis.append(end - started)
            elif pendtool:
                pending = {
                    "state": "tool_inflight",
                    "tool": pendtool["tool"],
                    "seconds": end - pendtool["elapsed_seconds"],
                }
            lastresp = next((e for e in reversed(aes) if e["kind"] == "model_response"), None)
            lastmeta = receipts[-1] if receipts else None
            row = {
                "run": p.parent.name,
                "agent": a["agent"],
                "reason": a["reason"],
                "experiments_completed": a.get("experiments_completed"),
                "duration_seconds": None if st is None else end - st,
                "model_requests": sum(e["kind"] == "model_request" for e in aes),
                "receipts": len(receipts),
                "queue_seconds": sum(queues),
                "api_seconds": sum(apis),
                "tool_seconds": tooltime,
                "pending": pending,
                "finish_reasons": dict(finishes),
                "tools": dict(
                    collections.Counter(e["tool"] for e in aes if e["kind"] == "tool_called")
                ),
                "tool_errors": errors,
                "empty_successful_python_results": pyempty,
                "most_repeated_python": codes.most_common(1),
                "last_provider": lastmeta.get("actual_provider") if lastmeta else None,
                "last_finish_reason": lastmeta["metadata"]["choices"][0]["finish_reason"]
                if lastmeta
                else None,
                "last_usage": lastmeta["metadata"].get("usage") if lastmeta else None,
                "final_output": a.get("final_output"),
                "last_output": lastresp["output"] if lastresp else None,
                "last_tools": [
                    {"sequence": e["sequence"], "tool": e["tool"], "arguments": e["arguments"]}
                    for e in aes
                    if e["kind"] == "tool_called"
                ][-3:],
                "source": str(p),
            }
            rows.append(row)
        rollouts.append(
            {
                "run": p.parent.name,
                "request_errors": [
                    {
                        "agent": e["agent"],
                        "status": e.get("status_code"),
                        "will_retry": e.get("will_retry"),
                    }
                    for e in es
                    if e["kind"] == "provider_request_failed"
                ],
                "finish_counts": dict(collections.Counter(a["reason"] for a in s["agents"])),
            }
        )

args.output.mkdir(parents=True, exist_ok=True)
audit = {
    "rows": rows,
    "rollouts": rollouts,
    "timing_method": "Per agent: model_request to provider_request_started is local semaphore queue; provider start to receipt is API time. Pending intervals end at agent_finished. Tools serialized per agent. API time includes network/host queuing and generation; it is not pure model compute. Retry backoff is excluded from local queue/API totals. Queue restart after a retry uses the scheduled backoff end; small event/scheduling overhead is unclassified.",
}
(args.output / "audit.json").write_text(json.dumps(audit, indent=2))
failures = [r for r in rows if r["reason"] != "submitted"]
fields = [
    "run",
    "agent",
    "reason",
    "experiments_completed",
    "model_requests",
    "receipts",
    "queue_seconds",
    "api_seconds",
    "tool_seconds",
    "last_provider",
    "last_finish_reason",
]
with (args.output / "failures.csv").open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    w.writerows(failures)
esc = html.escape
body = [
    "<!doctype html><meta charset=utf-8><title>Seven-model pilot failure audit</title><style>body{font:16px/1.5 system-ui;margin:32px auto;max-width:1200px;padding:0 20px;color:#19232b}table{border-collapse:collapse;width:100%}th,td{padding:8px;text-align:left;border-bottom:1px solid #ddd}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f6f6;padding:12px}details{margin:16px 0}h1,h2{line-height:1.2}.number{text-align:right}</style><h1>Seven-model pilot failure audit</h1><p>Audited all 140 planned agents, including the 20 Llama 4 Scout routing failures. 104 submitted, 36 did not. Original runs and submissions remain unchanged. Analysis from recorded events; agent IDs are zero-based.</p>"
]
body.append(
    "<h2>Findings</h2><ul><li><b>Llama 4 Scout: 20 routing errors.</b> All initial requests returned HTTP 404. Non-Google endpoints were removed for lacking tool compatibility; the remaining Google Vertex endpoint required Google BYOK credentials unavailable to our account. No inference or experiments occurred.</li><li><b>Qwen3 Next 80B A3B Instruct: one turn-limit failure.</b> Interact agent 6 spent 74 Python calls returning empty successful output, including 73 identical samples.tolist() calls. Bare expressions are not displayed by our subprocess Python tool. It reached 80 turns with zero experiments. The print(...) clarification was already added after this process started.</li><li><b>DeepSeek V3.2: 11 timeouts.</b> Ten agents were inside an API call at cancellation, one inside Python. Each spent 50–79% of its 1,800-second deadline in the local three-slot semaphore queue (mean 19.1 minutes), 6.3–15 minutes in provider calls, and under 10 seconds in completed tools. Five had already used all 10 measurements. Provider medians were 9.3/10.2 seconds; p95 about 53 seconds; max 126 seconds. The deadline includes local queue time. No provider request errors or output-token-limit terminations occurred for DeepSeek.</li><li><b>DeepSeek V3.2: three text endings.</b> Control agent 3 and Interact agents 4 and 7 returned stop after 8, 7 and 9 experiments. They described intended next actions rather than making native tool calls; one printed a Python tool argument block as text. All three final responses came from AtlasCloud. That host also produced 139 native tool responses, so association is not proof of a host bug. Completion lengths were 99, 20 and 1,232 tokens, below the 4,096 cap.</li><li><b>Kimi K2 Thinking: one text ending.</b> Interact agent 6 made one actual experiment and then returned a notebook-shaped text fragment claiming Experiments 2–10 and an improved best score. Those experiments never occurred. The response ended with stop on Google, 1,592 completion tokens including 442 reasoning tokens; it was not truncated. No submit call occurred, and the purported notebook update was never a tool call. We cannot determine whether model generation or upstream tool serialization caused the text-only ending.</li><li><b>Recovered provider failures.</b> Gemini 3.1 Flash-Lite received one HTTP 504 in each arm. Both requests recovered with the configured retry and both agents submitted.</li><li><b>Successful early exit.</b> Qwen Control agent 1 read 29 files and submitted the all-0.6 configuration without any own measurements. This is allowed: the budget is a maximum and peer records are visible in Control too.</li></ul>"
)
body.append(
    "<h2>Policy proposal — not implemented</h2><ol><li>Preflight each exact model/account/tool configuration with a native tool call and follow-up before admitting it to a batch. Fail fast for permanent routing/authentication errors; use bounded retries with backoff for 429, 5xx and connection errors. Never silently substitute a model in a formal run.</li><li>Remove scheduler starvation before judging model timeouts. Test request concurrency 10 (one active request per agent); separately record local queue and provider time. If excluding local queue time from the agent deadline, predeclare that rule for every model and retain an overall wall-clock safety cap. Provider and deliberate wait time must still count. Concurrency changes the collaboration environment and must be frozen before the experiment.</li><li>Make the Python contract explicit: fresh process per call, print outputs, persist state to files, available libraries and allowed paths. Keep notebook filename selection unchanged to preserve natural discovery behavior. Add one uniform diagnostic after repeated identical empty-output calls, rather than merely raising the turn limit. Mark such assisted behavior in logs.</li><li>For a text-only ending without submit, allow one standardized continuation reminding the agent to use tools and submit; count its time, tokens and cost, keep the original termination reason, and report raw versus recovered completion separately. Reserve a uniformly defined finalization window before hard limits. This intervention affects behavior and must be frozen across models/arms.</li><li>Use experiment_completed and submission events as the authoritative results. Do not parse prose into official experiments or automatically submit an inferred best point. Report completion, budget use, failure reason and any recovery alongside scores. Preserve unsuccessful agents in denominators where defined; zero own measurements leave own-best score unknown.</li><li>Only replay matched blocks automatically for predefined infrastructure failures, retaining the originals and identifying the replacement block. Do not rerun selectively because of poor scores or ordinary model behavior. Cancellation left 10 dispatched DeepSeek requests without response/cost receipts; reported spend may undercount billed cancellation work.</li></ol>"
)
body.append(
    "<p>Interface caveat: the main batch used the earlier Python description; the GLM/Kimi tail used the clarified print(...) description. This pilot is setup diagnostics, not the formal matched experiment.</p><h2>Every unsuccessful agent</h2><table><thead><tr><th>Run</th><th>Agent</th><th>Reason</th><th>Experiments</th><th>Local queue (min)</th><th>API (min)</th><th>End state</th></tr></thead><tbody>"
)
for r in failures:
    body.append(
        "<tr>"
        + "".join(
            "<td>" + esc(str(v)) + "</td>"
            for v in [
                r["run"],
                r["agent"],
                r["reason"],
                r["experiments_completed"],
                round(r["queue_seconds"] / 60, 2),
                round(r["api_seconds"] / 60, 2),
                r["pending"]["state"],
            ]
        )
        + "</tr>"
    )
body.append("</tbody></table><h2>Individual trace details</h2>")
for r in failures:
    if r["run"].startswith("llama"):
        continue
    evidence = {
        k: r[k]
        for k in [
            "tools",
            "tool_errors",
            "empty_successful_python_results",
            "most_repeated_python",
            "pending",
            "last_provider",
            "last_finish_reason",
            "last_usage",
            "last_tools",
            "final_output",
            "last_output",
            "source",
        ]
    }
    body.append(
        "<details><summary>"
        + esc(f"{r['run']} · agent {r['agent']} · {r['reason']}")
        + "</summary><pre>"
        + esc(json.dumps(evidence, indent=2))
        + "</pre></details>"
    )
body.append(
    '<p>Machine-readable evidence: <a href="audit.json">audit.json</a> · <a href="failures.csv">failures.csv</a></p>'
)
(args.output / "index.html").write_text("".join(body))
print(
    json.dumps(
        {
            "agents": len(rows),
            "submitted": sum(r["reason"] == "submitted" for r in rows),
            "failures": len(failures),
            "output": str(args.output),
        }
    )
)
