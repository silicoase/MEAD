# Implementation

This document describes MAD’s components, execution behavior, and operational limits.

## Boundaries

- `config.py` validates TOML, rejects unknown fields, and resolves input paths.
- `rollout.py` launches independent concurrent harnesses and records termination.
- `harness.py` supplies an OpenAI Agents SDK adapter and a scripted plumbing test.
- `environment.py` manages Docker execution and trusted artifact publication.
- `tools.py` dispatches and logs tools, serializing calls within each agent.
- `task.py` owns synthetic optimization, budgets, noise, submission, and evaluation.
- `recording.py` writes host-only JSON events and output files.

The harness and task protocols establish replacement boundaries. Configuration
currently accepts only the implemented adapters; this is not a plugin registry.

## Author identities

Each Docker environment assigns fresh UUID4 author IDs independently of task and
noise seeds. Agents see only their own identity in the system prompt and private
`task.md`. File-tool directory listings and measurement records expose opaque
author IDs; measurement filenames use independent UUIDs. Docker UIDs remain
internal filesystem ownership identifiers. Raw Python can still inspect Unix
ownership, so opaque author IDs do not hide every filesystem provenance cue.
The host saves index/author/Docker UID mappings in `identities.json`.

Lab-note author headers default on and can be disabled with
`note_author_headers = false`. The publisher preserves one canonical header on
replacement and append operations. Header text counts toward the note size
limit. Private workspace files do not receive headers. The ownership registry
uses internal agent indices for artifact access attribution.

## Docker and publication

Use Docker-managed storage so file ownership is enforced by Linux even on macOS.
A trusted, host-controlled storage container mounts the rollout volume. Agent
containers mount only their own workspace and permitted lab directories. Agent
containers use distinct non-root UIDs, separate process namespaces, no network,
a read-only image filesystem, dropped capabilities, and resource limits.

Lab mounts are read-only. Host-side file tools publish notes with a creator
registry and enforce ownership; Python cannot directly edit any published lab
artifact. Read-only mounts prevent file-mode changes granting peer write access and
prevent deletion/rename bypasses. Lab
publication replaces whole files atomically; visibility is live, not a snapshot
at agent initialization. Simultaneous attempts to claim the same note filename
are serialized: the first successful writer owns it.

This is experimental isolation, not a claim of complete resistance to container
escapes or all hardware/timing side channels. The kernel is shared. Verification
covers intended process, filesystem, and network boundaries. Credentials,
objective code, and controller logs are never mounted into agent containers.

## Task and lifecycle

The synthetic objective is a seeded sum of quadratic and periodic terms with
interactions among the first three variables, weak later variables, and one
irrelevant final variable (for the default eight-dimensional task). All parameters
are numeric with common configurable bounds. Function-family plugins, integer
or categorical parameters, and related variants are not implemented yet.

Observation noise is Gaussian. Each agent has a separate seeded random stream,
derived from the noise seed and agent index. Accepted call order within that
agent determines its noise sequence; cross-agent scheduling does not. Function
and noise generation are reproducible within the recorded runtime, not a promise
of deterministic model behavior or concurrency.

Invalid parameters do not consume budget. Valid accepted calls consume budget
before experiment latency, including calls later interrupted by a time limit.
Interrupted records remain in host logs/summary and need not appear in the lab.
Experiment latency counts against elapsed limits; start offsets do not. Containers
are prepared before the common launch point. Delays need not match model turns.

Final noise-free evaluation happens outside the agent environment. No submission
means no inferred configuration and no final true score. SDK final text without
the submission tool is recorded as `final_answer_without_submission`; accepted
submission terminates the SDK loop. SDK model turns and scripted tool actions
are different units and should not be compared as experimental measurements.

## Recording and operational limits

The event sequence reflects controller observation order. Events record UTC
timestamps and monotonic elapsed time; they are not a distributed logical clock.
SDK hooks retain completed model requests/responses and per-response usage,
including completed calls before turn/time limits. In-flight incomplete model
responses are not streamed or preserved. Hidden model reasoning is not available.

The explorer derives per-call context growth from reported input-token usage and
matches response usage with request-start times where available. Cached tokens
remain part of the input count. Cumulative input is displayed separately as
token processing, not context occupancy. The chart makes no assumptions about a
model's maximum context size.

OpenAI runs record initial tool definitions directly. Explicit recovery can enrich
runs without recorded definitions from stored OpenAI response metadata, preserving response IDs and
retrieval timestamps in a separate file without altering original events. Recovery
requires the responses still to exist and credentials for the same API project.
The initial recovered interface does not claim to capture later dynamic changes.

Explorer styling uses charcoal `#18181b` and pale blue `#b3e2f4` from the Silicoase
website's `app/globals.css`. Agent series share a color and use different line
styles. Most text uses one size, with modest heading and code-size differences.

Python execution is stateless between calls except for workspace files. Output
is truncated to 64 KiB, file tools have read/search limits, and individual files
written by container processes have a 16 MiB size limit. Memory, CPU, process,
and execution-time limits are configured. There is no total artifact-storage
quota yet. Detached processes are stopped when the agent exits. General-purpose
shell processes could still be launched by Python inside the same isolation
boundary despite the absence of a shell tool.

The artifact archive is saved without automatically extracting agent-created
symlinks. Hosts need Docker and `uv`; no VM provisioning or cloud deployment is
implemented. The host dependency lockfile pins the tested SDK environment. The
Docker image ID is recorded because rebuilding its base image or libraries may
change the runtime.

## Remaining work

- Inspect additional live rollouts and validate the review workflow.
- Extend the offline HTML viewer with artifact history where recorded, richer
  comparisons, and indicators of potential division of work. Initial flags
  cover peer-artifact reads, filename references, and matching submissions;
  they link to evidence and do not assert collaboration or intent.
- Decide whether finer-grained Python filesystem tracing is necessary.
- Add cross-agent/near-duplicate analysis and explicit artifact-access attribution.
- Add storage quotas and recovery/cleanup for hard-killed controllers.
- Validate task difficulty and experimental timing before making scientific claims.
- Extend model settings, task adapters, and harness adapters as experiments need them.

Optional `note_timestamps` adds UTC `Created` and `Updated` metadata and timestamps
each append entry. Replacement preserves creation time. Metadata counts toward
the note size limit. `harness.reasoning_summary` requests provider summaries;
returned reasoning items are logged verbatim and their summary text appears in
model-turn details. Summaries may be absent and are not raw reasoning traces.
