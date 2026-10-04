import io
import json
import tarfile
from types import SimpleNamespace

import pytest

from mad.review import (
    collaboration_flags,
    context_growth,
    export_review,
    load_run,
    recover_interfaces,
)


def make_run(tmp_path):
    (tmp_path / "config.json").write_text(
        json.dumps({"agents": 2, "harness": {"kind": "scripted"}})
    )
    return tmp_path


def test_peer_read_and_matching_submission_are_candidates_not_proof():
    events = [
        {
            "sequence": 1,
            "agent": 0,
            "kind": "experiment_completed",
            "record": {"run_id": "one", "parameters": [0.5]},
        },
        {
            "sequence": 2,
            "agent": 1,
            "kind": "tool_called",
            "tool": "read_file",
            "arguments": {"path": "/lab/runs/one.json"},
        },
        {"sequence": 3, "agent": 1, "kind": "tool_result", "result": "measurement"},
        {"sequence": 4, "agent": 1, "kind": "submission", "parameters": [0.5]},
    ]
    flags = collaboration_flags(events, {}, {})
    assert len(flags) == 2
    assert flags[0]["peer"] == 0
    assert flags[0]["sequence"] == 2
    assert "unknown" in flags[0]["strength"]
    assert "not established" in flags[1]["strength"]
    events[2]["result"] = {"error": "not visible"}
    assert len(collaboration_flags(events, {}, {})) == 1
    events.insert(
        0,
        {
            "sequence": 0,
            "agent": 1,
            "kind": "experiment_completed",
            "record": {"run_id": "own", "parameters": [0.5]},
        },
    )
    assert not collaboration_flags(events, {}, {})


def test_export_escapes_agent_html_and_preserves_recorded_interface(tmp_path):
    make_run(tmp_path)
    attack = "</script><script>window.injected=true</script>"
    interface = {
        "sequence": 1,
        "agent": 0,
        "kind": "agent_interface",
        "instructions": attack,
        "tools": [{"name": "submit", "description": "finish", "parameters": {"type": "object"}}],
    }
    (tmp_path / "events.jsonl").write_text(json.dumps(interface) + "\n")
    data = load_run(tmp_path)
    assert data["interfaces"]["0"]["source"] == "Recorded at execution"
    html = export_review(tmp_path).read_text()
    assert attack not in html
    assert "\\u003c/script>" in html
    assert "__MAD_RUN_DATA__" not in html


def test_old_partial_run_labels_reconstructed_tools_and_incomplete_tail(tmp_path):
    make_run(tmp_path)
    (tmp_path / "events.jsonl").write_text(
        json.dumps(
            {
                "sequence": 1,
                "agent": 0,
                "kind": "model_request",
                "system_prompt": "Recorded prompt",
                "input_items": [],
            }
        )
        + '\n{"kind":'
    )
    data = load_run(tmp_path)
    assert data["interfaces"]["0"]["instructions"] == "Recorded prompt"
    assert "not recorded for this run" in data["interfaces"]["0"]["source"]
    assert len(data["notices"]) == 3
    assert export_review(tmp_path).exists()


def test_archive_previews_do_not_extract_paths_or_follow_symlinks(tmp_path):
    make_run(tmp_path)
    with tarfile.open(tmp_path / "artifacts.tar", "w") as archive:
        entry = tarfile.TarInfo("../../outside.md")
        content = b"preview without extraction"
        entry.size = len(content)
        archive.addfile(entry, io.BytesIO(content))
        link = tarfile.TarInfo("work/0/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        archive.addfile(link)
    data = load_run(tmp_path)
    assert data["artifacts"][0]["text"] == "preview without extraction"
    assert data["artifacts"][1]["symlink"] == "/etc/passwd"
    assert "text" not in data["artifacts"][1]


def test_malformed_nonfinal_event_is_rejected(tmp_path):
    make_run(tmp_path)
    (tmp_path / "events.jsonl").write_text('bad\n{"kind":"submission"}\n')
    with pytest.raises(ValueError, match="line 1"):
        load_run(tmp_path)


def test_context_uses_per_call_tokens_keeps_cache_and_separates_spend():
    events = [
        {"kind": "model_request", "agent": 0, "sequence": 1, "elapsed_seconds": 1},
        {"kind": "model_request", "agent": 1, "sequence": 2, "elapsed_seconds": 2},
        {
            "kind": "model_response",
            "agent": 1,
            "sequence": 3,
            "elapsed_seconds": 3,
            "usage": {"input_tokens": 100, "output_tokens": 20},
        },
        {
            "kind": "model_response",
            "agent": 0,
            "sequence": 4,
            "elapsed_seconds": 4,
            "usage": {
                "input_tokens": 200,
                "output_tokens": 30,
                "input_tokens_details": {"cached_tokens": 100},
            },
        },
        {"kind": "model_request", "agent": 0, "sequence": 5, "elapsed_seconds": 5},
        {
            "kind": "model_response",
            "agent": 0,
            "sequence": 6,
            "elapsed_seconds": 6,
            "usage": {"input_tokens": 300, "output_tokens": 40},
        },
    ]
    points = context_growth(events)
    assert [p["input_tokens"] for p in points] == [100, 200, 300]
    assert [p["elapsed_seconds"] for p in points] == [2, 1, 5]
    assert points[1]["cached_tokens"] == 100
    assert points[2]["input_tokens"] == 300
    assert points[2]["cumulative_input_tokens"] == 500
    assert points[2]["turn"] == 2


def test_context_does_not_invent_usage_for_missing_or_scripted_calls():
    events = [
        {"kind": "model_response", "agent": 0, "sequence": 1, "usage": {}},
        {
            "kind": "model_response",
            "agent": 0,
            "sequence": 2,
            "elapsed_seconds": 2,
            "usage": {"input_tokens": 0, "output_tokens": 1},
        },
    ]
    assert context_growth([]) == []
    points = context_growth(events)
    assert len(points) == 1
    assert points[0]["input_tokens"] == 0
    assert points[0]["turn"] == 2


def test_recovery_uses_original_provider_tools_and_keeps_provenance(tmp_path):
    make_run(tmp_path)
    events = [
        {"sequence": i + 1, "agent": i, "kind": "model_response", "response_id": f"r-{i}"}
        for i in range(2)
    ]
    (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    original = (tmp_path / "events.jsonl").read_bytes()
    calls = []

    class OriginalTool:
        def model_dump(self, mode):
            return {
                "type": "function",
                "name": "original_tool",
                "description": "Original",
                "parameters": {"type": "object"},
                "strict": True,
            }

    def retrieve(response_id):
        calls.append(response_id)
        return SimpleNamespace(
            id=response_id,
            tools=[OriginalTool()],
            instructions="Original prompt",
            model="original-model",
            created_at=123,
        )

    client = SimpleNamespace(responses=SimpleNamespace(retrieve=retrieve))
    recovered = recover_interfaces(tmp_path, client)
    assert calls == ["r-0", "r-1"]
    assert recovered["0"]["tools"][0]["name"] == "original_tool"
    assert recovered["1"]["provider_response_id"] == "r-1"
    assert (tmp_path / "events.jsonl").read_bytes() == original
    data = load_run(tmp_path)
    assert "recovered from stored" in data["interfaces"]["0"]["source"]
    assert not any("Tool definitions were not recorded" in notice for notice in data["notices"])
    recover_interfaces(tmp_path, client)
    assert calls == ["r-0", "r-1"]  # No network calls for an already enriched run.


def test_partial_recovery_is_saved_without_claiming_remaining_schema(tmp_path):
    make_run(tmp_path)
    events = [
        {"sequence": i + 1, "agent": i, "kind": "model_response", "response_id": f"r-{i}"}
        for i in range(2)
    ]
    (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))

    def retrieve(response_id):
        if response_id == "r-1":
            raise RuntimeError("Unavailable")
        return SimpleNamespace(
            id=response_id, tools=[], instructions="Recorded", model="model", created_at=123
        )

    client = SimpleNamespace(responses=SimpleNamespace(retrieve=retrieve))
    with pytest.raises(ValueError, match="could not retrieve agent 1"):
        recover_interfaces(tmp_path, client)
    recovered = json.loads((tmp_path / "interfaces_recovered.json").read_text())
    assert list(recovered) == ["0"]
    data = load_run(tmp_path)
    assert "recovered from stored" in data["interfaces"]["0"]["source"]
    assert "not recorded for this run" in data["interfaces"]["1"]["source"]
