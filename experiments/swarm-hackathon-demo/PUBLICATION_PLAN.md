# Hugging Face publication plan and release record

Current status: publicly released as `v1.0.0` at commit
`3b44372a47184e074b79f226e2a4938f454e2f38`. See PUBLIC_RELEASE_VERIFICATION.json.
The earlier planning decisions and audit/staging milestones below are retained
as a chronological record.

Prepared 2026-10-04 from the experiment definition and current runner source.
This is a planning document, not a collection report. The originating chat owns
experiment launch, monitoring, collection, and the results writeup with figures.
The private Hugging Face dataset repository was created with user authorization
on 2026-10-04. No experiment data was uploaded, no local token authentication
was configured, and no experiment was executed here. Configurations and prompts must remain unchanged.

## Decisions to settle

| Decision | Recommendation / proposed default | Status |
| --- | --- | --- |
| Repository | [connacher-silicoase/swarm-hackathon-demo](https://huggingface.co/datasets/connacher-silicoase/MEAD) | **CREATED:** private dataset repository, 2026-10-04 |
| Visibility | Stage privately, inspect, then make public | **AGREED** |
| Authentication | Local HF login or environment-managed token with write access to the selected dataset; confirm account and organization permissions without exposing token values | **VERIFIED:** browser and CLI signed in as connacher-silicoase; user supplied successful `hf auth whoami` output; repository write permission not yet checked |
| Generated-data license | CC BY 4.0 for generated research data, with component exclusions | **AGREED:** user accepted the recommended CC BY 4.0 option on 2026-10-04 |
| Authors / affiliations | Connacher Murphy — Silicoase | **AGREED** |
| Contact | connacher@silicoase.com | **AGREED:** public email |
| Citation | Connacher Murphy; link https://github.com/silicoase/MEAD | **AGREED:** author and GitHub link; version/revision and formal citation still open |
| Release layout | Raw batch first; optional Parquet tables in a later revision | **AGREED:** initial raw-only release; trace/artifact exclusions still to review |
| Completion / submission audit | Fully complete means all 60 runs finished; separately check every agent submitted | **AGREED:** mandatory audit of all 240 agent slots; disclose exceptions before upload |
| Limitations | Card lists known implementation limits; add collection incidents and access restrictions after collection | **OPEN:** additional disclosures |

Only rows marked AGREED are accepted decisions. The user created the account using
connacher@silicoase.com and reported successful login. The visible signed-in
username is `connacher-silicoase`. Browser login is complete; the user approved the repository name and creation.
The private repository exists. On 2026-10-04 the user supplied successful
`hf auth whoami` output identifying `connacher-silicoase`; CLI authentication is
complete. Token type, repository scope and write access have not been verified. Resolve
remaining open items in this file and the card before release. Local authentication can be established with `hf auth login`,
then checked with `hf auth whoami`, if the CLI is available; never put a token in
chat, tracked files, release metadata, logs, or command arguments. Prefer a token
scoped to the destination repository where feasible; repository creation may
require separate account permissions. No credential files need inspection here.

## Initial release tree (raw-only; agreed)

```text
README.md                       # finalized DATASET_CARD.md, not experiment README
LICENSE                         # CC BY 4.0 terms, scoped by DATA_LICENSE.md / NOTICE.md
LICENSES/MAD-LICENSE.txt         # exact existing MAD terms and Required Notice
NOTICE.md                       # path-level data/code/third-party license scope
DATA_LICENSE.md                 # generated-data scope and attribution
SCHEMA.md                       # raw formats and missingness; derived tables deferred
RELEASE.json                    # release version, batch IDs, transform provenance
checksums.json                  # SHA-256 for final release files, excluding itself
raw/<batch_id>/                  # preserved batch structure and existing checksums
  manifest.json
  inputs/                       # frozen source/config/prompt snapshots
  <condition>-<NNN>/             # only directories actually produced
  ...                           # LICENSE, README, index and available run files
```

The raw batch's original `LICENSE` remains the MAD license. Root `LICENSE` would
apply only to separately licensed generated data; `NOTICE.md` must explicitly
exclude copied MAD source, prompts/documentation, embedded viewer code and brand
assets from that blanket grant. Retain all existing notices and separately
licensed third-party material. The existing LICENSE's Outputs section supports
this separation, but does not itself select a data license or establish the
publisher's rights in every generated or copied component.

Keep the launch-time README and snapshots inside `raw/`; publish the revised
card at root. Do not rewrite frozen inputs or collected raw records to match the
new card. If removal of private information is necessary, preserve the original
privately and produce a documented sanitized derivative with its own checksums,
redaction log (no secret values), and source-to-release file mapping. Original
checksums describe original bytes, not redacted bytes.

For the initial release, omit Parquet files and table configurations; document
the raw download workflow. Add analysis tables later in a new tagged revision,
keeping raw data unchanged and retaining the initial immutable revision.
A raw-only repository need not have a tabular Dataset Viewer. In a later release,
use explicit Hugging Face `configs` pointing only to each finalized table, so
heterogeneous manifest/event/config JSON files are not inferred as one dataset.
Use one descriptive `all` split per table; there is no train/test assignment.
Keep `condition` as a column, not separate training splits. Do not enable table
configs until files exist and load correctly. HTML reports are downloadable
viewers; verify how users can open them locally without promising Hub hosting.

## Optional later analysis schemas (release deferred; exporter implemented)

`scripts/export_batch_parquet.py` now implements the three tables. See
[PARQUET_EXPORT.md](PARQUET_EXPORT.md) for usage, checks and limitations. It adds
`confirmed_submissions` to runs and `submission_confirmed` to agents, and writes
`SCHEMA.json`, provenance and checksums. Typed tables passed eight focused tests
and a local preview round trip. Table publication remains deferred; raw-only
release preference is unchanged.

All table keys include `batch_id`; `run_id` means the condition/repetition run,
whereas raw measurement records use `run_id` for a measurement UUID. Rename that
raw field to `measurement_id` in the derived table, without changing raw bytes.
Integer agent indices are 0–3 and UUIDs identify synthetic agents, not people.
Timestamps are nullable UTC ISO 8601 strings. Scores and parameter values are
float64; vectors are lists of eight float64 values. Unknowns are null, not zero.
All tables carry `release_schema_version=1` (proposed; distinct from runner versions).

| Table / key | Columns and types beyond the key | Source / semantics |
| --- | --- | --- |
| runs: `(batch_id, run_id)` | `condition:string`, `repetition:int64`, `objective_seed:int64`, `noise_seed:int64`, `status:string`, `started_at:string?`, `finished_at:string?`, `planned_agents:int64`, `experiment_budget:int64`, `submitted_agents:int64?`, `accepted_measurements:int64?`, `completed_measurements:int64?`, `raw_path:string?`, `error_type:string?`, `error:string?`, `review_error:string?`, `missing_files:list<string>` | Manifest is status authority; counts from available summaries, otherwise null. Include all 60 planned entries for this definition. |
| agents: `(batch_id, run_id, agent)` | `author_id:string?`, `record_available:bool`, `reason:string?`, `parameters:list<float64>?`, `true_objective:float64?`, `experiments_used:int64?`, `experiments_completed:int64?`, `best_observed:float64?`, `duplicate_experiments:int64?`, `final_output_json:string?`, `usage_json:string?` | Summary reports are authoritative; identities supply UUIDs when available. Include four slots for each planned run without inventing sessions for absent reports. Preserve variable SDK structures as JSON strings. |
| measurements: `(batch_id, run_id, measurement_id)` | `agent:int64`, `author_id:string`, `parameters:list<float64>`, `observed:float64`, `started_at:string`, `completed_at:string?`, `completion_event_present:bool`, `publication_confirmed:bool?`, `source_path:string`, `source_locator:string` | Summary `experiment_records[agent]` when available; otherwise deduplicate `experiment_started` events by measurement UUID. Cross-check completion events. A completion timestamp is set before lab publication, so it alone cannot prove publication succeeded. |

Record transformation tool source/version and hash in `RELEASE.json`, together
with source batch checksums, selected batch IDs, export timestamp, release tag,
count reconciliation, exclusions, and redactions. Validate joins, unique keys,
eight-dimensional bounded vectors, event order, and accepted/completed counts.
Keep model/tool traces in raw JSONL; a separately browsable event table is deferred
unless requested. Do not coerce heterogeneous provider payloads into a guessed
flat schema or claim a standardized agent-trace format.

## Agreed completion rule and mandatory submission audit

The user defines fully complete as all 60 planned runs having status `finished`.
Do not publish partial batches; retain them locally for provenance. The user also
requires checking all 240 agents submitted. This is a separate mandatory audit,
not a redefinition of run completion. For each run verify four unique agent
indices (0–3), reason `submitted`, a submission in `summary.submissions`,
matching final parameters and a finite true score; cross-check submission events
and manifest outcomes. Report every missing/mismatched record or non-submission
with run ID, agent index and reason. If exceptions occur, surface them before
upload; do not silently drop agents or infer success from run status. Budget exhaustion is not a completion requirement: early valid
submission is allowed. If reruns produce the selected batch, disclose the
selection rule and earlier failed attempts without claiming the release includes
those attempts. The recommendations below govern interpreting raw records and
any later analysis; they do not override the complete-batch upload preference.

Runner run statuses are `pending`, `running`, `finished`, `error`, `cancelled`.
After a stopped batch, future entries can remain `pending`: this means unlaunched,
not currently scheduled work. Preserve that raw status; describe launch status
using available timestamps. Abrupt termination can leave stale `running` records;
report the observation rather than fabricating terminal outcomes.

Agent reasons include `submitted`, `final_answer_without_submission`,
`time_limit`, `turn_limit`, `error`, and `cancelled`; absent reports have null
reason. A run can be `finished` with time/turn limits or non-submission. API or
infrastructure failure stops subsequent repetitions, and whole runs are not
automatically retried. A later rerun must have a distinct batch ID, disclose why
it occurred, and never silently replace the failed attempt.

Retain partial runs locally; preserve accepted-but-interrupted measurements
within any selected released batch. Accepted calls
consume budget before the delay; timestamps/completion events and lab publication
must be distinguished. Final true scores require a submission and are null when
absent. `best_observed` is a noisy measurement statistic, not a final true score.
The batch HTML mean/best exclude non-submitters, which can introduce selection
bias. Proposed primary comparison: repetitions with all three runs `finished`,
reporting submission rates alongside scores conditional on submission. Also show
all-run attrition and disclose any stricter all-agents-submitted sensitivity
analysis; never encode missing scores as zero. Agents within one shared lab are
dependent; comparisons should respect the repetition/run grouping.

## Handoff to collection / packaging

1. Originating chat performs the all-60-finished and all-240-submission audit
   described above, then records collection boundaries in UTC, final batch IDs,
   statuses, actual reported sessions, submissions, accepted measurements,
   completion timestamps/events, file availability, and incidents. Planned
   maxima are 60 runs, 240 agent slots, and 2,400 accepted measurements; these
   are not observed results.
2. Once writers have stopped, verify original input, run, and batch checksums.
   Runner checksum maps omit any file named `checksums.json`; audit coverage as
   well as values. Missing final checksum files are disclosed for partial runs.
   `run_metadata.json` is written before review export, so a later `review_error`
   may appear only in the manifest. Resolve discrepancies explicitly.
3. Build an isolated release directory with an explicit file allowlist. Inspect
   free text, errors, absolute host paths in resolved configs, provider IDs,
   notes, and archive members for private information. Inspect archives without
   executing code or blindly extracting agent-created symlinks. Retain useful
   UUIDs/response IDs only as permitted by the agreed release scope.
4. Document raw schemas and release provenance; defer analysis tables; reconcile counts and
   missingness against raw records. Replace every card placeholder from evidence,
   add approved license/authorship/citation, then connect the final writeup.
5. Validate the card's metadata and raw-file inventory (and any later tables), review release bytes,
   licenses and checksums, then follow the separately authorized upload process.
   The user authorized creating the private repository, which is now complete.
   Data upload and public release have not been authorized by that creation step.

## References

- Local authority: `LICENSE` (especially Outputs, Notices, Silicoase branding),
  `docs/licensing.md`, `src/mad/experiment.py`, `rollout.py`, `recording.py`,
  `task.py`, `harness.py`, `environment.py`, and `tools.py`.
- [Hugging Face dataset cards](https://huggingface.co/docs/hub/datasets-cards)
- [Explicit dataset configurations](https://huggingface.co/docs/hub/datasets-manual-configuration)
- [Hub licenses](https://huggingface.co/docs/hub/repositories-licenses)
- [Local authentication](https://huggingface.co/docs/huggingface_hub/quick-start#authentication)
- [Token permissions](https://huggingface.co/docs/hub/security-tokens)
- [CC BY 4.0 terms](https://creativecommons.org/licenses/by/4.0/)

## Authentication recommendation

With user approval, installed the official `hf` package using `uv tool install hf`
on 2026-10-04. Verified `hf version` reports 2.1.1 and `hf auth login --help`
runs successfully. This is a user-level isolated tool installation; project
dependencies and lockfile were not changed. The user subsequently verified CLI authentication as `connacher-silicoase`
with `hf auth whoami`. Repository write access has not yet been verified.

The current CLI offers browser login or token paste. For the repository-scoped
token recommended here, run `hf auth login` in an interactive terminal and choose
**Paste an access token**. Browser login is an alternative with permissions
shown during its authorization flow. Neither login method uploads data.

After account signup and email verification, create the private dataset through
the website. Then use a dedicated fine-grained token with read/write access only
to that dataset for upload work, rather than broad account write access. Enter
it directly into the local `hf auth login` prompt and verify the account with
`hf auth whoami`; do not paste it into this chat. HF login stores a local token,
so that machine's user account must be trusted. For occasional local publication,
this is simpler than adding CI credentials. If upload automation is added later,
use its secret store, a separate scoped token, and a documented revocation path.
This is a recommendation, not authorization to create a token or change access.

## Agreed data license: CC BY 4.0

The user selected the recommended CC BY 4.0 option on 2026-10-04 for generated
research data, with credit to Connacher Murphy / Silicoase. See DATA_LICENSE.md. It permits commercial reuse
and adaptations, requires reasonable attribution, a license link and change
indication when shared, and is irrevocable for compliant recipients. It is not
a noncommercial license, and does not require adaptations to use the same
license. This decision allows commercial reuse of the separately licensed data.
The release must retain the software and third-party exclusions below.

The MAD license continues to govern included code, copied prompts/documentation,
HTML viewer code and branding. A commercial user could reuse separately
CC-BY-licensed data while still needing a separate agreement to use MAD software
for a prohibited commercial purpose. Mixed events/artifacts can contain copied
MAD text; specify component-level exclusions instead of assigning CC BY to
every byte in the raw tree. CC licenses grant only applicable rights held by the
licensor; they do not create copyright in facts or purely generated material,
or grant trademark/patent/privacy rights.

## License comparison (decision: CC BY 4.0)

The existing MAD LICENSE explicitly excludes outputs merely generated by using
the software. A separately scoped data license can therefore coexist with MAD
terms; this is a component separation, not relicensing of MAD-covered material.

| Option for separately licensed data | Reuse policy | Fit / tradeoff |
| --- | --- | --- |
| CC BY 4.0 | Commercial and noncommercial reuse, with attribution and change indication when shared | Broad research reuse with credit; software remains under MAD terms |
| CC BY-NC 4.0 | Noncommercial reuse, with attribution | Closer to a noncommercial data policy, but its use-purpose definition is not identical to MAD's explicit company-use and industry-sponsorship restrictions |
| CC0 1.0 | Waives applicable copyright/database rights as far as possible; commercial reuse and no mandatory credit | Lowest reuse friction; citation can be requested but is not a license condition |
| CC BY-SA 4.0 | Commercial reuse with attribution; shared adaptations use the same or a compatible license | Useful if reciprocal sharing is desired; creates extra licensing complexity |
| Custom data terms | Specify attribution and exact desired research/company/commercial boundaries | Could align closely with MAD policy, but needs separately drafted output terms and review; do not pretend current software scope already grants them |

Decision: CC BY 4.0 for broad reuse with attribution. Compatibility with MAD alone does not require
a noncommercial data license. Keep MAD terms/notices with source, copied
documentation/prompts, embedded viewer code and branding, including such portions
inside mixed logs/artifacts. Do not add MAD restrictions to the CC-licensed data
as extra conditions. Links: [CC BY](https://creativecommons.org/licenses/by/4.0/),
[CC BY-NC](https://creativecommons.org/licenses/by-nc/4.0/),
[CC0](https://creativecommons.org/publicdomain/zero/1.0/),
[CC BY-SA](https://creativecommons.org/licenses/by-sa/4.0/).

## Interim submission check — not final collection results

On 2026-10-04, a read-only snapshot of the available running batch manifest
`20261004T211502Z-442d48aa` found 9 finished runs. Their summaries contained
36/36 agents with reason `submitted`, submission mapping entries, final
parameters and non-null true scores. No exceptions were found in this limited
check. Remaining runs were not claimed complete. The final audit must repeat
after collection ends and additionally reconcile events/manifest and parameters.
The manifest batch ID differs from its containing folder's suffix; preserve
both identifiers in provenance rather than deriving batch ID from the folder.

## Final collection audit

See [RELEASE_AUDIT.md](RELEASE_AUDIT.md). The selected batch is finished: 60/60
runs, 240/240 confirmed agent submissions, 2,400 accepted measurements, all
with completion timestamps and publication events. All 62 checksum maps
verified, covering 1,264 entries / 636 unique files; expected run files are
present. Private-information scan and packaging conclusions are recorded in
the audit report. No data has been uploaded by this chat.

## Local packaging complete

The user authorized packaging. Built the raw-only `v1.0.0` derivative under
`outputs/huggingface-release/swarm-hackathon-demo-v1.0.0/`; see
[PACKAGING.md](PACKAGING.md) for contents, sanitization, validation and rebuilding.
Source originals were preserved. The local package has 766 files (625,037,238
bytes), verified derivative checksums, and a finalized root dataset card.
No upload or visibility change was performed.

## Private staging complete

The user authorized private staging. Uploaded the 766-file local v1.0.0 package
to the existing private dataset repository in six commits. Final staging commit:
`41f748be59f0e3206ecb2bd364bf2b0bc70a78ec`. All 766 expected files matched
remote content hashes (706 Git blobs, 60 LFS objects), with no missing/unexpected
package files or mismatches. The only additional remote file is the built-in
`.gitattributes`. Repository privacy was verified before and after upload. See
[STAGING_VERIFICATION.json](STAGING_VERIFICATION.json). Public visibility was
not changed, and no Parquet tables were uploaded.

## Public release complete

The user explicitly authorized public release. Finalized metadata and checksum
updates, verified all 766 package files, created tag `v1.0.0` at commit
`3b44372a47184e074b79f226e2a4938f454e2f38`, and set repository visibility public.
Unauthenticated access to the tagged inventory and checksum-matching downloads
of README.md and a raw summary succeeded. See
[PUBLIC_RELEASE_VERIFICATION.json](PUBLIC_RELEASE_VERIFICATION.json).
The release remains raw-only; all original batch files are preserved locally.

## Repository naming update — 2026-10-07

With explicit user authorization, renamed the GitHub project to `silicoase/MEAD`
and the Hugging Face dataset to `connacher-silicoase/MEAD`. Both use the title
Model Environment for Agent Discovery (MEAD). Updated active documentation
links and the dataset main-branch display metadata; the original `v1.0.0` tag
remains pinned to its original commit and the experiment identifier remains
`swarm-hackathon-demo`. Historical verification records retain original names.
See RENAME_VERIFICATION.json for the renamed dataset content verification.
The local checkout will be named MEAD; an old-path compatibility symlink lets
existing Codex chats continue using their saved project path.
