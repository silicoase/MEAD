---
pretty_name: swarm-hackathon-demo
language:
- en
tags:
- synthetic
- multi-agent
- agent-discovery
- optimization
---

# swarm-hackathon-demo

**Publication draft:** fill collection dates, actual run/session/measurement
counts, authors/contact, citation, release version, and generated-data license
before uploading. The included LICENSE covers MAD code and viewers; select the
research-data license separately and add it to the YAML header.

## Collection

Hackathon demo: planned 20 matched repetitions of control, aware, and interact,
with four GPT-6.1 Sol agents per run (60 runs / 240 sessions).
Each agent has 10 measurements, 80 turns, a 30-minute timeout, shared lab
artifacts, and 15-second measurement delays. Conditions differ in peer-awareness
and interaction-permission wording. Objective seeds are 44–63; noise seeds
are 125–144. Exact prompts and settings are preserved in inputs/experiment/.

## Files and metadata

manifest.json links conditions, repetitions, seeds, timestamps and statuses to
run folders. Each folder contains resolved config.json, runtime.json,
identities.json, ordered events.jsonl, summary.json, artifacts.tar,
run_metadata.json, checksums.json, and review.html when export succeeds.
The batch includes source/config/prompt snapshots, dependency versions and
lockfile, Git commit/dirty status, and SHA-256 fingerprints. Runtime records
identify the Docker image. Events preserve available model/tool outputs,
response IDs, token usage, and provider reasoning summaries.
Model request events include SDK settings; null values leave defaults unspecified.
Provider metadata events preserve the returned model identifier, settings and
request ID when available, linked by response ID. Identifiers may still be aliases.
Document any release tables and their schemas here when packaging the data.

## Data limitations

Author UUIDs identify synthetic agents. Model randomness, alias changes, UUIDs,
and scheduling prevent exact replay. Provider summaries are not complete hidden
reasoning; Python file accesses are not individually traced. Final scores may
be null when no submission occurs. File-tool flags are heuristic navigation aids.
Report actual incomplete/error records and any transformations in the release.
