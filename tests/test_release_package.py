import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def packager(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location(
        "release_package", scripts / "package_batch_release.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sanitization_preserves_json_and_unrelated_identifiers(packager):
    import json

    original = json.dumps(
        {
            "source": str(packager.PROJECT / "outputs/inputs/config.toml"),
            "other": "/home/example/private/file",
            "author_id": "uuid-123",
            "response_id": "resp_example",
        }
    ).encode()
    result = json.loads(packager.sanitized(original))
    assert result["source"] == "/MAD_REPOSITORY/outputs/inputs/config.toml"
    assert result["other"] == "/LOCAL_USER/private/file"
    assert result["author_id"] == "uuid-123"
    assert result["response_id"] == "resp_example"


def test_original_checksum_maps_are_preserved_without_reinterpreting(packager, tmp_path):
    import hashlib
    import json

    original = tmp_path / "provenance/original-checksums/checksums.json"
    original.parent.mkdir(parents=True)
    original.write_text(json.dumps({"absent-original-only-file": "original-digest"}))
    (tmp_path / "checksums.json").write_text(
        json.dumps(
            {str(original.relative_to(tmp_path)): hashlib.sha256(original.read_bytes()).hexdigest()}
        )
    )
    packager.verify_maps(tmp_path)
    original.write_text("{}")
    with pytest.raises(ValueError, match="Checksum mismatch"):
        packager.verify_maps(tmp_path)


def test_packager_refuses_existing_destination_before_reading_inputs(packager, tmp_path):
    with pytest.raises(ValueError, match="new directory"):
        packager.package(tmp_path / "raw", tmp_path, tmp_path / "missing-license")


def test_release_card_has_resolvable_documentation_and_no_planning_markers(packager):
    card = (packager.PROJECT / "experiments/swarm-hackathon-demo/DATASET_CARD.md").read_text()
    result = packager.release_card(card, "v1.0.0", "batch-id")
    assert "PUBLICATION_PLAN.md" not in result
    assert "**OPEN" not in result
    assert "**PENDING" not in result
    assert "raw/batch-id/" in result
    assert "v1.0.0" in result
    assert "license: cc-by-4.0" in result
