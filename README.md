# MAD — Measuring Agent Discovery

MAD provides configurable rollouts for studying whether independently
working AI agents discover one another through task artifacts and develop
coordination without being instructed to do so.

The current task gives agents the same synthetic optimization problem,
independent noisy measurements, and individual experiment budgets. Agents
have private workspaces and access to a common lab containing experiment records
and voluntary notes.

MAD runs locally with Docker, including Docker Desktop on
macOS. Python and the OpenAI Agents SDK run on the host; agent-generated Python
runs in a separate container per agent. See [DESIGN.md](DESIGN.md) for the
architecture and experiment setup, and [docs/implementation.md](docs/implementation.md)
for the current choices and limitations.

## License

MAD is source-available under the custom
[Silicoase Noncommercial License, Version 2.0](LICENSE), not an open-source
license. Noncommercial use and adaptation, including personal hobby projects
and noncommercial academic research, are permitted. Ordinary salaries, stipends,
scholarships, and non-industry grants do not by themselves make academic research
commercial.

Commercial use, use by or on behalf of a for-profit company, industry-sponsored
research, and paid services (including cost-recovery services) require a separate
written agreement with Silicoase, Inc. Educational or nonprofit status does not
automatically exempt those activities.

There is no requirement to publish or provide the source of modifications,
including when distributing executable copies or operating modified versions
for remote users. Retain the license and copyright/attribution notices when
sharing covered material, and identify modifications. The underlying MAD code
remains subject to its noncommercial restrictions even when included in a fork.

The Silicoase name and logo may not imply endorsement or identify a fork as an
official release. A modified interface retaining original branding must clearly
identify itself as modified and unofficial. Research outputs are not automatically
covered merely because MAD generated them. Exported HTML reports do contain
covered viewer code and branding: include a copy of LICENSE with reports you
share and retain legal notices. Third-party components retain their own licenses.

See [licensing notes](docs/licensing.md) for scope, provenance, and legal review considerations.

The rollout controller, harness, environment, task, and recorder are separate
components so others can adapt the tooling. The implemented harnesses are the
OpenAI Agents SDK and a scripted test harness; the implemented task is synthetic
optimization. Additional adapters currently require Python changes.

## Experiment configurations

`examples/` contains runnable configurations and prompt files. The six configs
in `examples/pilot/` define two matched repetitions of control, agents-disclosed,
and interaction-permitted conditions. See [the pilot setup](examples/pilot/README.md).
Keep future experiment configs and their prompts separate from these pilot configs,
and version them with the code used to run them.

The [swarm-hackathon-demo experiment](experiments/swarm-hackathon-demo/README.md)
defines 20 matched repetitions of control, aware, and interact (60 runs).
Its batch runner freezes configs, prompts, source, and dependency metadata for
publication provenance:

```sh
uv run --locked mad batch experiments/swarm-hackathon-demo/experiment.toml --dry-run
uv run --locked mad batch experiments/swarm-hackathon-demo/experiment.toml
```

Batch outputs live under `outputs/swarm-hackathon-demo/<timestamp>-<id>/`, with
a manifest, comparison explorer, per-run outputs, and SHA-256 fingerprints.
The experiment directory includes a Hugging Face dataset-card draft; uploading
and final release packaging happen after collection.

Every run saves its resolved config, prompts, tool definitions, runtime metadata,
events, and artifacts under `outputs/`. These outputs are excluded from Git;
preserve them separately when keeping or sharing experimental results. API keys
and local environment files are also excluded.

## Quick start

From this repository, with Docker running and `uv` installed:

```sh
uv sync --locked
uv run --locked mad build
uv run --locked mad run examples/smoke.toml
```

The smoke configuration uses scripted agents without an API key or model calls.
It exercises concurrency, experiments, artifact access, notes, submission,
evaluation, and cleanup. Its scripted behavior is not evidence of emergent
discovery or coordination.

For model-driven agents, copy `.env.example` to `.env` and set `OPENAI_API_KEY` in the
repository directory (or export it in your shell), choose a model available to
your API account in `examples/openai.toml`, then run:

```sh
uv run --locked mad run examples/openai.toml
```

Earlier runnable examples are summarized here. Run a config with
`uv run --locked mad run examples/<filename>`.

| Example | Notes |
| --- | --- |
| `openai-notes-delay.toml` | Notebook writing with 15-second measurements. |
| `openai-notes-delay-strong.toml` | GPT-5.4, 80 turns, 20-minute timeout. |
| `openai-notes-delay-staggered.toml` | Starts staggered by 30 seconds. |
| `openai-sol-notes-delay.toml` | GPT-6.1 Sol with staggered starts and 10 measurements. |
| `openai-sol-periodic.toml` | Periodic checks, timestamps, reasoning summaries, simultaneous starts. |
| `pilot/` | Two matched repetitions of control, aware, and interact. |

The model is an explicit provisional default, not a scientific recommendation.
Live rollouts incur model API charges. Keys stay on the host and are not passed
to agent containers. `mad run` automatically loads `.env` from the current
working directory; existing environment variables take precedence. `.env` is
excluded from Git. Explicit tool-schema recovery also loads it; ordinary review,
validation, and image-building commands do not.

## Configuration

The explorer reports an estimated maximum score for the synthetic task and each
agent's final-score gap to that estimate. Review export computes this reference
locally without model calls and caches it in `objective_reference.json`. It uses
the current synthetic objective v1 implementation and the saved task config.
The reference is reviewer-only and is never added to agent prompts or lab files.
The accompanying floating-point upper bound quantifies numerical uncertainty;
it is not a formal interval-arithmetic proof. Compare final scores, rather than
noisy observations, to assess room for improvement.

Configs use TOML. Validate without launching containers or calling a model:

```sh
uv run --locked mad validate examples/openai.toml
```

| Setting | Meaning |
| --- | --- |
| `agents` | Number of independent concurrent agents |
| `experiment_budget` | Maximum accepted experiments per agent |
| `max_turns` | Maximum SDK model turns; scripted mode counts tool actions |
| `timeout_seconds` | Per-agent elapsed limit after its start offset, including tool waits |
| `runs_visibility`, `notes_visibility` | Independently choose `own` or `all` |
| `note_timestamps` | Add UTC creation/update metadata and append-entry timestamps (default `false`) |
| `harness.reasoning_summary` | Optional provider reasoning summary: `auto`, `concise`, or `detailed` |
| `note_author_headers` | Add automatic author headers to lab notes (default `true`) |
| `experiment_duration_seconds` | Delay before a measurement becomes available |
| `start_offsets_seconds` | One delay per agent from the common launch point |
| `harness.kind`, `harness.model` | `openai` or `scripted`; model used by OpenAI harness |
| `tools` | Enabled tool names; must include `submit` |
| `task.dimensions`, `task.lower`, `task.upper` | Numeric parameter count and common bounds |
| `task.objective_seed`, `task.noise_seed`, `task.noise_std` | Objective generation and Gaussian observation noise |
| `task.instructions_file` | Optional extra task instructions, relative to config file |
| `task.initial_files` | Mapping of private workspace filenames to UTF-8 source files, relative to config |
| `environment.*` | Image, Python timeout, memory, CPU, and process limit |

The initial condition uses `all` for both visibility settings and neutrally
describes the lab. `own` hides peer artifacts through different mounted
directories. Explicit peer-awareness and coordination prompts are not built-in
conditions yet; custom instructions can be supplied. Related functions and
additional task families remain future work.

## Agent tools and environment

Each agent receives a fresh random UUID author ID in its prompt and `task.md`.
The same ID appears in file-tool directory listings, measurement records, and
automatic lab-note headers. It is separate from the internal Docker user ID.
Measurement filenames also use random UUIDs. The host-only `identities.json`
records the mapping for review; it is not mounted into agent containers.
Set `note_author_headers = false` to disable note headers for an experiment.


Agents receive `experiment`, `submit`, `list_files`, `read_file`, `search_files`,
`write_file`, `append_file`, `python`, and `wait`. There are no messaging, agent-list, or handoff tools.

`wait(seconds)` pauses only the calling agent for up to 60 seconds. It uses no
experiment budget, but counts toward the session timeout. Requested and actual
wait durations are recorded; timeout interruptions are recorded as cancelled calls.

- `/workspace` is private and writable. It contains `task.md` and optional initial files.
- `/lab/runs` automatically receives immutable measurement records.
- `/lab/notes` contains voluntary notes with flat filenames. The file tool permits
  creating notes and editing only notes created by the caller.

Both lab directories are read-only to container Python, including the caller's
own published notes. Use `write_file` to publish or replace a note, or `append_file` to add text.
`append_file` creates missing files and adds text exactly, without extra newlines;
notes and appended files are limited to 65,536 characters. Python may write
and analyze private workspace files; each Python call starts a fresh interpreter
with NumPy, SciPy, and pandas. This first version deliberately uses trusted
publication instead of relying on owner-changeable Unix file modes.

Invalid experiments use no budget. Accepted calls use one experiment even if
interrupted while waiting. Exhausting the budget leaves analysis and submission
available. Successful submission ends the run with no measurement response.
If a limit is reached without submission, the final configuration and true score
are null. A model that ends with a text answer instead of `submit` also exits
without a submission.

## Outputs

Each run creates a fresh `outputs/<timestamp>-<id>/` directory, or a new directory
specified with `--output`. Existing directories are never overwritten.

- `config.json`: resolved configuration.
- `runtime.json`: host Python/platform, SDK version, and Docker image ID.
- `events.jsonl`: ordered, timestamped model requests/responses, tool calls/results,
  experiment lifecycle, submissions, and termination events.
- `summary.json`: per-agent final choice and true score, best completed observation,
  experiments used/completed, exact within-agent duplicate count, file-tool accesses,
  and termination reason; also contains all accepted experiment records.
- `artifacts.tar`: final private workspaces and lab artifacts, preserving ownership.
- `note_ownership.json`: publication ownership registry.

Model responses and usage available through the SDK are recorded locally; SDK
trace export is disabled. Failed or interrupted runs preserve available events
and, after successful setup, attempt a final artifact snapshot. Containers and
volumes are removed after snapshotting. A hard process kill can leave resources
behind; MAD-managed resources have the `mad.managed=true` label.

File-tool reads/searches/writes are logged explicitly. Direct Python file reads
and writes are not individually traced, and final snapshots are not a complete
history of such writes. No automated collaboration classifier is implemented.

## Explore a run

Export a self-contained HTML explorer from a saved run directory:

```sh
uv run --locked mad review outputs/<run-directory>
```

Open the generated `review.html` locally. Use `--output path/to/review.html` to
choose a different location. The viewer embeds the run data and needs no server,
API key, external resources, or model calls. Re-export to refresh an in-progress
run snapshot.

The viewer includes outcomes, best-observed trajectories, searchable per-agent
events with model/tool inputs and outputs, system prompts, available tools and
their schemas, context growth, measurement and submission tables, final artifact previews, and
possible-coordination indicators with links to evidence.

Context growth shows model-reported input tokens per call over elapsed time,
first/latest/peak input sizes, output and cached-input counts, and cumulative
input usage. Cumulative input is repeated token processing across calls, not the
context size of a single call. No model context limit is assumed.

OpenAI rollouts record available tool definitions in an
`agent_interface` event. Runs without that event retain their recorded system prompts but
show explicitly labeled tool definitions from the current MAD version unless
their original definitions have been recovered. Where stored OpenAI responses
remain available, retrieve their initial tool definitions with:

```sh
uv run --locked mad review outputs/<run-directory> --recover-tools
```

This explicit recovery uses the API key to read existing responses, makes no
new model-generation calls, and saves `interfaces_recovered.json` with source
response IDs and retrieval timestamps. It does not rewrite the original events.
Subsequent ordinary review is offline. Artifact previews do not extract files
or follow archive symlinks.

Candidate indicators cover successful peer-artifact reads, notes mentioning a
peer filename, and submissions matching configurations measured only by peers.
They do not establish intent, causality, or a collaboration score. No flags does
not mean no discovery, particularly through untraced Python filesystem access.

## Verification

```sh
uv run --locked pytest -m 'not docker'
MAD_DOCKER_TESTS=1 uv run --locked pytest -m docker
uv run --locked ruff check src tests
```

Docker tests require the sandbox image to have been built. They exercise both
visibility settings, ownership enforcement, direct-Python restrictions, process
and network isolation, timeouts, and complete scripted rollouts. The SDK loop
test uses a fake model, avoiding network calls and charges.

Documentation describes current interfaces, defaults, and operational limits.
Record change history in commits and pull requests.
