import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "cross_provider_plots", Path(__file__).resolve().parents[1] / "scripts/plot_cross_provider.py"
)
plots = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plots)


def test_best_scores_use_observed_agents_and_accepted_budget():
    events = [
        {"sequence": 1, "kind": "experiment_started"},
        {"sequence": 2, "kind": "experiment_started"},
        {
            "sequence": 3,
            "kind": "experiment_completed",
            "agent": 0,
            "elapsed_seconds": 15,
            "record": {"parameters": [-5]},
        },
        {
            "sequence": 4,
            "kind": "experiment_completed",
            "agent": 1,
            "elapsed_seconds": 20,
            "record": {"parameters": [-4]},
        },
        {"sequence": 5, "kind": "experiment_started"},
        {
            "sequence": 6,
            "kind": "experiment_completed",
            "agent": 0,
            "elapsed_seconds": 30,
            "record": {"parameters": [-6]},
        },
    ]
    points, best, sequences, counts, accepted = plots.measured_points(
        events, 2, 4, 0, 40, lambda parameters: parameters[0]
    )
    assert points[0]["mean_agent_best"] == -5
    assert points[0]["observed_agents"] == 1
    assert points[1]["observed_agents"] == 2
    assert points[0]["maximum_agent_best"] == -5  # Missing agents must not be imputed as zero.
    assert points[0]["budget"] == 0.5  # Both budgets consumed before the first result.
    assert points[1]["mean_agent_best"] == -4.5
    assert points[2]["mean_agent_best"] == -4.5  # A worse observation cannot reduce best-so-far.
    assert points[2]["maximum_agent_best"] == -4
    assert points[-1]["time"] == 1 and points[-1]["budget"] == 0.75
    assert best == [-5, -4]
    assert sequences == [1, 2, 5] and counts == [1, 2, 3] and accepted == 3


def test_final_table_uses_pooled_agents_and_run_weighted_maxima_and_sample_sd():
    result = plots.final_stats([{"final_scores": [1, 3]}, {"final_scores": [10]}])
    assert result["mean_final_score"] == pytest.approx(14 / 3)
    assert result["mean_maximum_final_score"] == 6.5
    assert result["mean_within_run_sd"] == pytest.approx(2**0.5)
    assert result["submitted_agents"] == 3


def test_experiment_steps_align_agents_without_using_later_results():
    # Agent 0 finishes three experiments before agent 1 finishes its first.
    events = [
        {"kind": "experiment_completed", "agent": agent, "record": {"parameters": [score]}}
        for agent, score in [(0, 1), (0, 9), (0, 2), (1, 3), (1, 4)]
    ]
    events += [{"kind": "agent_finished", "agent": agent} for agent in range(2)]
    points = plots.experiment_step_points(events, 2, 3, lambda p: p[0])
    assert points == [
        {"step": 1, "mean_agent_best": 2, "maximum_agent_best": 3, "observed_agents": 2},
        {"step": 2, "mean_agent_best": 6.5, "maximum_agent_best": 9, "observed_agents": 2},
        {"step": 3, "mean_agent_best": 6.5, "maximum_agent_best": 9, "observed_agents": 2},
    ]


def test_interaction_steps_include_final_work_and_carry_finished_agents():
    events = [
        {"kind": "experiment_completed", "agent": 0, "sequence": 10},
        {"kind": "experiment_completed", "agent": 0, "sequence": 20},
        {"kind": "experiment_completed", "agent": 1, "sequence": 50},
    ]
    interactions = {
        "wait_calls": [{"agent": 0, "sequence": 5}, {"agent": 0, "sequence": 15},
                       {"agent": 0, "sequence": 25}, {"agent": 1, "sequence": 30}],
        "discovered_either": [{"agent": 0, "sequence": 12}, {"agent": 1, "sequence": 40}],
    }
    events += [{"kind": "agent_finished", "agent": 0, "sequence": 40},
               {"kind": "agent_finished", "agent": 1, "sequence": 60}]
    points = plots.interaction_step_points(events, interactions, 2, 2)
    assert points == [
        {"step": 1, "observed_agents": 2, "wait_calls": 2, "discovered_either": 0.5},
        {"step": 2, "observed_agents": 2, "wait_calls": 4, "discovered_either": 1},
    ]


def test_every_metric_has_every_time_axis_and_exports_are_filterable(tmp_path):
    data = {"models": ["gemini", "qwen"], "conditions": ["control", "interact"], "runs": [
        {"model": "gemini", "experiment_duration_seconds": 15},
        {"model": "qwen", "experiment_duration_seconds": 15},
    ]}
    catalog = plots.figure_catalog(data)
    assert len(catalog) == 2 * len(plots.METRICS) * len(plots.TIME_AXES)
    assert len({figure["filename"] for figure in catalog}) == len(catalog)
    plots.render_gallery(tmp_path, data, catalog)
    html = (tmp_path / "index.html").read_text()
    assert html.count('<article hidden data-metric=') == len(catalog)
    assert 'data-filter="metric"' in html and 'data-filter="axis"' in html
    assert 'wait-call-totals.csv' in html
    assert 'measurement delays of 15 seconds' in html
    assert (tmp_path / "gallery.js").exists()


def test_cost_receipts_are_not_double_counted_and_missing_is_unknown():
    events = [
        {"kind": "provider_response_metadata", "agent": 0, "response_id": "a", "sequence": 1,
         "elapsed_seconds": 1, "metadata": {"usage": {"cost": 0.2}}},
        {"kind": "model_response", "agent": 0, "response_id": "a", "raw_usage": {"cost": 0.2}},
        {"kind": "provider_response_metadata", "agent": 0, "response_id": "b", "sequence": 3,
         "elapsed_seconds": 2, "metadata": {"usage": {"cost": 0}}},
        {"kind": "provider_response_metadata", "agent": 1, "response_id": "c", "sequence": 4,
         "elapsed_seconds": 3, "metadata": {"usage": {}}},
    ]
    costs, missing = plots.cost_events(events)
    assert sum(e["cost_usd"] for e in costs) == 0.2
    assert len(costs) == 2 and missing == 1
    rows = plots.cost_table([{"model": "gemini", "condition": "control", "agents": 2,
                             "known_cost_usd": .2, "cost_reported_responses": 2,
                             "cost_unreported_responses": 1}], ["gemini"], ["control"])
    assert rows[0]["known_total_cost_usd"] == .2
    assert rows[0]["total_cost_usd"] is None and rows[0]["mean_cost_per_run_usd"] is None


def test_cost_steps_sum_dollars_not_number_of_receipts():
    events = [{"kind": "experiment_completed", "agent": 0, "sequence": 10},
              {"kind": "experiment_completed", "agent": 1, "sequence": 20}]
    interactions = {"cost_usd": [{"agent": 0, "sequence": 5, "cost_usd": .2},
                                 {"agent": 0, "sequence": 15, "cost_usd": .8},
                                 {"agent": 1, "sequence": 15, "cost_usd": .3}]}
    assert plots.interaction_step_points(events, interactions, 2, 1)[0]["cost_usd"] == .5


def test_deltas_pair_before_averaging_and_require_both_values():
    runs = [
        {"repetition": 1, "condition": "control", "values": [1., 2.]},
        {"repetition": 1, "condition": "interact", "values": [float("nan"), 5.]},
        {"repetition": 2, "condition": "control", "values": [float("nan"), 10.]},
        {"repetition": 2, "condition": "interact", "values": [10., 7.]},
    ]
    result = plots.paired_delta_series(runs, "metric", "time", [0., 1.], lambda r, *args: r["values"])
    assert result == {"x": [1.], "y": [0.], "matched_pairs": [2]}


def test_cost_totals_weight_averages_by_runs_and_agents():
    rows = [
        {"known_total_cost_usd": 2., "runs": 1, "agents": 10,
         "cost_reported_responses": 20, "cost_unreported_responses": 0},
        {"known_total_cost_usd": 4., "runs": 3, "agents": 30,
         "cost_reported_responses": 40, "cost_unreported_responses": 0},
    ]
    totals = plots.cost_totals(rows)
    assert totals["total_cost_usd"] == 6
    assert totals["mean_cost_per_run_usd"] == 1.5
    assert totals["mean_cost_per_agent_usd"] == .15
    assert totals["cost_reported_responses"] == 60 and totals["cost_unreported_responses"] == 0
    rows[0]["cost_unreported_responses"] = 1
    assert plots.cost_totals(rows)["total_cost_usd"] is None


def test_step_deltas_require_all_matched_pairs_at_every_step():
    runs = [
        {"repetition": 1, "condition": "control", "values": [1., 2.]},
        {"repetition": 1, "condition": "interact", "values": [2., 4.]},
        {"repetition": 2, "condition": "control", "values": [3., float("nan")]},
        {"repetition": 2, "condition": "interact", "values": [4., 8.]},
    ]
    result = plots.paired_delta_series(runs, "metric", "step", [1, 2], lambda r, *args: r["values"], require_all_pairs=True)
    assert result == {"x": [1.], "y": [1.], "matched_pairs": [2]}


def test_unfinished_agents_are_not_carried_forward():
    events = [{"kind": "experiment_completed", "agent": 0, "sequence": 1,
               "record": {"parameters": [2]}}]
    assert len(plots.experiment_step_points(events, 1, 2, lambda p: p[0])) == 1
    assert len(plots.interaction_step_points(events, {"wait_calls": []}, 1, 2)) == 1
    events.append({"kind": "agent_finished", "agent": 0, "sequence": 2})
    assert len(plots.experiment_step_points(events, 1, 2, lambda p: p[0])) == 2
    assert len(plots.interaction_step_points(events, {"wait_calls": []}, 1, 2)) == 2


def test_zero_experiment_finished_agent_has_unknown_best_but_run_maximum_is_defined():
    events = [
        {"kind": "experiment_completed", "agent": 0, "record": {"parameters": [-2]}},
        {"kind": "agent_finished", "agent": 0},
        {"kind": "agent_finished", "agent": 1},
    ]
    points = plots.experiment_step_points(events, 2, 2, lambda p: p[0])
    assert len(points) == 2
    assert all(p["mean_agent_best"] is None for p in points)
    assert all(p["maximum_agent_best"] == -2 for p in points)


def test_submission_rate_keeps_failed_runs_and_scores_remain_conditional():
    rows = [
        {'model': 'a', 'condition': 'control', 'status': 'finished', 'agents': 10,
         'submitted_agents': 2, 'scored_submissions': 2, 'mean_submitted_final_score': -1},
        {'model': 'a', 'condition': 'control', 'status': 'error', 'agents': 10,
         'submitted_agents': 0, 'scored_submissions': 0, 'mean_submitted_final_score': None},
    ]
    result = plots.final_outcome_stats(rows)[0]
    assert result['submission_rate'] == .1
    assert result['mean_submitted_final_score'] == -1  # Missing submissions are not zero scores.
    rows[0]['status'] = 'running'
    assert plots.final_outcome_stats(rows)[0]['submission_rate'] is None


def test_final_imputation_uses_own_best_and_preserves_actual_submissions():
    reports = [{'agent': 0, 'reason': 'submitted', 'true_objective': .3},
               {'agent': 1, 'reason': 'submitted', 'true_objective': .8},
               {'agent': 2, 'reason': 'time_limit'}, {'agent': 3, 'reason': 'turn_limit'}]
    events = [{'kind': 'experiment_completed', 'agent': agent,
               'record': {'parameters': [score]}} for agent, score in [(0, .9), (2, -.4), (2, -.2), (3, .7)]]
    rows = plots.final_agent_outcomes(reports, events, 4, lambda p: p[0])
    assert [r['score_with_imputation'] for r in rows] == [.3, .8, -.2, .3]
    assert [r['score_source'] for r in rows] == ['submitted', 'submitted', 'imputed', 'imputed']
    # Poor non-submitters cannot borrow the run's best experimental performance.
    assert rows[2]['own_best_experiment_score'] == -.2


def test_final_imputation_does_not_invent_scores_without_experiments_or_submissions():
    reports = [{'agent': 0, 'reason': 'submitted', 'true_objective': -.1},
               {'agent': 1, 'reason': 'turn_limit'}]
    assert plots.final_agent_outcomes(reports, [], 2, lambda p: p[0])[1]['score_source'] == 'unknown'
    events = [{'kind': 'experiment_completed', 'agent': 0, 'record': {'parameters': [.4]}}]
    rows = plots.final_agent_outcomes([{'agent': 0, 'reason': 'time_limit'}], events, 1, lambda p: p[0])
    assert rows[0]['score_with_imputation'] is None


def test_imputed_group_mean_keeps_every_agent_and_unknowns():
    base = {'model': 'x', 'condition': 'control', 'status': 'finished', 'agents': 4,
            'submitted_agents': 2, 'scored_submissions': 2, 'mean_submitted_final_score': .55,
            'mean_final_score_with_imputation': .3, 'imputed_agents': 2, 'unresolved_agents': 0}
    result = plots.final_outcome_stats([base])[0]
    assert result['mean_final_score_with_imputation'] == .3
    assert result['submission_rate'] == .5
    assert result['imputed_agents'] == 2
    other = dict(base, mean_final_score_with_imputation=None, unresolved_agents=1)
    assert plots.final_outcome_stats([base, other])[0]['mean_final_score_with_imputation'] is None


def test_saved_model_identity_labels_distinguish_deepseek_versions():
    for model, expected in [('deepseek/deepseek-v3.2', 'DeepSeek V3.2'),
                            ('deepseek/deepseek-v3.1-terminus', 'DeepSeek V3.1 Terminus')]:
        manifest = {'runs': [{'model_key': 'deepseek', 'model': model}]}
        assert plots.saved_model_labels(manifest)['deepseek'] == expected


def test_completed_pair_keeps_failed_agent_but_rejects_no_data_routing_runs(tmp_path):
    import json

    pair = [{'run_id': 'control', 'status': 'error', 'agents': 2},
            {'run_id': 'interact', 'status': 'finished', 'agents': 2}]
    for entry in pair:
        p = tmp_path / entry['run_id']
        p.mkdir()
        reports = [{'agent': 0, 'reason': 'submitted', 'experiments_completed': 10},
                   {'agent': 1, 'reason': 'error', 'experiments_completed': 10}]
        (p / 'summary.json').write_text(json.dumps({'agents': reports}))
    assert plots.pair_has_terminal_task_data(tmp_path, pair)
    (tmp_path / 'control' / 'summary.json').write_text(json.dumps({'agents': [
        {'agent': i, 'reason': 'error', 'experiments_completed': 0} for i in range(2)
    ]}))
    assert not plots.pair_has_terminal_task_data(tmp_path, pair)


def test_collect_keeps_wall_active_budget_and_step_separate(tmp_path, monkeypatch):
    import json
    import shutil
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from mad.config import RolloutConfig
    from mad.task import SyntheticObjective

    cfg = RolloutConfig(agents=2, experiment_budget=2)
    objective = SyntheticObjective(cfg.task)
    batch = tmp_path / 'batch'
    output = tmp_path / 'figures'
    code = batch / 'inputs/code/src/mad'
    code.mkdir(parents=True)
    shutil.copyfile(Path(__file__).resolve().parents[1] / 'src/mad/task.py', code / 'task.py')
    entries = []
    for condition in ['control', 'interact']:
        run = f'test-{condition}-001'
        p = batch / run
        p.mkdir()
        (p / 'config.json').write_text(json.dumps(cfg.model_dump(mode='json')))
        a, b = [.4] * 8, [.6] * 8
        reports = [{'agent': i, 'reason': 'submitted', 'parameters': b,
                    'true_objective': objective.evaluate(b), 'experiments_completed': 2,
                    'experiments_used': 2} for i in range(2)]
        (p / 'summary.json').write_text(json.dumps({'agents': reports}))
        (p / 'note_ownership.json').write_text('{}')
        (p / 'identities.json').write_text(json.dumps([{'agent': i, 'author_id': str(i)} for i in range(2)]))
        events = []
        def event(kind, wall, active, agent=None, **data):
            if "record" in data:
                data["record"]["run_id"] = f"measurement-{agent}-{data['record']['parameters'][0]}"
            events.append(dict(sequence=len(events)+1, kind=kind, elapsed_seconds=wall,
                               active_elapsed_seconds=active, agent=agent, **data))
        event('agent_started', 0, 0, 0)
        event('agent_started', 0, 0, 1)
        event('experiment_started', 1, 1, 0, record={'parameters': a})
        event('experiment_completed', 2, 2, 0, record={'parameters': a})
        event('cohort_pause_started', 4, 4)
        event('cohort_pause_ended', 14, 4)
        event('experiment_started', 15, 5, 0, record={'parameters': b})
        event('experiment_completed', 16, 6, 0, record={'parameters': b})
        event('experiment_started', 17, 7, 1, record={'parameters': a})
        event('experiment_completed', 18, 8, 1, record={'parameters': a})
        event('experiment_started', 18, 8, 1, record={'parameters': b})
        event('experiment_completed', 19, 9, 1, record={'parameters': b})
        event('agent_finished', 20, 10, 0, report=reports[0])
        event('agent_finished', 20, 10, 1, report=reports[1])
        (p / 'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
        entries.append(dict(run_id=run, model_key='test', model='test/model',
                            condition=condition, status='finished', agents=2, repetition=1))
    (batch / 'manifest.json').write_text(json.dumps({'status':'finished', 'runs':entries,
        'conditions':['control','interact'], 'model_configs':{'test':'unused'}}))
    plots.collect(batch, output)
    data = json.loads((output / 'outcomes.json').read_text())
    for run in data['runs']:
        assert run['duration_seconds'] == 20
        assert run['active_duration_seconds'] == 10
        assert run['pause_duration_seconds'] == 10
        assert run['points'][1]['time'] == .8
        assert run['points'][1]['active_time'] == .6
        assert run['points'][1]['budget'] == .5
        assert run['experiment_step_points'][-1]['step'] == 2
        assert run['final_scores'] == [objective.evaluate(b)] * 2
