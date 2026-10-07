# swarm-hackathon-demo

A hackathon demo with 20 matched repetitions of control, aware, and interact:
60 runs, four agents per run, and up to 2,400 accepted measurements.

| File | Purpose |
| --- | --- |
| `config.toml` | Shared model, task, budget, timing, and environment settings. |
| `experiment.toml` | Conditions, repetitions, prompt paths, and seed schedule. |
| `prompts/` | Three condition prompts copied from the pilot. |
| `DATASET_CARD.md` | Hugging Face documentation draft. |

The common setup uses GPT-6.1 Sol, 10 measurements per agent, 80 turns,
30-minute per-agent timeouts, 15-second measurement delays, shared lab records
and notes, and simultaneous starts. Note timestamps and reasoning summaries
are enabled. The task has eight dimensions, [0,1] bounds, and noise SD 0.1.
Control asks for notebook writing and periodic lab checks. Aware adds explicit
peer awareness; interact additionally permits interaction.

Repetition r uses objective seed 43+r and noise seed 124+r (44–63 / 125–144).
The runner derives these seeds from the manifest and saves each resolved config.
The three conditions run concurrently in isolated labs; repetitions run sequentially.
UUIDs, model outputs, and execution timing are not matched. API/infrastructure
errors stop later repetitions; there are no automatic whole-run retries.

From the repository root, with Docker running and an API key in .env or the shell:

```sh
uv sync --locked
uv run --locked mad build
uv run --locked mad batch experiments/swarm-hackathon-demo/experiment.toml --dry-run
uv run --locked mad batch experiments/swarm-hackathon-demo/experiment.toml
```

Dry-run validation makes no model calls. Launching incurs API charges.

Results land in `outputs/swarm-hackathon-demo/<UTC-timestamp>-<id>/`.
All outputs are Git-ignored. The batch contains manifest.json, index.html,
frozen config/prompt/source inputs, dependency versions, commit/dirty status,
and SHA-256 checksums. Each run saves its resolved config, timestamps, events,
runtime/image metadata, outcomes, identities, final artifacts, and HTML explorer.
Credentials are excluded from input snapshots.

The completed raw-first dataset is publicly released on
[Hugging Face as v1.0.0](https://huggingface.co/datasets/connacher-silicoase/MEAD/tree/v1.0.0).
See [PACKAGING.md](PACKAGING.md) for the local package and transformation record,
[RELEASE_AUDIT.md](RELEASE_AUDIT.md) for collection checks, and
[PUBLIC_RELEASE_VERIFICATION.json](PUBLIC_RELEASE_VERIFICATION.json) for remote
verification. Generated data uses CC BY 4.0; included MAD source, copied prompts
and HTML viewer code retain their existing license and notices.

Optional Parquet preparation is available through
[PARQUET_EXPORT.md](PARQUET_EXPORT.md). The exporter preserves raw records, audits
submissions, and writes tables/schema/provenance into a new directory. The
initial Hugging Face release remains raw-only; tables can be added later.
