# Three-model, 25-set experiment

Prepared at the user's request on 2026-10-13. **Completed and audited.**
The accepted full batch is `outputs/cross-provider-25-full/run-02`; all 150 runs
and 1,500 submissions finished. Data transfer is verified, monitoring is paused,
and local tracker servers have been retired. Continue with offline analysis;
this handoff does not authorize new scientific runs.

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

## Execution history

The compatibility preflight and one-pair-per-model pilot completed before the
full experiment. The first full attempt (`run-01`) failed on shared-provider-pool
429s. The user authorized a recovery fix and a fresh attempt (`run-02`), which
completed. Recovery recognizes explicit account and shared-provider-pool limits
and respects reset metadata; the cumulative pause cap remains 90 minutes.

Historical definitions, failed-attempt evidence, and pilot results are retained.
Do not rerun completed sets or mix attempts into the accepted scientific batch.

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

## Verified private dataset

- Dataset: https://huggingface.co/datasets/connacher-silicoase/MEAD-cross-provider
- Visibility: private; publication is a separate decision.
- Pinned data revision: `694e77881e3ed9b97d140e7434917a91c9f36222`
- Source code snapshot: `c538ff6` on `codex/small-cross-provider-experiment`.
- Eight uploaded files verified by size and SHA-256: remote LFS hashes for
  large files and downloaded content hashes for small files.

Code belongs in Git; generated data and archives are ignored. Authenticate on
the destination machine, then download the pinned snapshot:

```sh
hf auth login
hf download connacher-silicoase/MEAD-cross-provider --repo-type dataset --revision 694e77881e3ed9b97d140e7434917a91c9f36222 --local-dir mead-data
```

Verify `SHA256SUMS` inside `mead-data` (`shasum -a 256 -c SHA256SUMS` on macOS).
From the MEAD checkout, extract `raw-results.tar.gz` and `analysis.tar.gz` using
their full paths. Archives preserve repository-relative output paths.
`attempt-provenance.tar.gz` contains the excluded failed attempt and audit
provenance; extract separately when needed. `source.tar.gz` is an alternative
to cloning the pinned source commit. No credentials or virtualenvs are included.

On the other machine, clone this code branch and restore the output directories,
then install the locked analysis environment and regenerate:

```sh
uv sync --locked --group analysis --python 3.14
uv run python scripts/plot_cross_provider.py collect outputs/cross-provider-review/three-model-25-full/figures --batch outputs/cross-provider-25-full/run-02
uv run python scripts/plot_cross_provider.py plot outputs/cross-provider-review/three-model-25-full/figures
uv run python scripts/plot_blog_panels.py outputs/cross-provider-review/three-model-25-full/figures outputs/cross-provider-25-full/run-02 outputs/cross-provider-review/three-model-25-full/blog-panels
uv run python scripts/plot_final_scores.py outputs/cross-provider-review/three-model-25-full
```

No provider credentials or Docker are needed for this offline analysis. The
smaller figures ZIP contains collected data for figure iteration, but raw JSONL
logs and objective references are required to recompute interaction metrics.
