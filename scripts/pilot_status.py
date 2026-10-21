"""Read-only per-model timing and cost table for a saved or running pilot."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def status(batch):
    manifest = json.loads((batch / 'manifest.json').read_text())
    now = datetime.now(timezone.utc).timestamp()
    rows = []
    for model in manifest['model_configs']:
        runs = [r for r in manifest['runs'] if r['model_key'] == model]
        walls, actives, pauses = [], [], []
        experiments, cost, missing = 0, 0.0, 0
        for run in runs:
            path = batch / run['run_id'] / 'events.jsonl'
            if not path.exists():
                continue
            events = []
            for line in path.read_text().splitlines():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    break
            starts = [e for e in events if e['kind'] == 'agent_started']
            if not starts:
                continue
            first = min(starts, key=lambda e: e['elapsed_seconds'])
            frozen_at = None
            for event in events:
                kind = event['kind']
                if kind == 'cohort_pause_started':
                    frozen_at = datetime.fromisoformat(event['timestamp']).timestamp()
                elif kind == 'cohort_pause_clock_resumed':
                    frozen_at = None
                experiments += kind == 'experiment_completed'
                if kind == 'provider_response_metadata':
                    value = (event['metadata'].get('usage') or {}).get('cost')
                    missing += value is None
                    cost += value or 0
            running = run['status'] == 'running'
            ends = [e for e in events if e['kind'] == 'agent_finished']
            wall = (now - datetime.fromisoformat(first['timestamp']).timestamp() if running
                    else max((e['elapsed_seconds'] for e in ends), default=events[-1]['elapsed_seconds']) - first['elapsed_seconds'])
            pause = events[-1].get('paused_seconds', 0)
            if frozen_at is not None and running:
                pause += max(0, now - frozen_at)
            walls.append(wall / 60)
            pauses.append(pause / 60)
            actives.append(max(0, wall - pause) / 60)
        rows.append({'model': model, 'status': 'finished' if all(r['status'] == 'finished' for r in runs)
                     else 'running' if any(r['status'] == 'running' for r in runs)
                     else ', '.join(sorted({r['status'] for r in runs})),
                     'wall_minutes': round(max(walls, default=0), 1),
                     'active_minutes': round(max(actives, default=0), 1),
                     'cooldown_minutes': round(max(pauses, default=0), 1),
                     'experiments': experiments, 'reported_cost_usd': cost,
                     'missing_cost_receipts': missing})
    return {'status': manifest['status'], 'models': rows,
            'timing_definition': 'Maximum condition duration within each matched model pair; not summed.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('batch', type=Path)
    args = parser.parse_args()
    print(json.dumps(status(args.batch), indent=2))
