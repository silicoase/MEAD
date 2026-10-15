"""Read-only compact progress table for a multi-model batch."""
import argparse
import json
import time
from pathlib import Path

from live_progress import Progress


def status(batch):
    snapshot = Progress(batch).snapshot()
    rows = []
    for model in dict.fromkeys(r['model_key'] for r in snapshot['runs']):
        runs = [r for r in snapshot['runs'] if r['model_key'] == model]
        running = [r for r in runs if r['status'] == 'running']
        cooldown = max((max(0, r['reset_at'] - time.time()) for r in running if r['limited']), default=0)
        state = ('error' if any(r['status'] == 'error' for r in runs) else
                 'cooling off' if any(r['limited'] for r in running) else
                 'running' if running else
                 'finished' if all(r['status'] == 'finished' for r in runs) else 'queued')
        rows.append({'model': model, 'status': state,
                     'completed_runs': sum(r['status'] == 'finished' for r in runs),
                     'total_runs': len(runs), 'submissions': sum(r['submissions'] for r in runs),
                     'total_agents': sum(r['agents'] for r in runs),
                     'experiments': sum(r['experiments'] for r in runs),
                     'reported_cost_usd': sum(r['cost'] for r in runs),
                     'cooldown_remaining_seconds': round(cooldown)})
    result = {'batch_status': snapshot['status'], 'models': rows}
    destination = batch.parent / 'status.json'
    temporary = destination.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, indent=2)+'\n')
    temporary.replace(destination)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('batch', type=Path)
    args = parser.parse_args()
    print(json.dumps(status(args.batch), indent=2))
