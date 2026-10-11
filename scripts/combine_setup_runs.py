"""Create a derived view of setup sets across attempts without rewriting raw data."""

import argparse
import hashlib
import json
from pathlib import Path


def combine(sources, output):
    sources = [source.resolve() for source in sources]
    output = output.resolve()
    if any(output.is_relative_to(source) for source in sources):
        raise ValueError("derived view must stay outside every raw batch")
    manifests = [json.loads((source / "manifest.json").read_text()) for source in sources]
    hashes = {
        hashlib.sha256((source / "inputs/code/src/mad/task.py").read_bytes()).hexdigest()
        for source in sources
    }
    if len(hashes) != 1:
        raise ValueError("objective implementations differ across attempts")
    models = list(manifests[0]["model_configs"])
    if any(
        not set(m["model_configs"]).issubset(models) or m["conditions"] != manifests[0]["conditions"]
        for m in manifests
    ):
        raise ValueError("model roster and conditions must match across attempts")
    latest = {}
    for source, manifest in zip(sources, manifests):
        for entry in manifest["runs"]:
            key = (
                entry["model_key"],
                entry["condition"],
                entry["objective_seed"],
                entry["noise_seed"],
            )
            latest[key] = (source, entry)
    seeds = sorted({key[2:] for key in latest})
    output.mkdir(parents=True, exist_ok=True)

    def link(path, target):
        if path.is_symlink():
            if path.resolve() == target.resolve():
                return
            path.unlink()
        elif path.exists():
            raise ValueError(f"refusing to replace a non-link path: {path}")
        path.symlink_to(target, target_is_directory=True)

    (output / "inputs").mkdir(exist_ok=True)
    link(output / "inputs/code", sources[0] / "inputs/code")
    runs = []
    for repetition, (objective_seed, noise_seed) in enumerate(seeds, 1):
        for model in models:
            for condition in manifests[0]["conditions"]:
                source, original = latest[(model, condition, objective_seed, noise_seed)]
                entry = dict(original)
                entry["repetition"] = repetition
                entry["run_id"] = f"{model}-{condition}-{repetition:03d}"
                entry["source_batch"] = str(source)
                entry["source_run_id"] = original["run_id"]
                directory = source / original["run_id"]
                if directory.exists():
                    link(output / entry["run_id"], directory)
                runs.append(entry)
    manifest = dict(
        manifests[0],
        name="cross-provider-setup-combined",
        repetitions=len(seeds),
        runs=runs,
        sources=[str(source) for source in sources],
        derived=True,
        objective_source_sha256=next(iter(hashes)),
    )
    statuses = {entry["status"] for entry in runs}
    manifest["status"] = (
        "finished" if statuses == {"finished"} else "error" if "error" in statuses else "running"
    )
    temporary = output / "manifest.tmp.json"
    temporary.write_text(json.dumps(manifest, indent=2) + "\n")
    temporary.replace(output / "manifest.json")
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "runs": len(runs),
                "finished": sum(r["status"] == "finished" for r in runs),
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("sources", type=Path, nargs="+")
    args = parser.parse_args()
    combine(args.sources, args.output)
