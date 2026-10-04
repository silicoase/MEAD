import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/summarize_collaboration.py"
spec = importlib.util.spec_from_file_location("collaboration_summary", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_peer_reads_require_success_and_another_owner():
    events = [{"kind": "experiment_completed", "agent": 1,
               "record": {"run_id": "peer-measurement"}}]
    for i, (tool, path, result) in enumerate([
        ("read_file", "/lab/notes/peer.txt", "peer content"),
        ("read_file", "/lab/notes/own.txt", "own content"),
        ("read_file", "/lab/notes/peer.txt", {"error": "missing"}),
        ("list_files", "/lab/notes", []),
        ("read_file", "/lab/runs/peer-measurement.json", "measurement"),
        ("read_file", "/lab/notes/peer.txt", "peer content again"),
        ("read_file", "/workspace/task.md", "Other agents are present."),
    ]):
        events.extend([
            {"kind": "tool_called", "agent": 0, "sequence": i * 2,
             "tool": tool, "arguments": {"path": path}},
            {"kind": "tool_result", "agent": 0, "sequence": i * 2 + 1,
             "elapsed_seconds": i, "tool": tool, "result": result},
        ])
    reads, mentions = module.analyze_events(
        events, {"notes/all/peer.txt": 1, "notes/all/own.txt": 0}, {0: "own-id", 1: "peer-id"}
    )
    assert [r["artifact"] for r in reads] == ["note", "measurement", "note"]
    assert all(r["peer"] == 1 for r in reads)
    assert not mentions


def test_mentions_use_authored_text_and_count_responses_once():
    response = {
        "kind": "model_response", "agent": 0, "sequence": 3, "elapsed_seconds": 4,
        "response_id": "one-response", "output": [
            {"type": "reasoning", "summary": [{"text": "Other agents may have useful data."}],
             "encrypted_content": "ignored"},
            {"type": "message", "content": [{"type": "output_text", "text": "I can learn from peers."}]},
        ],
    }
    events = [
        {"kind": "model_request", "agent": 0, "system_prompt": "Other agents are present."},
        response, response,
        {"kind": "model_response", "agent": 0, "sequence": 4, "elapsed_seconds": 5,
         "output": [{"type": "function_call", "name": "read_file",
                     "arguments": '{"path":"/lab/notes/peer-id.txt"}'}]},
        {"kind": "model_response", "agent": 0, "sequence": 5, "elapsed_seconds": 6,
         "output": [{"type": "function_call", "name": "append_file",
                     "arguments": '{"path":"/lab/notes/own.txt","content":"Using abcd1234 results."}'}]},
    ]
    reads, mentions = module.analyze_events(events, {}, {0: "own-id", 1: "abcd1234"})
    assert not reads
    assert len(mentions) == 2
    assert len(mentions[0]["excerpts"]) == 2
    assert mentions[1]["excerpts"][0]["tag"] == "peer_id"


def test_specific_id_is_tagged_even_alongside_generic_peer_language():
    events = [{"kind": "model_response", "agent": 0, "sequence": 1, "elapsed_seconds": 2,
               "output": [{"type": "message", "content": [
                   {"type": "output_text", "text": "Other agents, especially abcd1234, found useful results. own1234 is my ID."}
               ]}]}]
    _, mentions = module.analyze_events(events, {}, {0: "own1234", 1: "abcd1234"})
    assert len(mentions) == 1
    assert [e["tag"] for e in mentions[0]["excerpts"]] == ["explicit_peer_language", "peer_id"]


def test_specific_references_allow_unique_prefixes_but_not_own_or_ambiguous_ids():
    ids = {0: "abcd0000", 1: "415cffff", 2: "0767ffff", 3: "abcd1111"}
    assert len(list(module.specific_references("agent415c and agent0767", 0, ids))) == 2
    assert len(list(module.specific_references("415c's results", 0, ids))) == 1
    assert not list(module.specific_references("abcd and abcd0000; score 0.0767", 0, ids))
