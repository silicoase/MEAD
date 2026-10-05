# Final batch audit

Read-only audit performed 2026-10-04. No data was uploaded and original raw
files/checksums were not changed. This confirms collection completeness, not
completion of release packaging or public-release authorization.

## Collection and consistency

| Check | Result |
| --- | --- |
| Manifest batch ID | `20261004T211502Z-442d48aa` |
| Raw batch folder | `outputs/swarm-hackathon-demo/20261004T211502Z-03c650a5` |
| Collection start / finish | 2026-10-04 21:15:02.946689 / 23:24:38.526392 UTC |
| Batch status | `finished` |
| Planned condition/repetition grid | All 60 entries present: 20 repetitions × 3 conditions |
| Run statuses | 60 `finished`; no other statuses |
| Agent reports / confirmed submissions | 240 / 240 |
| Accepted measurements | 2,400 |
| Measurements with completion timestamps | 2,400 |
| Measurements with completion/publication events | 2,400 |
| Submission inconsistencies | None |
| Invalid final parameter vectors | None; all eight-dimensional and within [0,1] |
| Missing expected run files | None |
| Checksum maps verified | 62 (batch, inputs, 60 runs) |
| Checksum entries / unique files verified | 1,264 / 636 |
| Checksum mismatches or missing referenced files | None |
| Raw batch size | 624,652,635 bytes (about 625 MB) |

Submission confirmation used agent reason `submitted`, finite final score,
matching final parameters in the summary submission mapping and submission
event, and agreement with available manifest outcomes. Measurement identity,
summary/event agreement, sequence order and per-agent accepted/completed counts
were reconciled by `scripts/export_batch_parquet.py`. Parsed files were rehashed
to check they had not changed during the audit. Full stored checksum maps were
also checked independently, hashing actual file bytes.

Preserve both the manifest ID and containing folder name: their suffixes differ.
Do not infer the batch ID from the folder or rename provenance fields silently.

## Initial publication scan

Scanned 638 non-archive files and inspected 4,039 tar archive members without
extracting or executing agent-created files. No absolute/traversal archive paths
or symbolic/hard links were found.

- Credential-pattern matches occurred in two files (one event log and its HTML
  viewer). JSON inspection traced them solely to opaque provider
  `encrypted_content` fields, not credential fields. These are incidental
  matches inside encoded provider data; no token values are reproduced here.
- Email-pattern matches in 27 file/member locations were Python matrix-operation
  expressions. All 16 distinct matches were classified as code expressions.
- Local absolute host-path patterns occur in 244 files, primarily resolved
  configuration and copies in events/viewers, with some objective-reference
  metadata. Review or sanitize these paths in a separate release derivative
  before public distribution.

This bounded pattern scan is not a guarantee that all private information is
absent. It does not validate provider identifiers as safe to disclose or decide
whether every copied/generated component can be offered under CC BY 4.0.

## Remaining packaging work

1. Prepare a separate raw-first release directory with the finalized card,
   CC BY 4.0 terms and data-scope notice, exact MAD license/notices and a
   component/path map of exclusions. Include the full source/provenance package.
2. Decide the release treatment of local host paths and provider response/request
   IDs. If sanitizing, keep the original privately, record the changed
   paths/components without secret values, regenerate affected HTML as needed,
   and compute new derivative checksums. Original checksum maps authenticate
   original bytes, not transformed files.
3. Set a release version/tag, reconcile the final inventory/counts, and verify
   that authentication grants write access to the selected private dataset.
4. Stage and review the release using the separately authorized upload process.
   The first release remains raw-only; optional Parquet tables can follow.

The dataset card has been updated with these audited collection counts and dates.
The originating chat continues to own the final results writeup and figures.
