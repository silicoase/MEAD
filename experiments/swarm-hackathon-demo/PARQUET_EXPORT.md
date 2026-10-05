# Optional Parquet tables

The initial Hugging Face release remains raw-only. The standalone exporter is
ready for local preparation and a later release revision. It does not launch
experiments, call model/Hugging Face APIs, extract archives, or modify raw files.
PyArrow is installed into an isolated `uv run --with` environment; this does not
change the experiment configuration, project dependencies or lockfile.

From the repository root, after collection stops:

```sh
uv run --locked --with pyarrow python scripts/export_batch_parquet.py \
  outputs/swarm-hackathon-demo/<batch-folder> \
  outputs/publication-tables/<new-export-folder>
```

Replace the placeholders with actual folders. The destination must not already
exist and must be separate from the raw batch. The exporter rejects a batch
unless its status and every planned run status are `finished`. When the manifest
includes conditions/repetitions, it verifies the entire expected grid exists.
For this experiment, that is 60 runs. Completion does not imply all agents
submitted: inspect the separate submission audit in `RELEASE.json`.

For a **local preview** of incomplete records, add `--allow-incomplete`. This
marks the export `preview: true` whenever the batch is unfinished. Missing and
pending agent slots appear in the audit; they are not failures of completed
sessions. A malformed/truncated event line or changed input causes export to
fail; retry after the current writes stop. Preview exports are not release
candidates. Exporting from live files is a best-effort consistency check, not
an atomic snapshot of collection.

## Output

| File | Contents |
| --- | --- |
| `runs.parquet` | One row per planned run, condition/seeds/status, counts, raw location and missing files |
| `agents.parquet` | One row per planned agent slot; nulls for absent reports; final results, usage and submission confirmation |
| `measurements.parquet` | One row per accepted measurement, including interrupted calls; parameters, noisy observation and completion/publication evidence |
| `SCHEMA.json` | Explicit Arrow field types and nullability; typed even for empty tables |
| `RELEASE.json` | Batch ID and folder name, export time, preview/completion state, submission issues, counts, input hashes, exporter hash and PyArrow version |
| `checksums.json` | SHA-256 for all exported files except itself |

Keys: `(batch_id, run_id)` for runs; add `agent` for agents, or `measurement_id`
for measurements. Measurement records' raw `run_id` becomes `measurement_id` in
the table. The manifest is the source of `batch_id`; the containing folder name
is recorded separately. Schema version 1 concerns derived tables, not the runner
manifest or metadata versions. Variable provider usage/final-output structures
remain JSON strings. No raw model/tool trace table is created.

Measurements use summary records when available, otherwise event records;
conflicting fields and duplicate IDs cause failure. Counts are reconciled with
agent reports. A completion timestamp is not proof of lab publication;
`publication_confirmed=true` requires an `experiment_completed` event. If no
such event exists, confirmation is null rather than an assertion of failure.

The submission audit checks reason `submitted`, a finite true score, matching
summary submission and final-parameter vectors, a matching submission event,
and agreement with manifest agent outcomes where available. It reports issues
without dropping rows. `confirmed_submissions` and `submission_confirmed` are
derived audit fields; `submitted_agents` preserves the reason-based count.
This checks recorded evidence rather than recomputing the objective or proving
the raw trace is complete. The final release should verify all 240 expected
agents, reconcile identities and artifacts, and disclose exceptions.

Input hashes describe the exact parsed manifest/config/identity/summary/event
files. Files are rechecked for changes before the staged export is renamed into
place. This is not a full audit of original batch/input/run checksum maps or
artifact contents; those remain separate publication checks. Raw checksum files
are never rewritten. Output creation is staged, and existing exports are not
overwritten.

## Before adding tables to Hugging Face

Review submission issues, final counts, license scope, and private-information
checks. Add the three files under the release's `data/` directory, include
export schema/provenance/checksums, and update the card with explicit table
configs. Keep raw bytes and the original tagged release unchanged. Set the
card's configs only after files exist and load correctly; there is no train/test
assignment. Archive the exporter version/hash with the release for reproducibility.

Validation performed: eight focused tests cover Parquet round trips, raw-file
preservation, incomplete batches/nulls, non-submission, event fallback for an
interrupted measurement, count mismatches, unsafe paths, input mutation, empty
table schemas, planned-grid omissions and duplicate measurement starts. A local
incomplete-batch preview also round-tripped successfully; this is not a final
collection report or an upload.
