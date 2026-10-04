import json
import os

import pytest

from mad.config import RolloutConfig
from mad.environment import DockerEnvironment, docker
from mad.rollout import run_rollout

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        os.environ.get("MAD_DOCKER_TESTS") != "1", reason="set MAD_DOCKER_TESTS=1 to use Docker"
    ),
]


@pytest.mark.parametrize(
    "runs_visibility,notes_visibility",
    [("all", "all"), ("own", "own"), ("own", "all"), ("all", "own")],
)
async def test_visibility_and_note_ownership(runs_visibility, notes_visibility):
    config = RolloutConfig(
        agents=2,
        runs_visibility=runs_visibility,
        notes_visibility=notes_visibility,
        note_author_headers=False,
    )
    environment = DockerEnvironment(config)
    try:
        await environment.start("Optimize the objective.")
        await environment.file(0, "write", "/lab/notes/calibration.md", content="first")
        await environment.publish_run(0, {"run_id": "measurement", "observed": 1})
        names = await environment.file(1, "list", "/lab/notes")
        assert bool(names) == (notes_visibility == "all")
        runs = await environment.file(1, "list", "/lab/runs")
        assert bool(runs) == (runs_visibility == "all")
        # Ownership check on trusted tool, independent of raw-Python permissions.
        if notes_visibility == "all":
            with pytest.raises(PermissionError):
                await environment.file(1, "write", "/lab/notes/calibration.md", content="overwrite")
        else:
            await environment.file(
                1, "write", "/lab/notes/calibration.md", content="private second"
            )
        await environment.file(0, "write", "/lab/notes/calibration.md", content="revised")
        assert await environment.file(0, "read", "/lab/notes/calibration.md") == "revised"
        assert await environment.file(0, "search", "/lab/notes", query="revised") == [
            "/lab/notes/calibration.md"
        ]
    finally:
        await environment.close()


async def test_python_isolation_and_read_only_lab_mounts():
    environment = DockerEnvironment(
        RolloutConfig(agents=2, environment={"python_timeout_seconds": 0.5})
    )
    try:
        await environment.start("Optimize the objective.")
        await environment.file(0, "write", "/lab/notes/calibration.md", content="revised")
        original = await environment.file(0, "read", "/lab/notes/calibration.md")
        await environment.publish_run(0, {"run_id": "measurement", "observed": 1})
        await environment.file(0, "write", "/workspace/new", content="replacement")
        # Read-only mount also blocks chmod, deletion, and replacement through Python.
        for code in (
            "from pathlib import Path; Path('/lab/notes/calibration.md').write_text('bad')",
            "from pathlib import Path; Path('/lab/notes/calibration.md').unlink()",
            "import os; os.chmod('/lab/notes/calibration.md', 0o666)",
            "from pathlib import Path; Path('/lab/runs/measurement.json').write_text('bad')",
            "import os; os.rename('/workspace/new', '/lab/notes/calibration.md')",
        ):
            assert (await environment.python(0, code))["exit_code"] != 0
        assert await environment.file(0, "read", "/lab/notes/calibration.md") == original
        with pytest.raises(ValueError):
            await environment.file(1, "write", "/lab/notes/../runs/measurement.json", content="bad")
        await environment.file(0, "write", "/workspace/private.txt", content="private")
        result = await environment.python(
            1,
            """
import json, os
from pathlib import Path
uids = []
for path in Path('/proc').iterdir():
    if path.name.isdigit():
        try:
            uids.append(path.stat().st_uid)
        except FileNotFoundError:
            pass
print(json.dumps({'uids': uids, 'uid': os.getuid(),
                  'private': Path('/workspace/private.txt').exists(),
                  'key': 'OPENAI_API_KEY' in os.environ,
                  'docker_socket': Path('/var/run/docker.sock').exists()}))
""",
        )
        state = json.loads(result["output"])
        assert state["uid"] != 0
        assert set(state["uids"]) == {state["uid"]}
        assert not state["private"] and not state["key"] and not state["docker_socket"]
        network = await environment.python(1, "print(open('/proc/net/dev').read())")
        assert "eth0" not in network["output"] and "lo:" in network["output"]
        assert (await environment.python(1, "import time; time.sleep(5)"))["timed_out"]
    finally:
        await environment.close()


async def test_scripted_rollout_logs_evaluation_archives_and_cleans_up(tmp_path, monkeypatch):
    from mad import rollout

    environments = []

    def create_environment(config):
        environment = DockerEnvironment(config)
        environments.append(environment)
        return environment

    monkeypatch.setattr(rollout, "DockerEnvironment", create_environment)
    config = RolloutConfig(
        agents=2, experiment_budget=2, harness={"kind": "scripted"}, max_turns=30
    )
    directory = tmp_path / "rollout"
    result = await run_rollout(config, directory)
    assert all(a["reason"] == "submitted" for a in result["agents"])
    assert all(a["experiments_used"] == 2 for a in result["agents"])
    assert all(a["true_objective"] is not None for a in result["agents"])
    assert (directory / "artifacts.tar").stat().st_size > 0
    environment = environments[0]
    container_names = (await docker("ps", "-a", "--format", "{{.Names}}")).decode().splitlines()
    assert set([*environment.containers.values(), environment.helper]).isdisjoint(container_names)
    volumes = (await docker("volume", "ls", "--format", "{{.Name}}")).decode().splitlines()
    assert environment.volume not in volumes
    events = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]
    assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
    assert sum(e["kind"] == "submission" for e in events) == 2
    identities = json.loads((directory / "identities.json").read_text())
    authors = [item["author_id"] for item in identities]
    assert len(set(authors)) == 2
    for event in events:
        if event["kind"] == "agent_started":
            assert authors[event["agent"]] in event["instructions"]
            assert authors[1 - event["agent"]] not in event["instructions"]
        if event["kind"] == "experiment_completed":
            assert event["record"]["author_id"] == authors[event["agent"]]
    records = [event["record"] for event in events if event["kind"] == "experiment_completed"]
    assert len({record["run_id"] for record in records}) == len(records)
    assert {record["run_id"] for record in records} == {
        record["run_id"] for agent_records in result["experiment_records"] for record in agent_records
    }
    import tarfile

    with tarfile.open(directory / "artifacts.tar") as archive:
        for i, author in enumerate(authors):
            task = archive.extractfile(f"./work/{i}/task.md").read().decode()
            assert author in task
            note = archive.extractfile(f"./notes/all/sweep-{author}.md").read().decode()
            assert note.startswith(f"Author: {author}\n\n")
    from mad.review import load_run

    assert all(flag["agent"] != flag["peer"] for flag in load_run(directory)["flags"])


@pytest.mark.parametrize("limit,reason", [("turn", "turn_limit"), ("time", "time_limit")])
async def test_limits_preserve_no_submission(tmp_path, limit, reason):
    config = RolloutConfig(
        agents=1,
        experiment_budget=2,
        harness={"kind": "scripted"},
        max_turns=1 if limit == "turn" else 30,
        timeout_seconds=0.01 if limit == "time" else 60,
    )
    result = await run_rollout(config, tmp_path / limit)
    report = result["agents"][0]
    assert report["reason"] == reason
    assert report["parameters"] is None
    assert report["true_objective"] is None
    assert (tmp_path / limit / "artifacts.tar").exists()


@pytest.mark.docker
@pytest.mark.parametrize("headers", [False, True])
async def test_append_preserves_content_and_enforces_ownership(headers):
    environment = DockerEnvironment(RolloutConfig(agents=2, note_author_headers=headers))
    try:
        await environment.start("Keep a notebook.")
        path = "/lab/notes/notebook.md"
        prefix = f"Author: {environment.author_ids[0]}\n\n" if headers else ""
        await environment.file(0, "append", path, content="first\n")
        await environment.file(0, "append", path, content="second\n")
        assert await environment.file(0, "read", path) == prefix + "first\nsecond\n"
        listing = await environment.file(1, "list", "/lab/notes")
        assert listing[0]["author_id"] == environment.author_ids[0]
        await environment.file(0, "write", path, content=prefix + "replacement")
        assert await environment.file(0, "read", path) == prefix + "replacement"
        await environment.file(0, "write", path, content="first\nsecond\n")
        with pytest.raises(PermissionError):
            await environment.file(1, "append", path, content="peer")
        with pytest.raises(RuntimeError):
            await environment.file(0, "append", path, content="x" * 65536)
        assert await environment.file(0, "read", path) == prefix + "first\nsecond\n"
        await environment.file(0, "append", "/workspace/log.txt", content="a")
        await environment.file(0, "append", "/workspace/log.txt", content="b")
        assert await environment.file(0, "read", "/workspace/log.txt") == "ab"
        with pytest.raises(RuntimeError):
            await environment.file(0, "append", "/lab/runs/new.json", content="bad")
    finally:
        await environment.close()


async def test_timestamped_notes_preserve_metadata():
    environment = DockerEnvironment(RolloutConfig(agents=1, note_timestamps=True))
    try:
        await environment.start("Keep notes.")
        path = "/lab/notes/log.md"
        await environment.file(0, "write", path, content="first")
        original = await environment.file(0, "read", path)
        created = next(line for line in original.splitlines() if line.startswith("Created: "))
        await environment.file(0, "append", path, content="second")
        appended = await environment.file(0, "read", path)
        assert created in appended and "Entry: " in appended
        assert "first" in appended and "second" in appended
        await environment.file(0, "write", path, content=appended)
        revised = await environment.file(0, "read", path)
        assert revised.count("Author: ") == 1 and created in revised
        await environment.file(0, "write", "/workspace/plain.txt", content="plain")
        assert await environment.file(0, "read", "/workspace/plain.txt") == "plain"
    finally:
        await environment.close()
