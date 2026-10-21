# Full experiment on another machine

The active plan is `experiment.toml`: 20 matched sets across Z.ai GLM 5.3 Flash,
Anthropic Claude Haiku 5.5 and OpenAI GPT-6 Luna. Each model runs Control and
Interact together; models and matched sets run sequentially. This is 120 runs,
1,200 agent sessions, and at most 12,000 experiments. Each agent has ten
experiments, 80 model turns, a fixed 32,768-token response ceiling and 60 active
minutes. Experiments are instant; agents start at one-second intervals.

API recovery pauses exclude frozen time from active clocks. Each matched pair
still has a separate cumulative 30-minute API freeze allowance. Empty truncated
responses terminate without retry; their cost is retained and final submission
stays missing. Timeouts are reported and the batch continues. An agent/API error
stops later pairs. Review submission and timeout rates to decide whether to remove
GLM; do not select its inclusion using observed scores. Changing the roster after
looking at results should be documented in the writeup.

## Hardware

At most 20 agent containers run together, plus two filesystem helper containers.
Each agent container is capped at 512 MiB and one CPU; these are limits, not
reservations. The aggregate agent ceiling is 10 GiB, plus Docker/helper/host
process overhead. A 16 GB RAM host is workable for modest workloads: start with
about 10 GB allocated to Docker Desktop and close memory-heavy apps. This does
not guarantee that 20 containers can all reach their memory caps simultaneously.
Do not lower agent memory caps just for one model or condition.

Four CPU cores can run the job, but eight give more room for simultaneous Python
analysis. The per-call Python timeout remains 20 seconds, so resource contention
can alter outcomes. Run the offline capacity check below on the destination host.
It loads NumPy/SciPy/pandas and a modest dense matrix workload in all 20 agent
containers and samples their aggregate memory. The preparation-machine check
passed with 2.22 GiB sampled aggregate agent memory and a slowest Python call
of 6.5 seconds; the destination machine still needs its own check. Passing establishes capacity for
that workload, not arbitrary agent programs or worst-case memory consumption.

Leave at least 20 GB free disk space for images, volumes, raw logs and figures.
Use the same image and resource settings throughout the experiment; capture the
Docker host/VM settings with the run. Docker image package versions are currently
installed from PyPI at build time, so transferring the pilot's existing image
is preferable when comparing to pilots. Keep the machine powered, awake and on a
stable network. The job may take a day or longer; API freezes add wall time.

## Setup and validation

From the repository root on the destination machine:

```sh
git checkout codex/small-cross-provider-experiment
git pull --ff-only
uv sync --locked
cp .env.example .env
```

Add `OPENROUTER_API_KEY` to `.env` locally. It is ignored by Git. Docker must be
running. Build the sandbox if the existing `mad-python:local` image has not been
transferred:

```sh
uv run --locked mad build
uv run --locked python scripts/check_machine_capacity.py
uv run --locked mad batch experiments/cross-provider-tinkering/experiment.toml --dry-run
uv run --locked mad preflight experiments/cross-provider-tinkering/experiment.toml --batch --output outputs/full-experiment-preflight
```

The capacity check and dry run make no API requests. The preflight is a small
paid two-turn compatibility check per model. Inspect its result before launching.
No full experiment has been launched from this handoff.

## Launch

Use a persistent terminal (for example, tmux) so disconnecting SSH does not kill
the runner. Choose a fresh output directory; the batch rejects an existing one.
Do not run multiple full batches concurrently on the 16 GB machine.

```sh
mkdir -p outputs/cross-provider-full
uv run --locked mad batch experiments/cross-provider-tinkering/experiment.toml --output outputs/cross-provider-full/run-01 > outputs/cross-provider-full/run-01.log 2>&1
```

The output snapshots the experiment, prompts and source, with Git provenance.
Watch the log and `run-01/manifest.json`. There is no automatic checkpoint resume
or safe whole-machine sleep workflow. If the batch stops, preserve the original
output and use a separate continuation definition/output for the remaining sets;
do not rerun completed sets into the same directory or overwrite their results.
Do not change an in-flight snapshot to alter its time or token limits.

## Review

After the run, use the experiment virtualenv for collection/auditing, then the
separate plotting environment for figures:

```sh
uv run --locked python scripts/review_coordinated_pause.py outputs/cross-provider-full/run-01 outputs/cross-provider-review/full --checks outputs/full-experiment-preflight
uv run --locked python scripts/plot_cross_provider.py collect outputs/cross-provider-review/full/figures --batch outputs/cross-provider-full/run-01
uv venv .venv-plot
uv pip install --python .venv-plot/bin/python -r experiments/cross-provider-tinkering/requirements-review.txt
.venv-plot/bin/python scripts/plot_cross_provider.py plot outputs/cross-provider-review/full/figures
```

Open `outputs/cross-provider-review/full/figures/index.html`. Raw pilot outputs,
API keys and generated full-run data are ignored by Git and remain on the machine
that produced them; transfer those separately if needed. Code, configs, viewer,
checks and this guide are committed on the experiment branch.
