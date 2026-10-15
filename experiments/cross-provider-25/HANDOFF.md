# Three-model, 25-set experiment

Prepared at the user's request on 2026-10-13. **No preflight, pilot, or full run
has been launched. Wait for the user to check back before live execution.**

Models: Claude Haiku 5.5 (`anthropic/claude-haiku-5.5`), GPT-6 Luna
(`openai/gpt-6-luna`), and GPT-6.1 Sol (`openai/gpt-6.1-sol`). GLM is excluded.

Each model runs Control and Interact together in isolated labs. Models and sets
run sequentially, with at most 20 agent containers together. The unchanged
scientific settings are ten agents per condition, ten experiments per agent,
80 model turns, 60 active minutes, 32,768 completion tokens per response, instant
experiments, and a one-second starting stagger. Existing Control/Interact prompts
are copied unchanged. Reasoning and provider routing retain their defaults.

The user-requested cumulative API freeze allowance is **5,400 seconds (90
minutes) per matched pair**, shared across both conditions. Frozen intervals are
excluded from agent active clocks. This is separate from the 60-minute active
time limit. Historical definitions and output snapshots retain their old caps.

## Definitions

- `pilot.toml`: one matched set per model, six runs, 60 agents, up to 600
  measurements. Fresh objective/noise seeds 50/131; pilot data excluded from full
  analysis.
- `experiment.toml`: 25 matched sets per model, 150 runs, 1,500 agents, up to
  15,000 measurements. Fresh objective seeds 3000–3024 and noise seeds 4000–4024.
  This is a new experiment, separate from the completed 20-set Haiku/Luna batch.

Both dry runs passed. Model configurations were checked for identical settings
apart from their model routes, including the 90-minute freeze allowance.

## When the user returns

From the MEAD repository root, the small paid compatibility preflight is:

```sh
uv run --locked mad preflight experiments/cross-provider-25/pilot.toml --batch --output outputs/cross-provider-25-preflight
```

The pilot command is:

```sh
uv run --locked mad batch experiments/cross-provider-25/pilot.toml --output outputs/cross-provider-25-pilot/run-01
```

Use a persistent runner and fresh output directories when launching. Start live
tracking and monitoring at that time. If a directory already exists, preserve it
and choose a new attempt name. Report actual submissions, errors, API freezes,
reported costs and missing receipts. Compute per-model cost ×25 for the full-run
estimate. Do not launch the full experiment merely because the pilot finishes.

The full definition is `experiments/cross-provider-25/experiment.toml`.
The OpenRouter key remains in the ignored local `.env`; no credentials are
included here. The existing `mad-python:local` sandbox image and locked Python
environment were used for the completed prior experiment.

## Analysis

Use the implemented external/internal mention split: successful shared-note
writes/appends count as external; released reasoning and private assistant
messages are separate internal channels. Report reasoning-text coverage and keep
unknown reasoning distinguishable from zero mentions. Preserve raw run evidence,
including failed attempts, and keep pilots separate from formal runs.

The blog construction is owned by another session. This thread owns experiments,
analysis, graphs and export packets.


## Completed full batch and remote analysis

The accepted batch is `outputs/cross-provider-25-full/run-02`: 150 finished runs,
1,500 submissions, 14,780 experiments, $82.48239532 reported cost, no missing
cost receipts or coordinated-pause audit violations. `run-01` is a preserved
failed attempt and must not be pooled into the accepted scientific results.
Pilot data are separate. GLM is excluded.

Code belongs in Git; generated data and archives are ignored. To work elsewhere,
transfer the accepted raw batch while preserving its relative directory layout,
plus `outputs/cross-provider-review/three-model-25-full` for the existing analysis.
A private Hugging Face dataset repository is suitable for a versioned data copy.
Record its exact revision and the code commit together, and include SHA-256
checksums for transferred files. Do not include `.env`, API keys, or virtualenvs.
Keep failed-attempt evidence in a clearly separate provenance directory.

On the other machine, clone this code branch and restore the output directories,
then install the locked analysis environment and regenerate:

```sh
uv sync --group analysis
uv run python scripts/plot_cross_provider.py collect outputs/cross-provider-review/three-model-25-full/figures --batch outputs/cross-provider-25-full/run-02
uv run python scripts/plot_cross_provider.py plot outputs/cross-provider-review/three-model-25-full/figures
uv run python scripts/plot_blog_panels.py outputs/cross-provider-review/three-model-25-full/figures outputs/cross-provider-25-full/run-02 outputs/cross-provider-review/three-model-25-full/blog-panels
uv run python scripts/plot_final_scores.py outputs/cross-provider-review/three-model-25-full
```

No provider credentials or Docker are needed for this offline analysis. The
smaller figures ZIP contains collected data for figure iteration, but raw JSONL
logs and objective references are required to recompute interaction metrics.
