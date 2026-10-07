"""Build a local raw-first release derivative; never upload or change the source batch."""

import argparse
import hashlib
import json
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from export_batch_parquet import collect

PROJECT = Path(__file__).resolve().parents[1]
HOST_PREFIX = re.compile(rb"/(?:Users|home)/[A-Za-z0-9_.-]+/")
TEXT_SUFFIXES = {".json", ".jsonl", ".html", ".md", ".txt", ".toml", ".py", ".lock"}


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def file_map(root, include_checksum_files=False):
    return {
        str(p.relative_to(root)): digest(p)
        for p in sorted(root.rglob("*"))
        if p.is_file() and (include_checksum_files or p.name != "checksums.json")
    }


def verify_maps(root):
    cache = {}
    for checksum_file in sorted(root.rglob("checksums.json")):
        if checksum_file.relative_to(root).parts[:2] == ("provenance", "original-checksums"):
            continue
        for relative, expected in json.loads(checksum_file.read_text()).items():
            path = checksum_file.parent / relative
            if not path.resolve().is_relative_to(root) or not path.is_file():
                raise ValueError(f"Missing or unsafe checksum entry: {relative}")
            actual = cache.setdefault(path, None)
            if actual is None:
                actual = cache[path] = digest(path)
            if actual != expected:
                raise ValueError(f"Checksum mismatch: {path.relative_to(root)}")


def sanitized(data):
    # The actual repository prefix removes intermediate private directory names, too.
    data = data.replace(str(PROJECT).encode(), b"/MAD_REPOSITORY")
    return HOST_PREFIX.sub(b"/LOCAL_USER/", data)


def release_card(card, version, batch_id):
    card = re.sub(
        r"\*\*Release draft.*?launch-time card inside the raw batch snapshot\.\n",
        "This raw-first release contains the completed batch and a documented "
        "host-path-sanitized derivative. See [RELEASE_AUDIT.md](RELEASE_AUDIT.md), "
        "[TRANSFORMATIONS.json](TRANSFORMATIONS.json) and "
        "[NOTICE.md](NOTICE.md). The original launch-time card remains in the "
        "raw snapshot.\n",
        card,
        count=1,
        flags=re.S,
    )
    card = card.replace(
        "| Release version / immutable revision | **OPEN** |",
        f"| Release version / immutable revision | {version}; Hub commit pending upload |",
    )
    card = card.replace(
        "| Release layout / exclusions / redactions | **AGREED:** raw batch first, "
        "optional analysis tables later; exclusions/redactions pending review |",
        "| Release layout / exclusions / redactions | Raw batch derivative; "
        "host paths sanitized, runtime bytecode caches omitted; "
        "see TRANSFORMATIONS.json and NOTICE.md |",
    )
    start = card.index("**Agreed initial layout:**")
    end = card.index("### Raw files", start)
    card = (
        card[:start]
        + (
            f"Raw records are under `raw/{batch_id}/`. Download this subtree to preserve "
            "relative viewer links. Open `index.html` or individual `review.html` files locally. "
            "There are no Parquet tables or predefined training/test splits in this release. "
            "See [SCHEMA.md](SCHEMA.md) for raw file formats. Later revisions may add analysis "
            "tables; cite the release revision actually used.\n\n"
        )
        + card[end:]
    )
    card = card.replace(
        "**PENDING:** additional collection or access limitations.",
        "No additional collection incidents were identified by the recorded audit.",
    )
    start = card.index("See RELEASE_AUDIT.md for scope and limits. **PENDING:**")
    end = card.index("\n\n## Citation", start)
    card = (
        card[:start]
        + (
            "See RELEASE_AUDIT.md for scope and limits. Local host paths were replaced by "
            "`/MAD_REPOSITORY` or `/LOCAL_USER/` in the release copy; generated source-bytecode "
            "caches were omitted. Original files remain private. Original checksum maps are "
            "preserved under `provenance/original-checksums/`; the derivative has new checksum "
            "maps. Provider response/request IDs and encrypted provider payloads are retained "
            "as recorded provenance; no access tokens were identified by the scan. "
            "See TRANSFORMATIONS.json for every modified/omitted file."
        )
        + card[end:]
    )
    card = re.sub(
        r"\*\*OPEN:\*\* formal citation.*?date is asserted by this draft\.",
        f"Suggested citation: Murphy, Connacher (2026). *swarm-hackathon-demo*, "
        f"{version}. Silicoase. "
        "https://huggingface.co/datasets/connacher-silicoase/MEAD-swarm-hackathon. "
        "Include the immutable Hub commit used once uploaded. No DOI is assigned. "
        "The results writeup will be linked separately when finalized.",
        card,
        flags=re.S,
    )
    return card


def package(batch, output, license_text, version="v1.0.0", expected_runs=60, expected_agents=240):
    batch, output = batch.resolve(), output.resolve()
    if output.exists() or output.is_relative_to(batch) or batch.is_relative_to(output):
        raise ValueError("Destination must be a new directory separate from the batch")
    terms = license_text.read_text()
    if "Attribution 4.0 International" not in terms or "Section 8" not in terms:
        raise ValueError("Supply the full official CC BY 4.0 legal text")
    inputs, manifest, tables, issues = collect(batch)
    if (
        manifest["status"] != "finished"
        or len(tables["runs"]) != expected_runs
        or any(r["status"] != "finished" for r in tables["runs"])
        or len(tables["agents"]) != expected_agents
        or issues
    ):
        raise ValueError("Completion or all-agent submission audit failed")
    verify_maps(batch)
    before = file_map(batch, include_checksum_files=True)
    definitions = PROJECT / "experiments/swarm-hackathon-demo"
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".release-", dir=output.parent))
    try:
        raw = staging / "raw" / manifest["batch_id"]
        raw.mkdir(parents=True)
        changes = []
        for relative, source_hash in before.items():
            source = batch / relative
            if source.is_symlink():
                raise ValueError(f"Refusing symlink: {relative}")
            if "__pycache__" in source.relative_to(batch).parts or source.suffix == ".pyc":
                changes.append(
                    dict(path=relative, action="omit_runtime_bytecode", source_sha256=source_hash)
                )
                continue
            target = raw / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            if source.name == "checksums.json":
                saved = staging / "provenance/original-checksums" / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, saved)
            elif source.suffix in TEXT_SUFFIXES:
                original = source.read_bytes()
                transformed = sanitized(original)
                if transformed != original:
                    target.write_bytes(transformed)
                    changes.append(
                        dict(
                            path=relative,
                            action="sanitize_local_host_paths",
                            source_sha256=source_hash,
                            release_sha256=digest(target),
                        )
                    )
        checksum_paths = sorted(
            raw.rglob("checksums.json"), key=lambda p: len(p.parts), reverse=True
        )
        for path in checksum_paths:
            save(path, file_map(path.parent))
            if digest(path) != before[str(path.relative_to(raw))]:
                changes.append(
                    dict(
                        path=str(path.relative_to(raw)),
                        action="regenerate_derivative_checksums",
                        source_sha256=before[str(path.relative_to(raw))],
                        release_sha256=digest(path),
                    )
                )
        (staging / "LICENSE").write_text(terms)
        (staging / "LICENSES").mkdir()
        shutil.copyfile(batch / "LICENSE", staging / "LICENSES/MAD-LICENSE.txt")
        for name in ("DATA_LICENSE.md", "RELEASE_AUDIT.md"):
            shutil.copyfile(definitions / name, staging / name)
        license_path = staging / "DATA_LICENSE.md"
        license_path.write_text(
            license_path.read_text().replace(
                "release revision\n  is pending collection and packaging.",
                f"local package version is {version}; immutable Hub commit is pending upload.",
            )
        )
        card = release_card(
            (definitions / "DATASET_CARD.md").read_text(), version, manifest["batch_id"]
        )
        (staging / "README.md").write_text(card)
        schema_start = card.index("### Raw files")
        schema_end = card.index("## Incomplete runs", schema_start)
        (staging / "SCHEMA.md").write_text("# Raw schemas\n\n" + card[schema_start:schema_end])
        (staging / "NOTICE.md").write_text(
            "# License scope and modification notice\n\n"
            "Generated measurements, submissions, outcomes and generated portions of traces/artifacts "
            "are offered under CC BY 4.0 (root LICENSE); credit Connacher Murphy (Silicoase). "
            "See DATA_LICENSE.md.\n\n"
            "The CC grant excludes MAD-covered material: `raw/*/inputs/code/**`, copied experiment "
            "prompts/documentation in `raw/*/inputs/experiment/**`, MAD instructions/tool descriptions "
            "copied into events and artifacts (including workspace task.md), and HTML viewer code "
            "and branding in `raw/*/index.html` and `raw/*/*/review.html`. Those components retain "
            "the Silicoase Noncommercial License, Version 2.0 (LICENSES/MAD-LICENSE.txt and raw "
            "LICENSE files). Mixed files contain both generated data and covered software text; "
            "CC BY does not relicense the latter. Third-party material retains its own terms; "
            "dependencies are referenced by the source lockfile, not redistributed as installed "
            "packages. This grant covers only rights held by the publisher.\n\n"
            "Required Notice: Copyright (c) 2026 Silicoase, Inc.\n\n"
            "Release derivative prepared by Connacher Murphy (Silicoase): host paths sanitized "
            "and runtime bytecode caches omitted. Changes are itemized in TRANSFORMATIONS.json. "
            "Viewer logic and lab archives are unchanged. Preserved source fingerprints describe "
            "the original bytes; regenerated checksum maps describe the derivative.\n"
        )
        save(
            staging / "TRANSFORMATIONS.json",
            dict(
                source_batch_id=manifest["batch_id"],
                source_folder=batch.name,
                changes=changes,
                original_checksums="provenance/original-checksums",
                archives="copied byte-for-byte",
            ),
        )
        save(
            staging / "RELEASE.json",
            dict(
                version=version,
                layout="raw-only",
                batch_id=manifest["batch_id"],
                source_folder=batch.name,
                packaged_at=datetime.now(timezone.utc).isoformat(),
                counts={k: len(v) for k, v in tables.items()},
                all_agents_submitted=True,
                data_license="CC-BY-4.0",
                raw_path=str(raw.relative_to(staging)),
                packager_sha256=digest(Path(__file__)),
                source_files_sha256=before,
                provider_identifiers="retained",
                published=False,
                cc_license_source="https://creativecommons.org/licenses/by/4.0/legalcode.txt",
            ),
        )
        inputs.verify_unchanged()
        if before != file_map(batch, include_checksum_files=True):
            raise ValueError("Raw batch changed during packaging")
        verify_maps(raw)
        save(staging / "checksums.json", file_map(staging, include_checksum_files=True))
        verify_maps(staging)
        # Original maps refer to the original bytes, not their mirrored storage subtree.
        staging.rename(output)
        return dict(
            output=str(output),
            version=version,
            modified_or_omitted_files=len(changes),
            files=sum(p.is_file() for p in output.rglob("*")),
        )
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cc-license", type=Path, required=True)
    parser.add_argument("--version", default="v1.0.0")
    args = parser.parse_args()
    print(json.dumps(package(args.batch, args.output, args.cc_license, args.version), indent=2))


if __name__ == "__main__":
    main()
