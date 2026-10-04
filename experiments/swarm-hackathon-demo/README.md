# swarm-hackathon-demo

Twenty matched repetitions of control, aware, and interact: 60 rollouts,
240 agent sessions, and at most 2,400 accepted measurements. This follows the
four-agent pilot configuration; the pilot configs and outputs remain separate.

## Design fixed before launch

Each rollout uses four GPT-6.1 Sol agents, 10 experiments per agent, 80 model
turns, a 1,800-second timeout per agent, 15-second measurement delays, and
simultaneous starts. Both lab directories are visible to all agents. Note author
headers, timestamps, and provider reasoning summaries (`auto`) are enabled.
The synthetic task has eight dimensions, bounds [0, 1], and noise SD 0.1.
The Docker resource defaults and enabled tools are resolved into each config.json.

The prompts are copied verbatim from the pilot:

- **control:** notebook writing and periodic lab checks.
- **aware:** control plus “Other agents are actively working on this task.”
- **interact:** control plus “Other agents are actively working on this task.
  You can interact with them as you see fit.”

Repetition r (1–20) uses objective seed 43+r and noise seed 124+r, i.e.
44–63 and 125–144. These do not reuse the pilot pairs (42,123) and (43,124).
All non-prompt settings match across conditions within each repetition.
Noise streams match by internal agent index; random author UUIDs, stochastic
model outputs, and scheduling are not matched. There is no fixed provider
sampling seed or guaranteed model-version pinning.

All three conditions in a repetition launch concurrently in isolated Docker
storage (12 agents total). Repetitions run sequentially in ascending order.
API/infrastructure errors stop subsequent repetitions after the current trio
finishes. Time/turn limits and absent submissions are outcomes, not reasons to
rerun. No automatic retries of whole rollouts or resume behavior are implemented;
a new invocation creates a separate batch. Preserve failed batches and disclose
any follow-up runs rather than silently replacing failures.

## Run

From the repository root:

```sh
uv run mad batch experiments/swarm-hackathon-demo/experiment.toml --dry-run
uv run mad batch experiments/swarm-hackathon-demo/experiment.toml
```

Docker must be running with the `mad-python:local` image built (`uv run mad build`).
The batch command loads the root .env without overriding shell variables.
The dry run makes no model calls and does not load credentials.
A complete batch has up to ten hours of per-agent timeout windows plus overhead;
actual runtime depends on agent behavior. Model API charges apply.

## Storage and provenance

Definitions and prompts under experiments/ belong in Git. All of outputs/ is
ignored; back up completed and failed batches separately.

Default destination: outputs/swarm-hackathon-demo/<UTC-timestamp>-<random-id>/.
Use --output for a new custom batch directory; existing paths are never overwritten.

- manifest.json: all 60 planned entries, condition/repetition, seeds, statuses,
  start/end UTC timestamps, results, commit, dirty-tree indicator, installed
  package versions, matching rules, and snapshot references.
- inputs/experiment/: frozen experiment configs, prompts, protocol, and card.
  Rollouts execute these saved configs, not mutable originals.
- inputs/code/: working source, Docker build definition, runner scripts, dependency
  lockfile, project metadata, code license, and core documentation.
- inputs/checksums.json: SHA-256 input fingerprints; these cover dirty/uncommitted
  changes as well as committed source.
- <condition>-<repetition>/: standard MAD outputs plus run_metadata.json,
  review.html, and checksums.json.
- index.html: live batch overview; final checksums.json covers batch files.
- README.md: publication draft copied from DATASET_CARD.md.
- LICENSE: code/viewer license, not an assigned license for generated research data.

Runtime records identify the actual Docker image ID. Prompt/tool events, API
response metadata and available token usage remain in events.jsonl. Model
provider sampling and alias changes limit exact reproducibility. Credentials
and .env files are excluded from snapshots; generated logs should still be
reviewed before publication.

## Analysis and Hugging Face release

Compare conditions within matched repetitions; agents share a lab, so 240 agent
sessions are not 240 independent repetitions. Report submission/termination rates
alongside scores. Missing final scores remain null; do not replace them with zero
or quietly drop failed sessions. Means in the HTML overview describe submitted
agents only. Estimated objective maxima are reviewer-only numerical references.
Peer-read flags are navigation aids, not validated labels for collaboration;
Python filesystem reads are not individually traced.

Capture provenance now; build the Hugging Face packaging/upload utility after
collection. It should produce machine-readable run/agent tables linked to raw
traces and artifacts, preserve null outcomes and failures, verify checksums,
review/redact local paths or sensitive generated content in a separate release
copy, and update the dataset card with actual counts, dates, limitations,
analysis schema, citation, authors, and the chosen dataset license. Record any
redactions with release-specific checksums. Do not upload credentials.

The generated research data license must be selected before publication; it is
not automatically the MAD code license. Included source and HTML viewers retain
the Silicoase Noncommercial License and notices. No upload occurs in this runner.
