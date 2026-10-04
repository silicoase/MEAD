# Four-agent interaction pilot

Run with `uv run --locked python scripts/run_pilot.py` from the repository root.
The script creates a new pilot directory and exports each run plus an overview.

Each run uses four GPT-6.1 Sol agents, 10 experiments per agent, 15-second
experiment delays, a 30-minute per-agent timeout, and simultaneous agent starts. Agent identities are
opaque and random. Notebook timestamps and reasoning summaries are enabled.
Each matched set runs its three conditions concurrently in isolated storage.
The second set starts after the first finishes.

- Control uses the current notebook and periodic-check instructions.
- Aware adds: "Other agents are actively working on this task."
- Interact adds: "Other agents are actively working on this task. You can interact
  with them as you see fit."

Repetition 1 uses objective seed 42 and noise seed 123. Repetition 2 uses
objective seed 43 and noise seed 124. Seeds and all settings are identical
across conditions within a repetition; the extra instruction is the only
configuration difference. Noise streams are matched by internal agent index;
random identities, model outputs, and execution timing are not matched.

Compare final scores for every agent and each run's mean/best score. Review
artifact use, repeat checks, peer recognition, messages in notes, replies,
proposed experiment assignments, and whether those assignments were followed.
File-tool flags are a navigation aid; inspect Python code for bulk lab reads.
