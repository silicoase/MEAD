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


def test_released_reasoning_text_is_counted_but_encrypted_content_is_not():
    events = [{"kind": "model_response", "agent": 0, "sequence": 1, "elapsed_seconds": 1,
               "response_id": "reasoning-text", "output": [{
                   "type": "reasoning", "summary": [],
                   "content": [{"type": "reasoning_text", "text": "Other agents may share results."}],
                   "encrypted_content": "Other agents abcd1234 opaque-signature",
               }]}]
    _, mentions = module.analyze_events(events, {}, {0: "own-id", 1: "abcd1234"})
    assert len(mentions) == 1
    assert len(mentions[0]["excerpts"]) == 1
    assert mentions[0]["excerpts"][0]["source"] == "reasoning_text"
    assert mentions[0]["excerpts"][0]["tag"] == "explicit_peer_language"


def test_discovery_is_first_listing_per_agent_and_type_with_either_as_union():
    ids = {0: "own", 1: "peer"}
    def listing(agent, path, entries, seq):
        return [
            {"kind": "tool_called", "tool": "list_files", "agent": agent,
             "arguments": {"path": path}, "sequence": seq},
            {"kind": "tool_result", "tool": "list_files", "agent": agent,
             "result": entries, "sequence": seq + 1, "elapsed_seconds": seq},
        ]
    own = {"name": "own.md", "author_id": "own", "directory": False}
    peer = {"name": "peer.md", "author_id": "peer", "directory": False}
    events = []
    for agent, path, entries, seq in [
        (0, "/lab/notes", [], 1),
        (0, "/lab/notes", [own], 3),
        (0, "/lab/notes", [{**peer, "directory": True}], 5),
        (0, "/workspace", [peer], 7),
        (0, "/lab/notes", {"error": "denied"}, 9),
        (0, "/lab/notes", [peer], 11),
        (0, "/lab/notes", [peer], 13),
        (0, "/lab/runs", [{**peer, "name": "result.json"}], 15),
        (1, "/lab/runs", [{**own, "name": "own-result.json"}], 17),
        (1, "/lab/notes", [own], 19),
    ]:
        events.extend(listing(agent, path, entries, seq))
    discoveries = module.analyze_discoveries(events, ids)
    assert [e["sequence"] for e in discoveries["discovered_peer_note"]] == [12, 20]
    assert [e["sequence"] for e in discoveries["discovered_peer_result"]] == [16, 18]
    assert [e["sequence"] for e in discoveries["discovered_either"]] == [12, 18]
    assert discoveries["discovered_peer_result"][0]["path"] == "/lab/runs/result.json"


def test_unknown_authors_and_cancelled_listings_are_not_discoveries():
    events = [
        {"kind": "tool_called", "tool": "list_files", "agent": 0,
         "arguments": {"path": "/lab/notes"}, "sequence": 1},
        {"kind": "tool_result", "agent": 0, "sequence": 2, "elapsed_seconds": 1,
         "result": [{"name": "unknown", "author_id": "unknown", "directory": False}]},
        {"kind": "tool_called", "tool": "list_files", "agent": 0,
         "arguments": {"path": "/lab/notes"}, "sequence": 3},
        {"kind": "tool_cancelled", "agent": 0},
        {"kind": "tool_result", "agent": 0, "sequence": 4, "elapsed_seconds": 2,
         "result": [{"name": "peer", "author_id": "peer", "directory": False}]},
    ]
    assert all(not events for events in module.analyze_discoveries(events, {0: "own", 1: "peer"}).values())
