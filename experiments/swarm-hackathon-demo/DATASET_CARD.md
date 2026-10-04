---
pretty_name: swarm-hackathon-demo
language:
- en
tags:
- synthetic
- multi-agent
- agent-discovery
- coordination
- optimization
---

# Dataset Card for swarm-hackathon-demo

**Publication draft.** Update this card from the completed manifest before
uploading. Generated-data licensing, authors, citation, and Hugging Face repository
identity are pending. The included LICENSE applies to MAD source/viewer code;
it does not assign a license to the generated research data. Add the chosen data
license to the YAML metadata before publication.

## Dataset description and collection

This experiment studies peer discovery and voluntary coordination through shared
artifacts during synthetic optimization. Planned collection: 20 matched
repetitions × three prompt conditions × four agents = 60 rollouts / 240 sessions,
with at most 2,400 accepted measurements. These are planned, not observed counts.
Actual statuses, dates, counts and outcomes must be derived from manifest.json.

Model: OpenAI GPT-6.1 Sol (`gpt-6.1-sol` alias); OpenAI Agents SDK.
Conditions: control (notebook + periodic lab checks), aware (explicit peer
awareness), interact (peer awareness + permission to interact).
Each trio shares objective/noise seeds: objective 44–63, noise 125–144.
The task has eight dimensions, [0,1] bounds, Gaussian noise SD 0.1,
10 measurements per agent, 15-second delays, simultaneous starts, 80 model turns,
and 30-minute per-agent timeouts. Both lab directories are shared.
Provider reasoning summaries use auto; these are provider-supplied summaries,
not complete hidden reasoning. No human collaboration labels are collected.

## Data structure and provenance

Each batch contains a manifest, frozen inputs and source with SHA-256 hashes,
per-run resolved configuration and runtime metadata, ordered events.jsonl,
summary.json, identity/ownership mappings, final artifacts.tar, and HTML reviews.
run_metadata.json links raw runs to condition, repetition, seed pair and batch.
Source provenance includes Git commit, dirty status, the actual working-source
snapshot, uv.lock and installed package versions. Runtime includes Docker image
identity. Opaque random UUID author IDs identify synthetic agents, not people.
The final release should specify flattened table schemas and links to raw files.

## Intended use and limitations

Use for exploratory research on artifact-mediated agent discovery, optimization,
and coordination. Interpret scores within matched repetitions; four agents in a
shared lab are dependent observations. Model alias changes, model randomness,
random UUIDs, and execution timing prevent exact replay. Repetitions run in fixed
order, and concurrent conditions can contend for host/provider resources.
Direct Python filesystem accesses are not individually traced. Peer-read flags
are heuristic navigation aids, not collaboration ground truth.

Preserve errors, timeouts, turn limits, absent submissions and null scores.
Report final scores and submission rates together. Automated whole-run retries
are disabled; disclose separately collected follow-up runs. Review the actual
failure/missingness distribution before drawing comparative conclusions.

## Publication checklist

Fill actual collection dates, completed/failed/missing counts, release version,
authors/contact, code repository/commit, citation, generated-data license,
review/redaction decisions, file schemas, and release checksums. Review generated
text and local host paths before publication. Preserve original raw files locally
and record release transformations. Retain source/viewer notices and LICENSE.

Collection protocol: inputs/experiment/README.md.
