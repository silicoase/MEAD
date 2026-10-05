---
pretty_name: swarm-hackathon-demo
license: cc-by-4.0
language:
- en
tags:
- synthetic
- multi-agent
- agent-discovery
- optimization
---

# swarm-hackathon-demo

**Release draft template — v1.0.0 is publicly released.** The final
read-only audit confirms all 60 runs finished, all 240 agents submitted, and
all 2,400 accepted measurements completed and published to lab records. See
[RELEASE_AUDIT.md](RELEASE_AUDIT.md) for evidence and remaining release checks. See
[PUBLICATION_PLAN.md](PUBLICATION_PLAN.md) for proposed packaging and decisions.
Copy this finalized card to the release's root `README.md`; preserve the original
launch-time card inside the raw batch snapshot.

## Release information to complete

| Field | Value |
| --- | --- |
| Hugging Face repository / visibility | [connacher-silicoase/swarm-hackathon-demo](https://huggingface.co/datasets/connacher-silicoase/swarm-hackathon-demo), publicly released 2026-10-04 as v1.0.0 |
| Release version / immutable revision | v1.0.0 / `3b44372a47184e074b79f226e2a4938f454e2f38` |
| Creators / affiliations | Connacher Murphy — Silicoase |
| Public contact | connacher@silicoase.com |
| Generated-data license | **AGREED:** CC BY 4.0 for generated research data; MAD and third-party material retain their own terms |
| Collection interval (UTC) / batch IDs | 2026-10-04 21:15:02.946689–23:24:38.526392 UTC; manifest batch ID `20261004T211502Z-442d48aa` |
| Planned runs / agent slots / measurement maximum | 60 / 240 / 2,400 accepted measurements |
| Actual runs by status / agent sessions with reports | 60 finished runs; 240 agent reports; no pending/running/error/cancelled runs |
| Submissions / accepted measurements / completed measurements | 240 confirmed submissions / 2,400 accepted / 2,400 completion timestamps / 2,400 confirmed lab publications |
| Complete matched repetitions / collection incidents | 20 complete matched repetitions; no submission inconsistencies, missing expected run files, or checksum mismatches found in final audit |
| Release layout / exclusions / redactions | **AGREED:** raw batch first, optional analysis tables later; exclusions/redactions pending review |
| Citation / results writeup | Connacher Murphy; [MAD GitHub repository](https://github.com/silicoase/measuring-agent-discovery); versioned citation and writeup pending |

## Dataset purpose

This synthetic optimization experiment supports examination of how prompt
wording about peer awareness and interaction affects independent agents working
in shared labs. It is a hackathon demo, not a general benchmark of scientific
discovery, multi-agent systems, or models. Suggested uses include inspecting
trajectories, measurements, artifacts, and matched condition comparisons.
There are no predefined training, validation, or test splits.

## Collection design

The definition plans 20 repetitions of `control`, `aware`, and `interact`, with
four agents per run. The configured model is `gpt-6.1-sol`, with provider reasoning
summaries requested as `auto`. Each agent has at most 10 accepted measurements,
80 SDK turns, and a 1,800-second session timeout. Measurements incur a 15-second
delay; agents start simultaneously. The objective has eight parameters bounded
by [0,1], with Gaussian observation noise SD 0.1. Submission is separate from
measurement and is evaluated on the noiseless objective.

All conditions have the same shared lab record/note access and tools, including
Python. Control asks for notebook writing and periodic lab checks; aware adds
explicit peer awareness; interact additionally permits interaction. There are
no direct messaging or cross-agent handoff tools: interaction can occur through
shared artifacts. These conditions do not isolate the effect of granting access
to peers' files. Exact prompts and settings are preserved in the frozen
`inputs/experiment/` tree of each batch.

Repetition r uses objective seed 43+r and noise seed 124+r (44–63 / 125–144).
Noise streams are matched by internal agent index; adaptive measurement choices
mean this does not imply identical observations. Conditions run concurrently
in isolated labs; repetitions run sequentially. UUIDs, model outputs, and timing
are not matched. API/infrastructure errors stop later repetitions; the runner
does not automatically retry whole runs. This released batch completed all
planned runs; actual dates and counts are recorded above. Provider-returned
model identifiers and settings remain available in the raw event records.

## Release organization and schemas

**Agreed initial layout:** raw batch under `raw/<batch_id>/`, plus the finalized
card, license scope/notices, raw schema documentation and release provenance.
Parquet analysis tables are deferred. Download raw files to inspect them; the
initial release does not promise a tabular Dataset Viewer. Later revisions may
add the tables proposed below without replacing raw data. Each release should
have an immutable revision/tag; cite the revision actually analyzed. Full
proposed table fields/types are in PUBLICATION_PLAN.md.

| Proposed table | Unit / unique key | Meaning |
| --- | --- | --- |
| runs | Planned run / `(batch_id, run_id)` | Condition, repetition, matched seeds, lifecycle status, counts, file availability, errors |
| agents | Planned agent slot / `(batch_id, run_id, agent)` | Synthetic author UUID, report availability, termination reason, final parameters/true score, measurement counts, usage |
| measurements | Accepted measurement / `(batch_id, run_id, measurement_id)` | Eight parameters, noisy observation, author, timestamps, completion-event/publication evidence, raw source locator |

Raw measurement `run_id` is a measurement UUID and is renamed `measurement_id`
only in the derived table. It must not be confused with the batch condition/run
folder ID. Missing reports and values remain null, not zero. Tables would use
explicit Hub configurations with one `all` split each; add YAML `configs` only
after the table files exist and have been validated. Raw heterogeneous JSON
payloads are retained rather than flattened into one inferred dataset schema.

### Raw files (availability depends on run progress and export success)

| File | Structure / provenance |
| --- | --- |
| `manifest.json` | Batch object: experiment definition schema version 2, batch ID/status/timestamps, matching text, provenance, and planned `runs` entries with condition/repetition/seeds/status and optional outcomes/errors |
| `inputs/` | Frozen experiment configs/prompts/docs, MAD source and viewers, Docker/scripts, dependency lockfile, code license; SHA-256 map |
| `<run_id>/config.json` | Fully resolved rollout/task/harness/environment settings; may contain host paths |
| `<run_id>/runtime.json` | Python/platform, Agents SDK version, Docker image ID |
| `<run_id>/identities.json` | List of `{agent, author_id, docker_uid}`; synthetic UUIDs, not human identifiers |
| `<run_id>/events.jsonl` | Ordered event objects: `sequence`, UTC `timestamp`, `elapsed_seconds`, `kind`, nullable `agent`, and kind-specific payload |
| `<run_id>/summary.json` | Object with `harness`, agent reports, per-agent lists `experiment_records`, and submission mapping; may be missing on early startup failure |
| `<run_id>/run_metadata.json` | Schema version 1: experiment/batch/run identity, status, seeds, timing and optional errors; later viewer errors may only appear in manifest |
| `<run_id>/artifacts.tar` | Final lab state and agent workspaces; may contain agent-created files and symlinks |
| `<run_id>/note_ownership.json` | Lab note path to internal agent-index mapping |
| `checksums.json` | Relative file path to SHA-256 digest; runner maps exclude all files named `checksums.json` |
| `index.html`, `<run_id>/review.html` | Batch comparison and run viewers; run viewer depends on export success and carries MAD software/branding terms |

Events cover rollout/agent lifecycle, interfaces, model requests/responses,
provider metadata, tool calls/results/cancellations, accepted/completed
experiments, and submissions. Requests include system prompts, inputs and SDK
settings; null SDK values leave defaults unspecified. Responses preserve
available outputs, usage, response IDs and provider reasoning summaries.
Provider metadata records returned model/settings/request ID when available,
linked by response ID; identifiers may still be aliases. Raw events do not have
a separately declared event-schema version. Exact payloads depend on the frozen
source and SDK versions, which must be consulted when parsing.

## Incomplete runs and missingness

**Agreed upload rule:** release only a batch with all 60 planned run statuses
`finished`; partial batches remain local. Separately audit all 240 agent slots
for submission, reconciling termination reasons, final parameters/scores, summary
submission mappings and recorded submission events. Report every exception
before upload; run completion alone does not establish agent submission. Early submission
without spending all measurement budget is allowed. Preserve all records within
the selected batch; disclose reruns and selection criteria if applicable. Report
run status and agent termination separately. Run `finished` does not imply that
all four agents submitted: time/turn limits and final answers without submission
can still yield that status. `pending` in a stopped batch can mean never launched;
an interrupted process can leave stale `running` records. Missing data is not
evidence of a zero score or zero usage.

An accepted measurement consumes budget before its delay and can be interrupted.
`completed_at` is assigned before lab publication, while `experiment_completed`
is recorded after publication succeeds. Report accepted counts, timestamp-based
completion counts, and publication evidence distinctly when they differ. Final
`true_objective` is null without a submission; `best_observed` uses completed
noisy observations and is not the final true score. HTML score summaries exclude
agents without submissions. Comparisons must show submission attrition, respect
shared-lab dependencies, and disclose excluded repetitions rather than silently
selecting successful records. In the audited batch, all 240 agents submitted
and all 2,400 measurements completed with publication events. No missing expected
run files were found. Preserve the manifest batch ID separately from the raw
folder name `20261004T211502Z-03c650a5`, whose suffix differs.

## Limitations and responsible interpretation

The dataset concerns one configured model, one synthetic objective family, and
three prompt conditions in a small planned demo. It cannot establish broad
claims about real-world scientific discovery or causal communication mechanisms.
Agents in one lab share information and are dependent. Model randomness, model
alias changes, UUIDs, API behavior and concurrent scheduling prevent exact replay
even with matched seeds and frozen inputs. An image ID identifies the local
Docker image but does not by itself distribute that image.

Provider summaries are not complete hidden reasoning. Python file accesses are
not individually traced; file-tool flags in viewers are heuristic navigation
aids, not a complete measure of interaction. Notes/artifacts and model outputs
may contain incorrect claims or executable code; they are research records,
not verified instructions. Repeated noisy evaluations and selected maxima can
inflate observed-best statistics. Report collection interruptions and every
release transformation. **PENDING:** additional collection or access limitations.

## Licensing, privacy, and release transformations

Generated experiment data: **Creative Commons Attribution 4.0 International
(CC BY 4.0)**, selected by the user on 2026-10-04. See
[DATA_LICENSE.md](DATA_LICENSE.md) for scope and attribution. The existing MAD
license does not automatically license generated outputs. The release inventory
must identify copied third-party material and retain applicable notices. MAD source, copied documentation/prompts and embedded HTML viewer code
retain the Silicoase Noncommercial License, Version 2.0 and its Required Notice;
brand assets retain its branding restrictions. See release `NOTICE.md` and
`LICENSES/MAD-LICENSE.txt` once packaged. Do not apply the generated-data license
to those portions merely by putting one license in the YAML header.

Input snapshots exclude credentials by an explicit source allowlist, but this
does not certify that every error, free-text output, config path or archived
artifact is suitable for publication. The initial scan found local host-path
patterns in 244 files; credential-like matches were confined to opaque provider
encrypted-content fields, and email matches were classified as Python code.
See RELEASE_AUDIT.md for scope and limits. **PENDING:** final release review,
provider-ID policy, host-path treatment, exclusions and redactions. Preserve original evidence privately if
sanitization is necessary; publish a transformation log and new checksums for
changed bytes. Do not rewrite frozen provenance or imply that source checksums
authenticate a modified release.

## Citation and contact

Author: Connacher Murphy. Affiliation: Silicoase. Public contact:
[connacher@silicoase.com](mailto:connacher@silicoase.com).
Software and experiment source: [MAD GitHub repository](https://github.com/silicoase/measuring-agent-discovery).

**OPEN:** formal citation, release version and immutable Hugging Face revision, and final results-writeup link. No paper, DOI, or publication
date is asserted by this draft.

Hub packaging references: [dataset cards](https://huggingface.co/docs/hub/datasets-cards),
[explicit data configurations](https://huggingface.co/docs/hub/datasets-manual-configuration),
and [license metadata](https://huggingface.co/docs/hub/repositories-licenses).
