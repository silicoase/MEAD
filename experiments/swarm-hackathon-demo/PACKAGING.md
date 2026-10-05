# Local release package

Prepared `v1.0.0` at:

`outputs/huggingface-release/swarm-hackathon-demo-v1.0.0/`

This package is publicly released on Hugging Face as `v1.0.0`, with user
authorization. Final commit: `3b44372a47184e074b79f226e2a4938f454e2f38`. It is raw-only;
Parquet tables remain optional for a later revision. There are 766 files,
625,037,238 bytes (about 625 MB).

## Contents and validation

The root README is the release card. It links to DATA_LICENSE.md, NOTICE.md,
SCHEMA.md, RELEASE_AUDIT.md, and TRANSFORMATIONS.json. LICENSE contains the full
CC BY 4.0 text downloaded from the official Creative Commons legal-code URL;
LICENSES/MAD-LICENSE.txt preserves the exact original MAD license. Each original
raw license and source notice also remains in the raw subtree.

Raw data is under `raw/20261004T211502Z-442d48aa/`. The original containing
folder name is recorded separately in RELEASE.json. Download that subtree and
open index.html or the run viewers locally; relative links are preserved.

- All 60 runs and all 240 submissions passed the packaging audit.
- 2,400 accepted measurements are present and confirmed complete/published.
- Local host paths were sanitized in 240 text files. Four generated runtime
  bytecode-cache files were omitted. 61 affected checksum maps were regenerated.
- All 60 lab archives were copied byte-for-byte. They were inspected without
  extraction; the prior scan found no host-path hits or unsafe path/link members.
- Original checksum maps remain under provenance/original-checksums. They
  describe original bytes, not files in that mirrored storage subtree.
- Every source file hash was checked unchanged before/after packaging. The
  original batch was not modified.
- All derivative checksum maps and the top-level release checksum map verified.
  No local host-path patterns remained in non-archive package files.
- The root card has no broken local links or unresolved OPEN/PENDING markers.
  The immutable Hub commit remains pending upload; a later writeup link can be
  added when finalized.
- Four focused packaging tests and lint checks passed.

Provider response/request IDs and opaque provider encrypted-content payloads
are retained as experiment provenance. A bounded credential-pattern scan found
only incidental matches in those encrypted payloads, not access-token fields.
This scan is not a guarantee of absence of all private information.

Private staging is complete at commit
`41f748be59f0e3206ecb2bd364bf2b0bc70a78ec`. Write access worked, all 766 package
files matched remote Git/LFS content hashes, and the repository remained private.
See STAGING_VERIFICATION.json. Public visibility is a separate release step
after review. The final public card references the `v1.0.0` release tag. Public release
verification is recorded in PUBLIC_RELEASE_VERIFICATION.json; the earlier
private-stage check is retained as historical evidence. No Parquet tables were uploaded.

## Rebuilding

From the repository root, download the canonical CC BY 4.0 legal text to a local
file, then run the packager with a **new** destination:

```sh
curl --fail --location https://creativecommons.org/licenses/by/4.0/legalcode.txt \
  --output /tmp/cc-by-4.0-legalcode.txt
python3 scripts/package_batch_release.py \
  outputs/swarm-hackathon-demo/20261004T211502Z-03c650a5 \
  outputs/huggingface-release/<new-package-folder> \
  --cc-license /tmp/cc-by-4.0-legalcode.txt --version v1.0.0
```

The packager has no model/API calls or upload behavior. It rejects existing
destinations, incomplete batches, non-submissions, source checksum mismatches,
and source changes during packaging. License text is supplied explicitly; the
packager itself does not download dependencies or license terms.

Final metadata changes affected README.md, DATA_LICENSE.md, RELEASE.json and
the root checksum map. These were verified before public visibility changed.
The `v1.0.0` tag pins the final commit; public anonymous downloads were verified.
