"""Collect matched model outcomes and plot time/budget trajectories and final tables.

Collect with MEAD's Python; plot with matplotlib/numpy/fonttools installed.
"""

import argparse
import bisect
import csv
import hashlib
import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path


def final_stats(runs):
    scores = [score for run in runs for score in run["final_scores"]]
    maxima = [max(run["final_scores"]) for run in runs if run["final_scores"]]
    spreads = [
        statistics.stdev(run["final_scores"]) for run in runs if len(run["final_scores"]) >= 2
    ]
    return {
        "runs": len(runs),
        "submitted_agents": len(scores),
        "mean_final_score": statistics.mean(scores) if scores else None,
        "mean_maximum_final_score": statistics.mean(maxima) if maxima else None,
        "mean_within_run_sd": statistics.mean(spreads) if spreads else None,
    }




def final_agent_outcomes(reports, events, agents, evaluate):
    """Keep actual submissions; impute missing finals from this agent's own best."""
    by_agent = {r["agent"]: r for r in reports}
    submitted = [r["true_objective"] for r in reports
                 if r.get("reason") == "submitted" and r.get("true_objective") is not None]
    floor = min(submitted) if submitted else None
    best = [None] * agents
    for event in events:
        if event["kind"] == "experiment_completed":
            agent = event["agent"]
            score = evaluate(event["record"]["parameters"])
            best[agent] = max(best[agent], score) if best[agent] is not None else score
    rows = []
    for agent in range(agents):
        report = by_agent.get(agent, {})
        is_submitted = report.get("reason") == "submitted"
        actual = report.get("true_objective") if is_submitted else None
        score = actual
        source = "submitted" if actual is not None else "unknown"
        if not is_submitted and floor is not None and best[agent] is not None:
            score = min(floor, best[agent])
            source = "imputed"
        rows.append({"agent": agent, "reason": report.get("reason"),
                     "submitted_score": actual, "own_best_experiment_score": best[agent],
                     "run_minimum_submitted_score": floor,
                     "score_with_imputation": score, "score_source": source})
    return rows

def final_outcome_stats(completion):
    """Report completion and conditional final scores over all terminal run entries."""
    rows = []
    groups = sorted({(r["model"], r["condition"]) for r in completion})
    for model, condition in groups:
        group = [r for r in completion if (r["model"], r["condition"]) == (model, condition)]
        terminal = all(r["status"] in {"finished", "error"} for r in group)
        agents = sum(r["agents"] for r in group)
        submitted = sum(r["submitted_agents"] for r in group)
        scored = sum(r["scored_submissions"] for r in group)
        score_sum = sum(r["mean_submitted_final_score"] * r["scored_submissions"]
                        for r in group if r["mean_submitted_final_score"] is not None)
        rows.append({
            "model": model, "condition": condition, "runs": len(group),
            "agents": agents, "submitted_agents": submitted,
            "submission_rate": submitted / agents if terminal and agents else None,
            "scored_submissions": scored,
            "mean_submitted_final_score": score_sum / scored if terminal and scored else None,
            "mean_final_score_with_imputation": (
                sum(r["mean_final_score_with_imputation"] * r["agents"] for r in group) / agents
                if terminal and agents and all(r.get("mean_final_score_with_imputation") is not None for r in group)
                else None
            ),
            "imputed_agents": sum(r.get("imputed_agents", 0) for r in group),
            "unresolved_agents": sum(r.get("unresolved_agents", 0) for r in group),
        })
    return rows

def measured_points(events, agents, allocation, start, duration, evaluate):
    best = [None] * agents
    accepted = 0
    points = []
    sequences, counts = [], []
    for event in events:
        if event["kind"] == "experiment_started":
            accepted += 1
            sequences.append(event["sequence"])
            counts.append(accepted)
        if event["kind"] != "experiment_completed":
            continue
        agent = event["agent"]
        score = evaluate(event["record"]["parameters"])
        best[agent] = max(score, best[agent]) if best[agent] is not None else score
        observed = [value for value in best if value is not None]
        points.append(
            {
                "time": (event["elapsed_seconds"] - start) / duration,
                "budget": accepted / allocation if allocation else None,
                "mean_agent_best": statistics.mean(observed),
                "maximum_agent_best": max(observed),
                "observed_agents": len(observed),
            }
        )
    if points:
        points.append(
            {**points[-1], "time": 1.0, "budget": accepted / allocation if allocation else None}
        )
    return points, best, sequences, counts, accepted


def experiment_step_points(events, agents, per_agent_budget, evaluate):
    """Retrospectively align agents by completed experiment ordinal, not wall time."""
    histories = [[] for _ in range(agents)]
    finished = {event["agent"] for event in events if event["kind"] == "agent_finished"}
    for event in events:
        if event["kind"] != "experiment_completed":
            continue
        history = histories[event["agent"]]
        score = evaluate(event["record"]["parameters"])
        history.append(max(history[-1], score) if history else score)
    points = []
    for step in range(1, per_agent_budget + 1):
        if any(len(history) < step and agent not in finished
               for agent, history in enumerate(histories)):
            break
        scores = [history[min(step, len(history)) - 1] for history in histories if history]
        if scores:
            points.append({
                "step": step,
                "mean_agent_best": statistics.mean(scores) if len(scores) == agents else None,
                "maximum_agent_best": max(scores),
                "observed_agents": len(scores),
            })
    return points


MODEL_LABELS = {
    "gemini": "Gemini 3.1 Flash-Lite",
    "qwen": "Qwen3 Next 80B A3B Instruct",
    "minimax": "MiniMax M2",
    "deepseek": "DeepSeek V3.2",
    "llama": "Llama 4 Scout",
    "glm": "GLM 4.7",
    "glm53": "Z.ai GLM 5.3 Flash",
    "kimi": "Kimi K2 Thinking",
}

MODEL_NAMES = {
    "anthropic/claude-haiku-5.5": "Claude Haiku 5.5",
    "openai/gpt-5.6-luna": "OpenAI GPT-5.6 Luna",
    "openai/gpt-6-luna": "OpenAI GPT-6 Luna",
    "openai/gpt-6.1-sol": "OpenAI GPT-6.1 Sol",
    "google/gemini-3.8-flash": "Google Gemini 3.8 Flash",
    "google/gemini-3.1-flash-lite": "Gemini 3.1 Flash-Lite",
    "qwen/qwen3-next-80b-a3b-instruct": "Qwen3 Next 80B A3B Instruct",
    "minimax/minimax-m2": "MiniMax M2",
    "deepseek/deepseek-v3.2": "DeepSeek V3.2",
    "deepseek/deepseek-v3.1-terminus": "DeepSeek V3.1 Terminus",
    "z-ai/glm-4.7": "GLM 4.7",
    "z-ai/glm-5.3-flash": "Z.ai GLM 5.3 Flash",
    "moonshotai/kimi-k2-thinking": "Kimi K2 Thinking",
    "meta-llama/llama-4-scout": "Llama 4 Scout",
}


def saved_model_labels(manifest):
    return {entry["model_key"]: MODEL_NAMES.get(entry.get("model"),
            entry.get("model") or MODEL_LABELS.get(entry["model_key"], entry["model_key"]))
            for entry in manifest["runs"]}

METRICS = {
    "mean_agent_best": "Mean of each agent’s best score",
    "maximum_agent_best": "Maximum score across agents",
    "peer_reads": "Peer-file reads",
    "peer_mentions": "Other-agent mentions",
    "specific_mentions": "Specific-agent mentions",
    "reasoning_mentions": "Internal reasoning: other-agent mentions",
    "reasoning_specific_mentions": "Internal reasoning: specific-agent mentions",
    "assistant_message_mentions": "Internal messages: other-agent mentions",
    "assistant_message_specific_mentions": "Internal messages: specific-agent mentions",
    "discovered_peer_result": "Listed a peer’s experiment result",
    "discovered_peer_note": "Listed a peer’s notebook",
    "discovered_either": "Listed either peer artifact",
    "wait_calls": "Wait-tool calls",
    "cost_usd": "Cumulative reported cost (USD)",
}
TIME_AXES = {
    "time": "Share of run elapsed time",
    "active_time": "Share of run active time (pauses excluded)",
    "budget": "Share of allocated experiment budget consumed",
    "step": "Experiments completed per agent",
}


def cost_events(events):
    """Prefer provider receipts; never add SDK copies of the same receipts."""
    receipts = [e for e in events if e["kind"] == "provider_response_metadata"]
    if not receipts:
        receipts = [e for e in events if e["kind"] == "model_response"]
    known, missing, seen = [], 0, set()
    for event in receipts:
        response_id = event.get("response_id")
        if response_id:
            key = (event["agent"], response_id)
            if key in seen:
                continue
            seen.add(key)
        usage = ((event.get("metadata") or {}).get("usage")
                 if event["kind"] == "provider_response_metadata" else event.get("raw_usage"))
        cost = (usage or {}).get("cost")
        if cost is None:
            missing += 1
        else:
            known.append({"agent": event["agent"], "sequence": event["sequence"],
                          "elapsed_seconds": event["elapsed_seconds"],
                          "active_elapsed_seconds": event.get("active_elapsed_seconds", event["elapsed_seconds"]), "cost_usd": cost})
    return known, missing


def cost_table(runs, models, conditions):
    rows = []
    for model in models:
        for condition in conditions:
            group = [r for r in runs if r["model"] == model and r["condition"] == condition]
            if not group:
                continue
            known = sum(r["known_cost_usd"] for r in group)
            missing = sum(r["cost_unreported_responses"] for r in group)
            rows.append({"model": model, "condition": condition, "runs": len(group),
                         "agents": sum(r["agents"] for r in group),
                         "known_total_cost_usd": known,
                         "total_cost_usd": known if missing == 0 else None,
                         "mean_cost_per_run_usd": known / len(group) if missing == 0 else None,
                         "mean_cost_per_agent_usd": known / sum(r["agents"] for r in group) if missing == 0 else None,
                         "cost_reported_responses": sum(r["cost_reported_responses"] for r in group),
                         "cost_unreported_responses": missing})
    return rows


def cost_totals(rows):
    known = sum(row["known_total_cost_usd"] for row in rows)
    runs = sum(row["runs"] for row in rows)
    agents = sum(row["agents"] for row in rows)
    missing = sum(row["cost_unreported_responses"] for row in rows)
    complete = missing == 0
    return {"model": "All", "condition": "All", "runs": runs, "agents": agents,
            "known_total_cost_usd": known, "total_cost_usd": known if complete else None,
            "mean_cost_per_run_usd": known / runs if complete and runs else None,
            "mean_cost_per_agent_usd": known / agents if complete and agents else None,
            "cost_reported_responses": sum(row["cost_reported_responses"] for row in rows),
            "cost_unreported_responses": missing}


def interaction_step_points(events, interactions, agents, per_agent_budget):
    """Count each agent's events through completion of its kth experiment."""
    checkpoints = [[] for _ in range(agents)]
    finished = {event["agent"]: event["sequence"] for event in events
                if event["kind"] == "agent_finished"}
    for event in events:
        if event["kind"] == "experiment_completed":
            checkpoints[event["agent"]].append(event["sequence"])
    sequences = {
        metric: {
            agent: sorted(e["sequence"] for e in evidence if e["agent"] == agent)
            for agent in range(agents)
        }
        for metric, evidence in interactions.items()
    }
    points = []
    for step in range(1, per_agent_budget + 1):
        cutoffs = {}
        for agent in range(agents):
            history = checkpoints[agent]
            if agent in finished and step >= len(history):
                cutoffs[agent] = finished[agent]
            elif len(history) >= step:
                cutoffs[agent] = history[step - 1]
        if len(cutoffs) != agents:
            break
        point = {"step": step, "observed_agents": agents}
        for metric, by_agent in sequences.items():
            count = sum(bisect.bisect_right(by_agent[agent], cutoffs[agent])
                        for agent in range(agents))
            if metric == "cost_usd":
                count = sum(e["cost_usd"] for e in interactions[metric]
                            if e["sequence"] <= cutoffs[e["agent"]])
            point[metric] = count / agents if metric.startswith("discovered_") else count
        points.append(point)
    return points


def paired_delta_series(runs, metric, axis, grid, run_values, require_all_pairs=False):
    """Average Interact-Control within complete repetition pairs at each x."""
    repetitions = sorted({run["repetition"] for run in runs})
    pairs = []
    for repetition in repetitions:
        by_condition = {run["condition"]: run for run in runs if run["repetition"] == repetition}
        if not {"control", "interact"}.issubset(by_condition):
            continue
        pairs.append((run_values(by_condition["control"], metric, axis, grid),
                      run_values(by_condition["interact"], metric, axis, grid)))
    result = {"x": [], "y": [], "matched_pairs": []}
    for index, x in enumerate(grid):
        differences = [float(interact[index] - control[index]) for control, interact in pairs
                       if math.isfinite(control[index]) and math.isfinite(interact[index])]
        if require_all_pairs and len(differences) != len(pairs):
            continue
        if differences:
            result["x"].append(float(x))
            result["y"].append(statistics.mean(differences))
            result["matched_pairs"].append(len(differences))
    return result


def figure_catalog(data):
    return [
        {"model": model, "metric": metric, "axis": axis,
         "filename": f"{metric}-{axis}-{model}"}
        for model in data["models"]
        if any(run["model"] == model for run in data["runs"])
        for metric in METRICS
        for axis in TIME_AXES
    ]



def pair_has_terminal_task_data(batch, pair):
    """Keep completed episodes with agent failures; exclude unfinished/no-data attempts."""
    for entry in pair:
        if entry["status"] not in {"finished", "error"}:
            return False
        path = batch / entry["run_id"] / "summary.json"
        if not path.exists():
            return False
        reports = json.loads(path.read_text()).get("agents", [])
        if len(reports) != entry["agents"] or {r.get("agent") for r in reports} != set(range(entry["agents"])):
            return False
        if not all(r.get("reason") for r in reports):
            return False
        if not any((r.get("experiments_completed") or 0) > 0 or r["reason"] == "submitted" for r in reports):
            return False
    return True

def collect(batch, output):
    # Reevaluate measurements with the objective code archived with this exact batch.
    sys.path.insert(0, str(batch / "inputs/code/src"))
    from summarize_collaboration import analyze_discoveries, analyze_events, analyze_mention_channels

    from mad.config import TaskConfig
    from mad.task import SyntheticObjective

    manifest = json.loads((batch / "manifest.json").read_text())
    conditions = manifest["conditions"]
    runs, excluded, completion, agent_outcomes = [], [], [], []
    for entry in manifest["runs"]:
        summary_path = batch / entry["run_id"] / "summary.json"
        agents_summary = json.loads(summary_path.read_text()).get("agents", []) if summary_path.exists() else []
        directory = batch / entry["run_id"]
        config_path, events_path = directory / "config.json", directory / "events.jsonl"
        config = json.loads(config_path.read_text()) if config_path.exists() else None
        events = [json.loads(line) for line in events_path.read_text().splitlines()] if events_path.exists() else []
        objective = SyntheticObjective(TaskConfig.model_validate(config["task"])) if config else None
        per_agent = final_agent_outcomes(agents_summary, events, entry["agents"],
                                        objective.evaluate if objective else lambda _: None)
        agent_outcomes.extend({"run_id": entry["run_id"], "model": entry["model_key"],
                               "condition": entry["condition"], **row} for row in per_agent)
        imputed_scores = [row["score_with_imputation"] for row in per_agent]
        submitted_scores = [a["true_objective"] for a in agents_summary
                            if a.get("reason") == "submitted" and a.get("true_objective") is not None]
        completion.append({
            "run_id": entry["run_id"], "model": entry["model_key"],
            "condition": entry["condition"], "status": entry["status"],
            "agents": entry["agents"],
            "submitted_agents": sum(a.get("reason") == "submitted" for a in agents_summary),
            "mean_final_score_with_imputation": (
                statistics.mean(imputed_scores) if imputed_scores and all(v is not None for v in imputed_scores) else None
            ),
            "imputed_agents": sum(r["score_source"] == "imputed" for r in per_agent),
            "unresolved_agents": sum(r["score_source"] == "unknown" for r in per_agent),
            "scored_submissions": len(submitted_scores),
            "mean_submitted_final_score": statistics.mean(submitted_scores) if submitted_scores else None,
            "measured_agents": sum((a.get("experiments_completed") or 0) > 0 for a in agents_summary),
            "end_reasons": dict(Counter(a["reason"] for a in agents_summary)),
        })
        pair = [
            e
            for e in manifest["runs"]
            if e["repetition"] == entry["repetition"]
            and e.get("model_key") == entry.get("model_key")
        ]
        if not pair_has_terminal_task_data(batch, pair):
            excluded.append(
                {
                    "run_id": entry["run_id"],
                    "status": entry["status"],
                    "reason": "matched pair unfinished or without completed task data",
                }
            )
            continue
        directory = batch / entry["run_id"]
        config = json.loads((directory / "config.json").read_text())
        summary = json.loads((directory / "summary.json").read_text())
        events = [
            json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()
        ]
        objective = SyntheticObjective(TaskConfig.model_validate(config["task"]))
        start = min(e["elapsed_seconds"] for e in events if e["kind"] == "agent_started")
        end = max(e["elapsed_seconds"] for e in events if e["kind"] == "agent_finished")
        duration = end - start
        active_start = min(e.get("active_elapsed_seconds", e["elapsed_seconds"]) for e in events if e["kind"] == "agent_started")
        active_end = max(e.get("active_elapsed_seconds", e["elapsed_seconds"]) for e in events if e["kind"] == "agent_finished")
        active_duration = active_end - active_start
        event_active = {e["sequence"]: e.get("active_elapsed_seconds", e["elapsed_seconds"]) for e in events}
        allocation = config["agents"] * config["experiment_budget"]
        points, best, budget_sequences, budget_counts, accepted = measured_points(
            events, config["agents"], allocation, start, duration, objective.evaluate
        )
        measured_events = [e for e in events if e["kind"] == "experiment_completed"]
        for point, event in zip(points[:-1], measured_events):
            point["active_time"] = (event_active[event["sequence"]] - active_start) / active_duration
        if points:
            points[-1]["active_time"] = 1.0
        ownership = json.loads((directory / "note_ownership.json").read_text())
        identities = {
            a["agent"]: a["author_id"]
            for a in json.loads((directory / "identities.json").read_text())
        }
        reads, mentions = analyze_events(events, ownership, identities)
        channels, reasoning_coverage = analyze_mention_channels(events, identities)
        mentions = channels["shared_notes"]
        discoveries = analyze_discoveries(events, identities)
        costs, missing_costs = cost_events(events)
        interactions = {}
        for name, evidence in [
            ("peer_reads", reads),
            ("peer_mentions", mentions),
            (
                "specific_mentions",
                [m for m in mentions if any(x["tag"] == "peer_id" for x in m["excerpts"])],
            ),
            *discoveries.items(),
            ("reasoning_mentions", channels["reasoning"]),
            ("reasoning_specific_mentions", [m for m in channels["reasoning"]
                                            if any(x["tag"] == "peer_id" for x in m["excerpts"])]),
            ("assistant_message_mentions", channels["assistant_messages"]),
            ("assistant_message_specific_mentions", [m for m in channels["assistant_messages"]
                                                    if any(x["tag"] == "peer_id" for x in m["excerpts"])]),
            ("wait_calls", [e for e in events if e["kind"] == "tool_called" and e["tool"] == "wait"]),
            ("cost_usd", costs),
        ]:
            interactions[name] = [
                {
                    **({"cost_usd": event["cost_usd"]} if name == "cost_usd" else {}),
                    "agent": event["agent"],
                    "sequence": event["sequence"],
                    "time": (event["elapsed_seconds"] - start) / duration,
                    "active_time": (event_active[event["sequence"]] - active_start) / active_duration,
                    "budget": (
                        budget_counts[bisect.bisect_right(budget_sequences, event["sequence"]) - 1]
                        if bisect.bisect_right(budget_sequences, event["sequence"])
                        else 0
                    )
                    / allocation
                    if allocation
                    else None,
                }
                for event in evidence
            ]
        runs.append(
            {
                "run_id": entry["run_id"],
                "model": entry["model_key"],
                "reasoning_text_coverage": reasoning_coverage,
                "mention_channel_evidence": channels,
                "condition": entry["condition"],
                "repetition": entry["repetition"],
                "agents": config["agents"],
                "duration_seconds": duration,
                "active_duration_seconds": active_duration,
                "pause_duration_seconds": duration - active_duration,
                "experiment_duration_seconds": config.get("experiment_duration_seconds", 0),
                "budget_allocation": allocation,
                "accepted_experiments": accepted,
                "final_scores": [
                    a["true_objective"]
                    for a in summary["agents"]
                    if a["reason"] == "submitted" and a.get("true_objective") is not None
                ],
                "final_agent_bests": best,
                "experiment_step_points": experiment_step_points(
                    events, config["agents"], config["experiment_budget"], objective.evaluate
                ),
                "per_agent_budget": config["experiment_budget"],
                "points": points,
                "interactions": interactions,
                "interaction_step_points": interaction_step_points(
                    events, interactions, config["agents"], config["experiment_budget"]
                ),
                "known_cost_usd": sum(e["cost_usd"] for e in costs),
                "cost_reported_responses": len(costs),
                "cost_unreported_responses": missing_costs,
                "wait_calls_total": len(interactions["wait_calls"]),
                "wait_calls_by_agent": [
                    sum(e["agent"] == agent for e in interactions["wait_calls"])
                    for agent in range(config["agents"])
                ],
                "discovery_evidence": discoveries,
                "discovery_indicators": {
                    key: [int(any(event["agent"] == agent for event in evidence))
                          for agent in range(config["agents"])]
                    for key, evidence in discoveries.items()
                },
            }
        )
    output.mkdir(parents=True, exist_ok=True)
    tables = [
        {
            "model": model,
            "condition": condition,
            **final_stats([r for r in runs if r["model"] == model and r["condition"] == condition]),
        }
        for model in manifest["model_configs"]
        for condition in conditions
    ]
    measured_tables = []
    for model in manifest["model_configs"]:
        for condition in conditions:
            group = [r for r in runs if r["model"] == model and r["condition"] == condition]
            means = [
                statistics.mean(r["final_agent_bests"])
                for r in group
                if all(v is not None for v in r["final_agent_bests"])
            ]
            maxima = [
                max(v for v in r["final_agent_bests"] if v is not None)
                for r in group
                if any(v is not None for v in r["final_agent_bests"])
            ]
            measured_tables.append(
                {
                    "model": model,
                    "condition": condition,
                    "runs": len(group),
                    "mean_agent_best_measured_noiseless": statistics.mean(means)
                    if group and len(means) == len(group)
                    else None,
                    "mean_run_maximum_measured_noiseless": statistics.mean(maxima)
                    if group and len(maxima) == len(group)
                    else None,
                }
            )
    data = {
        "batch": str(batch.resolve()),
        "batch_status": manifest["status"],
        "models": list(manifest["model_configs"]),
        "model_labels": saved_model_labels(manifest),
        "conditions": conditions,
        "runs": runs,
        "excluded": excluded,
        "completion_table": completion,
        "final_outcome_table": final_outcome_stats(completion),
        "final_agent_outcomes": agent_outcomes,
        "final_score_table": tables,
        "measured_score_table": measured_tables,
        "cost_table": cost_table(runs, manifest["model_configs"], conditions),
        "definitions": {
            "time": "Wall time from first agent_started to last agent_finished; includes pauses.",
            "active_time": "Same endpoints on the recorded active clock. Only quiescent frozen intervals are excluded; draining admitted work remains active time. Historical logs without active clocks use wall time.",
            "budget": "Accepted experiments / (agents × per-agent experiment budget). "
            "Budget is consumed at experiment_started, before its result arrives. "
            "Final values of finished runs carry forward through any unused allocation to x=1. "
            "Final analysis/interactions map to the last consumed fraction; they do not spend experiments.",
            "mean_agent_best": "Mean of best true scores for agents with at least one completed measurement; "
            "agents without results are omitted. Equal weight among runs with results at that point. "
            "Agent and run denominators can change during the trajectory.",
            "maximum_agent_best": "Maximum true score among all completed measurements in each run, "
            "then mean across runs. Final submissions excluded from both trajectories.",
            "experiment_step": "At step k, use each agent’s best noiseless score from its first k "
            "completed experiments. Average or maximize within each run, then average across runs. "
            "Finished agents with fewer than k experiments carry their last measured best forward; "
            "all agents/runs stay in the average. Unfinished or unmeasured agents are not imputed. "
            "No wall-time alignment or future results.",
            "final_imputation": "Actual submitters keep their submitted noiseless scores. Each non-submitter "
            "receives min(the lowest submitted score in its run, that agent's own best completed noiseless "
            "experiment score). No submission in a run or no own completed experiment leaves the value unknown; "
            "a group mean is unknown unless every agent has a defined score. Imputation is analysis only: "
            "it never creates a submission or changes submission rate. Group means pool all agents.",
            "final_outcome_table": "Submission rate uses all agents in terminal run entries, including failed runs. "
            "Final-score mean includes only actual submitted configurations with known noiseless scores; "
            "no score is assigned to non-submissions. These outcomes are reported side by side.",
            "final_score_table": "Mean final score pools submitted agents; maxima averaged per run; "
            "within-run sample SD (ddof=1) averaged across runs. Attrition reported.",
            "matching": "Only terminal control/interact task episodes within each model/repetition are aggregated. "
            "Agent failures within completed episodes remain included; unfinished episodes and "
            "pre-inference/no-task-data routing failures are excluded from trajectories.",
            "cost_usd": "Cumulative provider-reported USD cost, summed over agents and averaged equally "
            "across runs. Provider response receipts preferred; SDK copies not counted twice. "
            "Missing costs are excluded from reported-cost trajectories and flagged in the table; "
            "total/average cost is unknown when coverage is incomplete. Only selected terminal task episodes, including their failed agents, "
            "are included; separate pre-inference/no-data attempts and external charges excluded.",
            "wait_calls": "Total logged tool_called events for wait, including failed/cancelled calls. "
            "Provider retry backoff and experiment measurement delays do not count as wait-tool calls.",
            "interaction_step": "At step k, count every agent’s interaction events through completion "
            "of its kth experiment, then sum counts (or average discovery indicators) within each run. "
            "For finished agents, final work after their last measurement is included at that last step; "
            "terminal counts and costs carry forward through unused steps. All agents stay included. ",
            "discovery": "Agent-level absorbing indicators: flip to 1 at the first successful "
            "list_files result for /lab/runs or /lab/notes containing a non-directory file "
            "whose returned author ID belongs to another agent. Either flips at the first of the two. "
            "Mean indicator over all allocated agents, then equal-weight mean across runs. "
            "Listing is observable exposure, not proof the agent understood or read the file. "
            "Python listings are excluded.",
            "interactions": "External mentions count successful write_file/append_file operations "
            "to /lab/notes containing peer language or a specific peer ID. Failed writes and private "
            "files are excluded. Internal reasoning and ordinary assistant messages are separate "
            "one-per-response measures. Specific-ID mentions are a subset within each channel. "
            "Excludes Python bulk file access. Reasoning-text coverage is recorded per run; "
            "unavailable reasoning is unknown, not evidence of no internal mentions.",
        },
        "objective_source_sha256": hashlib.sha256(
            (batch / "inputs/code/src/mad/task.py").read_bytes()
        ).hexdigest(),
    }
    data["cost_totals"] = cost_totals(data["cost_table"])
    (output / "outcomes.json").write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    with (output / "final-agent-outcomes.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(agent_outcomes[0]))
        writer.writeheader()
        writer.writerows(agent_outcomes)
    with (output / "final-outcome-table.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(data["final_outcome_table"][0]))
        writer.writeheader()
        writer.writerows(data["final_outcome_table"])
    with (output / "final-score-table.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(tables[0]))
        writer.writeheader()
        writer.writerows(tables)
    with (output / "measured-score-table.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(measured_tables[0]))
        writer.writeheader()
        writer.writerows(measured_tables)
    with (output / "completion-table.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(completion[0]))
        writer.writeheader()
        writer.writerows(completion)
    with (output / "cost-table.csv").open("w") as stream:
        rows = data["cost_table"]
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows([*rows, data["cost_totals"]])
    wait_rows = [
        {"run_id": run["run_id"], "model": run["model"], "condition": run["condition"],
         "wait_calls_total": run["wait_calls_total"], **{
             f"agent_{agent}_wait_calls": count
             for agent, count in enumerate(run["wait_calls_by_agent"])
         }}
        for run in runs
    ]
    with (output / "wait-call-totals.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(wait_rows[0]))
        writer.writeheader()
        writer.writerows(wait_rows)
    print(json.dumps({"complete_runs": len(runs), "excluded_runs": len(excluded),
                      "wait_calls_total": sum(run["wait_calls_total"] for run in runs)}))


def plot(output):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib import font_manager
    from matplotlib.ticker import PercentFormatter

    data = json.loads((output / "outcomes.json").read_text())
    MODEL_LABELS = {**globals()["MODEL_LABELS"], **data.get("model_labels", {})}
    font = Path("/System/Library/Fonts/Avenir Next.ttc")
    if font.exists():
        from fontTools.ttLib import TTCollection

        target = output / "AvenirNext-Medium.ttf"
        with TTCollection(str(font)) as collection:
            next(
                f for f in collection.fonts if f["name"].getDebugName(6) == "AvenirNext-Medium"
            ).save(target)
        font_manager.fontManager.addfont(target)
        family = font_manager.FontProperties(fname=target).get_name()
    else:
        family = "DejaVu Sans"
    plt.rcParams.update(
        {
            "font.family": family,
            "figure.facecolor": "#F7F6F0",
            "axes.facecolor": "#F7F6F0",
            "savefig.facecolor": "#F7F6F0",
            "text.color": "#18181B",
            "axes.labelcolor": "#18181B",
            "svg.fonttype": "none",
            "font.size": 10,
        }
    )
    colors = {"control": "#075C78", "interact": "#4B9AB5"}
    grid = np.linspace(0, 1, 201)

    def style(ax, xlabel):
        ax.set_xlim(0, 1)
        ax.xaxis.set_major_formatter(PercentFormatter(1))
        ax.set_xlabel(xlabel)
        ax.grid(axis="y", color="#E6EAED", linewidth=0.7)
        for spine in ax.spines.values():
            spine.set_visible(False)

    def save(fig, name):
        fig.savefig(output / f"{name}.png", dpi=200)
        fig.savefig(output / f"{name}.svg")
        plt.close(fig)

    def run_values(run, metric, axis, axis_grid):
        performance = metric in ("mean_agent_best", "maximum_agent_best")
        discovery = metric.startswith("discovered_")
        if performance or axis == "step":
            points = (run["experiment_step_points"] if performance else run["interaction_step_points"]) if axis == "step" else run["points"]
            if not points:
                return np.full(axis_grid.shape, np.nan)
            xs = np.asarray([p.get(axis, p.get("time")) for p in points], dtype=float)
            ys = np.asarray([p[metric] if p[metric] is not None else np.nan for p in points], dtype=float)
            indices = np.searchsorted(xs, axis_grid, side="right") - 1
            vals = ys[np.maximum(indices, 0)].copy()
            vals[indices < 0] = np.nan
            if axis == "step":
                vals[axis_grid > xs[-1]] = np.nan
        else:
            xs = sorted(e.get(axis, e.get("time")) for e in run["interactions"][metric])
            indices = np.searchsorted(xs, axis_grid, side="right")
            if metric == "cost_usd":
                evidence = sorted(run["interactions"][metric], key=lambda e: e.get(axis, e.get("time")))
                cumulative = np.concatenate(([0.0], np.cumsum([e["cost_usd"] for e in evidence])))
                vals = cumulative[indices]
            else:
                vals = indices.astype(float)
            if discovery:
                vals /= run["agents"]
        return vals

    # Cache the actual displayed means before selecting one scale per outcome.
    curves, scales = {}, {}
    for metric in METRICS:
        values = []
        for model in data["models"]:
            runs = [r for r in data["runs"] if r["model"] == model]
            if not runs:
                continue
            for axis in TIME_AXES:
                axis_grid = (np.arange(1, max(r["per_agent_budget"] for r in runs) + 1)
                             if axis == "step" else grid)
                for condition in data["conditions"]:
                    group = [run for run in runs if run["condition"] == condition]
                    matrices = [run_values(run, metric, axis, axis_grid) for run in group]
                    matrix = np.asarray(matrices)
                    available = np.isfinite(matrix)
                    denominators = available.sum(axis=0)
                    valid = denominators == len(group) if axis == "step" else denominators > 0
                    mean = np.where(available, matrix, 0).sum(axis=0)[valid] / denominators[valid]
                    curves[model, metric, axis, condition] = (axis_grid[valid], mean)
                    values.extend(mean.tolist())
        if metric.startswith("discovered_"):
            ticks = np.linspace(0, 1, 6)
        else:
            from matplotlib.ticker import MaxNLocator
            low, high = (min(values), max(values)) if values else (0, 0)
            if metric not in ("mean_agent_best", "maximum_agent_best"):
                low = 0
            margin = (high - low) * 0.05 or 0.05
            upper = high + margin if high > low else low + 1
            lower = low - margin if metric in ("mean_agent_best", "maximum_agent_best") else 0
            ticks = MaxNLocator(nbins=5).tick_values(lower, upper)
        scales[metric] = {"limits": [float(ticks[0]), float(ticks[-1])],
                          "ticks": ticks.tolist()}
    (output / "vertical-scales.json").write_text(json.dumps(scales, indent=2) + "\n")

    delta_series, delta_scales = [], {}
    for metric in METRICS:
        values = []
        for model in data["models"]:
            runs = [run for run in data["runs"] if run["model"] == model]
            if not runs:
                continue
            for axis in TIME_AXES:
                axis_grid = (np.arange(1, max(run["per_agent_budget"] for run in runs) + 1)
                             if axis == "step" else grid)
                result = paired_delta_series(runs, metric, axis, axis_grid, run_values,
                                             require_all_pairs=axis == "step")
                delta_series.append({"model": model, "metric": metric, "axis": axis,
                                     "condition": "delta", "mode": "delta", **result})
                values.extend(result["y"])
        if metric.startswith("discovered_"):
            ticks = np.linspace(-1, 1, 9)
        else:
            extent = max((abs(value) for value in values), default=0)
            extent = extent * 1.05 if extent else 1
            ticks = MaxNLocator(nbins=6, symmetric=True).tick_values(-extent, extent)
        delta_scales[metric] = {"limits": [float(ticks[0]), float(ticks[-1])],
                                "ticks": ticks.tolist()}

    chart_data = {
        "metrics": METRICS, "axes": TIME_AXES, "models": data["models"],
        "model_labels": {model: MODEL_LABELS.get(model, model) for model in data["models"]},
        "conditions": data["conditions"], "scales": scales, "delta_scales": delta_scales,
        "delta_definition": "Interact minus Control within each matched repetition; then mean across pairs. "
        "Only pairs with both values at that x are included; step curves retain all pairs/agents "
        "by carrying finished agents' terminal values through unused steps. "
        "Positive means Interact is higher, not necessarily better.",
        "series": [
            {"model": model, "metric": metric, "axis": axis, "condition": condition, "mode": "levels",
             "x": xs.tolist(), "y": ys.tolist()}
            for (model, metric, axis, condition), (xs, ys) in curves.items()
        ] + delta_series,
    }
    (output / "chart-data.json").write_text(json.dumps(chart_data, allow_nan=False) + "\n")

    for model in data["models"]:
        runs = [r for r in data["runs"] if r["model"] == model]
        if not runs:
            continue
        n = len([r for r in runs if r["condition"] == "control"])
        pair_label = f"{n} matched pair" + ("s" if n != 1 else "")
        for metric, ylabel in METRICS.items():
            performance = metric in ("mean_agent_best", "maximum_agent_best")
            discovery = metric.startswith("discovered_")
            for axis, xlabel in TIME_AXES.items():
                fig, ax = plt.subplots(figsize=(7.5, 5), layout="constrained")
                ax.set_title(f"{MODEL_LABELS.get(model, model.capitalize())} · {ylabel}", fontsize=14, pad=14)
                axis_grid = (np.arange(1, max(r["per_agent_budget"] for r in runs) + 1)
                             if axis == "step" else grid)
                for condition in data["conditions"]:
                    xs, ys = curves[model, metric, axis, condition]
                    ax.step(xs, ys, where="post", color=colors[condition], linewidth=2,
                            linestyle="-" if condition == "control" else "--",
                            label=condition.capitalize())
                style(ax, xlabel)
                if axis == "step":
                    from matplotlib.ticker import ScalarFormatter
                    ax.set_xlim(1, max(2, axis_grid[-1]))
                    ax.set_xticks(axis_grid)
                    ax.xaxis.set_major_formatter(ScalarFormatter())
                ax.set_ylabel(ylabel if performance else "Share of agents" if discovery else "Mean cumulative cost per run (USD)" if metric == "cost_usd" else "Mean cumulative count per run")
                ax.legend(frameon=False)
                if discovery:
                    ax.set_ylim(0, 1)
                    ax.yaxis.set_major_formatter(PercentFormatter(1))
                elif not performance:
                    ax.set_ylim(bottom=0)
                if not performance and not any(run["interactions"][metric] for run in runs):
                    ax.set_ylim(0, 1)
                    ax.set_yticks([0, 0.5, 1])
                    ax.text(0.5, 0.5, "No logged events", transform=ax.transAxes,
                            ha="center", fontsize=11, color="#666666")
                ax.set_ylim(*scales[metric]["limits"])
                ax.set_yticks(scales[metric]["ticks"])
                if axis == "step":
                    note = "All agents included; finished agents carry their last best through unused steps."
                    if not performance:
                        note += "\nFinal work included at the last used step; terminal totals carry forward."
                elif performance:
                    note = "Completed measurements only; agents/runs with results included."
                else:
                    note = "All agents included. Logged tool events; Python file access excluded."
                if discovery:
                    note += "\nFirst listing per agent; discovery does not imply reading."
                if metric == "cost_usd":
                    if axis != "step":
                        note = "All agents included; provider-reported USD averaged across runs."
                    note += "\nProvider-reported costs only; see coverage in the cost table."
                if metric == "wait_calls":
                    note += "\nWait-tool calls only; provider retry backoff excluded."
                fig.get_layout_engine().set(rect=(0, 0.23, 1, 0.72))
                fig.text(0.08, 0.025, f"{pair_label}. {note}", fontsize=8)
                save(fig, f"{metric}-{axis}-{model}")

        fig, ax = plt.subplots(figsize=(12, 3.4))
        ax.axis("off")
        headers = [
            "Condition",
            "Mean final score\nacross submitted agents",
            "Mean of maximum final score\nacross agents per run",
            "Mean within-run SD of\nfinal scores",
        ]
        rows = [r for r in data["final_score_table"] if r["model"] == model]
        cells = [
            [r["condition"].capitalize()]
            + [
                f"{r[k]:.4f}" if r[k] is not None else "—"
                for k in ["mean_final_score", "mean_maximum_final_score", "mean_within_run_sd"]
            ]
            for r in rows
        ]
        table = ax.table(
            cellText=cells,
            colLabels=headers,
            cellLoc="center",
            colWidths=[0.16, 0.26, 0.32, 0.26],
            bbox=[0, 0.20, 1, 0.68],
        )
        table.auto_set_font_size(False)
        table.set_fontsize(12)
        for (row, col), cell in table.get_celld().items():
            cell.set_facecolor("#F7F6F0")
            cell.set_edgecolor("#18181B")
            cell.visible_edges = "B" if row == 0 else ""
            if col == 0:
                cell.set_text_props(ha="left")
        fig.suptitle(f"{MODEL_LABELS.get(model, model.capitalize())} · final submitted scores", fontsize=16, y=0.98)
        attrition = " · ".join(
            f"{r['condition'].capitalize()}: {r['submitted_agents']}/{r['runs'] * runs[0]['agents']} submitted"
            for r in rows
        )
        fig.text(
            0.04,
            0.045,
            f"{pair_label}. {attrition}. Within-run sample SD (ddof=1).",
            fontsize=9,
        )
        fig.subplots_adjust(left=0.03, right=0.97, bottom=0.06, top=0.91)
        save(fig, f"final-score-table-{model}")
    catalog = figure_catalog(data)
    (output / "figure-manifest.json").write_text(json.dumps(catalog, indent=2) + "\n")
    render_gallery(output, data, catalog)
    print(f"Rendered {len(catalog)} single-metric figures plus final-score tables.")


def render_gallery(output, data, catalog):
    import html

    MODEL_LABELS = {**globals()["MODEL_LABELS"], **data.get("model_labels", {})}

    esc = html.escape
    gallery = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MEAD setup figures</title>'
    gallery += """<style>
    body{font:15px/1.5 system-ui;margin:0;background:#F7F6F0;color:#18181b}
    main{max-width:1600px;margin:auto;padding:28px}h1{margin:0 0 6px}a{color:#075C78}img{width:100%}
    .controls{display:flex;gap:18px;flex-wrap:wrap;align-items:start;padding:18px;background:#fff;border:1px solid #ddd;border-radius:10px;margin:20px 0}
    .field{display:grid;gap:6px;font-weight:600}select,button{font:inherit;padding:8px;border:1px solid #bbb;border-radius:6px;background:white;cursor:pointer}
    fieldset{border:0;margin:0;padding:0}legend{font-weight:600;margin-bottom:6px}.choices{display:flex;gap:12px;flex-wrap:wrap}
    .choices label{font-weight:400;white-space:nowrap}.toolbar{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}
    .figures{display:grid;gap:18px;grid-template-columns:repeat(auto-fit,minmax(min(100%,440px),1fr))}
    .figures.overlay{grid-template-columns:repeat(auto-fit,minmax(min(100%,650px),1fr))}
    .chart-card{position:relative;min-width:0;border:1px solid #ddd;border-radius:10px;background:#fff;padding:14px}
    .chart-card h2{font-size:17px;margin:0}.chart-head{display:flex;justify-content:space-between;gap:12px;align-items:start}
    .chart-head button{padding:4px 8px;font-size:12px}.chart-card svg{display:block;width:100%;height:auto;touch-action:none}
    .legend{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0}.legend button{font-size:12px;padding:3px 7px;border:0;background:#f5f5f5}
    .tooltip{position:absolute;z-index:10;background:#fff;border:1px solid #bbb;border-radius:6px;box-shadow:0 4px 15px #0002;padding:10px;pointer-events:none;min-width:190px;font-size:12px}
    .tooltip[hidden]{display:none}.tooltip table{width:100%;text-align:right}.tooltip td:first-child{text-align:left;padding-right:14px}
    .hint{color:#555;font-size:13px}.exports{margin-top:24px}.exports article{padding:12px}.exports article[hidden]{display:none}
    </style><main><h1>MEAD results explorer</h1><p>Choose an outcome, select models, then compare panels or overlay their curves.</p>"""
    delays = sorted({r["experiment_duration_seconds"] for r in data["runs"]})
    gallery += f'<p>These archived runs used measurement delays of {esc(", ".join(str(x) for x in delays))} seconds. Changes to future configurations do not change these observations.</p>'
    gallery += '<p><a href="final-score-table.csv">Final-score CSV</a> · <a href="measured-score-table.csv">Measured-best CSV</a> · <a href="wait-call-totals.csv">Wait-call totals CSV</a> · <a href="cost-table.csv">Cost CSV</a> · <a href="outcomes.json">Source data and definitions</a> · <a href="figure-manifest.json">Figure manifest</a></p>'
    available_models = {run["model"] for run in data["runs"]}
    gallery += '<section class="controls" aria-label="Chart controls"><label class="field" for="select-metric">Outcome<select id="select-metric" data-filter="metric">'
    for metric, label in METRICS.items():
        gallery += f'<option value="{esc(metric)}">{esc(label)}</option>'
    gallery += '</select></label><label class="field" for="select-contrast">Measure<select id="select-contrast"><option value="levels">Control / Interact</option><option value="delta">Delta: Interact − Control</option></select></label><label class="field" for="select-layout">View<select id="select-layout"><option value="panels">Side-by-side models</option><option value="overlay">Overlay models</option></select></label>'
    for group, options in [("model", {m: MODEL_LABELS.get(m, m.capitalize()) for m in data["models"]}), ("axis", TIME_AXES), ("condition", {c:c.capitalize() for c in data["conditions"]})]:
        gallery += f'<fieldset><legend>{esc({"model":"Models", "axis":"Time axes", "condition":"Conditions"}[group])}</legend><div class="choices">'
        for value, label in options.items():
            unavailable = group == "model" and value not in available_models
            checked = ' checked' if not unavailable and (group != "axis" or value == "budget") else ''
            disabled = ' disabled' if unavailable else ''
            caption = label + ' (unavailable)' if unavailable else label
            gallery += f'<label><input type="checkbox" data-filter="{group}" value="{esc(value)}"{checked}{disabled}> {esc(caption)}</label>'
        gallery += '</div></fieldset>'
    gallery += '</section><div class="toolbar"><button id="compare-models">Compare models</button><button id="compare-times">Compare time axes</button><button id="overlay-models">Overlay models</button><button id="reset-zoom">Reset zoom</button></div><p id="contrast-note" class="hint"></p><p class="hint">Hover for values. Drag horizontally inside a chart to zoom; double-click to reset. Click a legend label to hide/show a curve. Colors identify models; solid = Control, dashed = Interact.</p><p id="result-count" role="status"></p><div id="live-charts" class="figures"></div><details class="exports"><summary>Original PNG / SVG exports</summary><div id="static-exports">'
    for figure in catalog:
        filename = figure["filename"]
        title = f'{MODEL_LABELS.get(figure["model"], figure["model"].capitalize())} · {METRICS[figure["metric"]]} · {TIME_AXES[figure["axis"]]}'
        gallery += f'<article hidden data-metric="{esc(figure["metric"])}" data-axis="{esc(figure["axis"])}" data-model="{esc(figure["model"])}"><h2 style="font-size:17px">{esc(title)}</h2><a href="{filename}.svg">SVG</a> · <a href="{filename}.png">PNG</a><img loading="lazy" src="{filename}.png" alt="{esc(title)}"></article>'
    gallery += '</div></details><h2>Final submitted scores</h2><p>Summary tables, independent of trajectory time axes.</p>'
    for model in data["models"]:
        if any(r["model"] == model for r in data["runs"]):
            filename = f'final-score-table-{model}'
            gallery += f'<details><summary>{esc(MODEL_LABELS.get(model, model.capitalize()))} final scores</summary><a href="{filename}.svg">SVG</a> · <a href="{filename}.png">PNG</a><img loading="lazy" src="{filename}.png" alt="{esc(model)} final scores"></details>'
    if data.get("final_outcome_table"):
        gallery += '<h2>Submission rate and final scores</h2><p>All agents in finished or failed runs. The submitted-score column uses actual submissions only. The separate imputed column caps each non-submitter’s own best noiseless experiment score at the lowest submitted score in its run. Unknown cases are retained, so the group mean is unknown if any agent cannot be scored. <a href="final-outcome-table.csv">Download summary CSV</a> · <a href="final-agent-outcomes.csv">Agent accounting CSV</a>.</p><div style="overflow-x:auto"><table style="border-collapse:collapse;width:100%;text-align:left"><tr><th>Model</th><th>Condition</th><th>Submitted / agents</th><th>Submission rate</th><th>Mean submitted noiseless score</th><th>Mean final score with imputation</th><th>Imputed agents</th><th>Unresolved agents</th></tr>'
        for row in data["final_outcome_table"]:
            cells = [MODEL_LABELS.get(row["model"], row["model"]), row["condition"].capitalize(),
                     f'{row["submitted_agents"]}/{row["agents"]}',
                     f'{row["submission_rate"]:.1%}' if row["submission_rate"] is not None else 'Unknown',
                     f'{row["mean_submitted_final_score"]:.4f}' if row["mean_submitted_final_score"] is not None else 'Unknown',
                     f'{row["mean_final_score_with_imputation"]:.4f}' if row["mean_final_score_with_imputation"] is not None else 'Unknown',
                     str(row["imputed_agents"]), str(row["unresolved_agents"])]
            gallery += '<tr>' + ''.join(f'<td style="padding:8px;border-bottom:1px solid #ddd">{esc(value)}</td>' for value in cells) + '</tr>'
        gallery += '</table></div>'
    if data.get("completion_table"):
        gallery += '<h2>Run completion</h2><p>Final submissions and measurement coverage are separate. <a href="completion-table.csv">Download CSV</a>.</p><div style="overflow-x:auto"><table style="border-collapse:collapse;width:100%;text-align:left"><tr><th>Model</th><th>Condition</th><th>Status</th><th>Submitted</th><th>Measured</th><th>End reasons</th></tr>'
        for row in data["completion_table"]:
            cells = [MODEL_LABELS.get(row["model"], row["model"]), row["condition"].capitalize(), row["status"],
                     f'{row["submitted_agents"]}/{row["agents"]}', f'{row["measured_agents"]}/{row["agents"]}',
                     ', '.join(f'{key}: {value}' for key, value in row["end_reasons"].items())]
            gallery += '<tr>' + ''.join(f'<td style="padding:8px;border-bottom:1px solid #ddd">{esc(value)}</td>' for value in cells) + '</tr>'
        gallery += '</table></div>'
    gallery += '<h2>Cost summary</h2><p>Selected terminal task episodes, including failed agents; separate no-data attempts excluded. <a href="cost-table.csv">Download CSV</a>.</p><div style="overflow-x:auto"><table style="border-collapse:collapse;width:100%;text-align:right"><thead><tr>'
    for label in ["Model", "Condition", "Runs", "Total USD", "Mean/run USD", "Mean/agent USD", "Reported responses", "Missing costs"]:
        gallery += f'<th style="padding:8px;border-bottom:1px solid #aaa">{label}</th>'
    gallery += '</tr></thead><tbody>'
    for row in data.get("cost_table", []):
        values = [MODEL_LABELS.get(row["model"], row["model"].capitalize()), row["condition"].capitalize(), row["runs"]]
        values += [f'{row[key]:.4f}' if row[key] is not None else 'Unknown'
                   for key in ["total_cost_usd", "mean_cost_per_run_usd", "mean_cost_per_agent_usd"]]
        values += [row["cost_reported_responses"], row["cost_unreported_responses"]]
        gallery += '<tr>' + ''.join(f'<td style="padding:8px;border-bottom:1px solid #ddd">{esc(str(value))}</td>' for value in values) + '</tr>'
    rows = data.get("cost_table", [])
    if rows:
        totals = data.get("cost_totals") or cost_totals(rows)
        values = ["Total", "All conditions", totals["runs"]]
        values += [f'{totals[key]:.4f}' if totals[key] is not None else 'Unknown'
                   for key in ["total_cost_usd", "mean_cost_per_run_usd", "mean_cost_per_agent_usd"]]
        values += [totals["cost_reported_responses"], totals["cost_unreported_responses"]]
        gallery += '<tr id="cost-total-row" style="font-weight:600">' + ''.join(
            f'<td style="padding:8px;border-top:2px solid #aaa">{esc(str(value))}</td>' for value in values) + '</tr>'
    gallery += '</tbody></table></div>'
    chart_path = output / "chart-data.json"
    chart_data = json.loads(chart_path.read_text()) if chart_path.exists() else {}
    payload = json.dumps(chart_data, allow_nan=False).replace("<", "\\u003c")
    gallery += f'<script id="chart-data" type="application/json">{payload}</script><script src="gallery.js"></script></main></html>'
    (output / "index.html").write_text(gallery)
    shutil_source = Path(__file__).with_name("cross_provider_gallery.js")
    (output / "gallery.js").write_text(shutil_source.read_text())



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["collect", "plot"])
    parser.add_argument("output", type=Path)
    parser.add_argument("--batch", type=Path)
    args = parser.parse_args()
    if args.mode == "collect":
        if args.batch is None:
            parser.error("collect requires --batch")
        collect(args.batch, args.output)
    else:
        plot(args.output)
