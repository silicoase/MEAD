"""Docker execution and trusted publication of flat lab artifacts.

Agent mounts are read-only for lab artifacts. Only this host-side backend may
publish notes and runs; private workspace operations execute as the agent UID.
"""

import asyncio
import inspect
import json
import uuid
from pathlib import Path, PurePosixPath

from .config import RolloutConfig
from .notes import format_note
from .recording import timestamp

FILE_WORKER = r"""
import json, os
from pathlib import Path
request = json.loads(input())
path = Path(request['path']).resolve()
roots = [Path('/workspace'), Path('/lab/runs'), Path('/lab/notes')]
if not any(path == root or root in path.parents for root in roots):
    raise ValueError('path outside available directories')
operation = request['operation']
if operation == 'list':
    result = [dict(name=p.name, directory=p.is_dir(), author_id=p.stat().st_uid)
              for p in sorted(path.iterdir())][:1000]
elif operation == 'read':
    with path.open() as f:
        result = f.read(65537)
    if len(result) > 65536:
        raise ValueError('file exceeds read limit of 65536 characters')
elif operation in ('write', 'append'):
    if Path('/workspace') not in path.parents:
        raise ValueError('direct writes require /workspace')
    path.parent.mkdir(parents=True, exist_ok=True)
    content = request['content']
    if operation == 'append':
        content = (path.read_text() if path.exists() else '') + content
        if len(content) > 65536:
            raise ValueError('file exceeds 65536 characters')
    path.write_text(content)
    result = {'written': str(path)}
elif operation == 'search':
    result = []
    for p in sorted(path.rglob('*')):
        if p.is_symlink() or not p.is_file():
            continue
        try:
            with p.open() as f:
                content = f.read(65536)
            if request['query'] in content:
                result.append(str(p))
        except (OSError, UnicodeError):
            pass
        if len(result) >= 100:
            break
else:
    raise ValueError('unknown operation')
print(json.dumps(result))
"""


PYTHON_WORKER = r"""
import json, os, signal, subprocess, tempfile
request = json.loads(input())
# Store output in a bounded file instead of buffering arbitrary output in memory.
with tempfile.TemporaryFile() as output:
    process = subprocess.Popen(['python', '-c', request['code']], stdout=output,
                               stderr=subprocess.STDOUT, start_new_session=True)
    timed_out = False
    try:
        process.wait(timeout=request['timeout'])
    except subprocess.TimeoutExpired:
        timed_out = True
    finally:
        # Kill descendants too, including children left after a successful parent.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
    output.seek(0)
    data = output.read(65537)
    print(json.dumps(dict(exit_code=process.returncode, timed_out=timed_out,
                          output=data[:65536].decode('utf-8', errors='replace'),
                          truncated=len(data) > 65536)))
"""


async def docker(*args: str, stdin: bytes | None = None, timeout: float = 60) -> bytes:
    process = await asyncio.create_subprocess_exec(
        "docker",
        *args,
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(stdin), timeout)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise RuntimeError(stderr.decode(errors="replace").strip() or "Docker command failed")
    return stdout


class DockerEnvironment:
    def __init__(self, config: RolloutConfig):
        self.config = config
        self.author_ids = [uuid.uuid4().hex for _ in range(config.agents)]
        self.run_owners: dict[str, int] = {}
        self.token = uuid.uuid4().hex
        self.volume = f"mad-{self.token}"
        self.helper = f"mad-store-{self.token}"
        self.containers: dict[int, str] = {}
        self.created_volume = False
        self.created_helper = False
        self.note_owners: dict[str, int] = {}
        self.notes_lock = asyncio.Lock()

    def notes_dir(self, agent: int) -> str:
        return "notes/all" if self.config.notes_visibility == "all" else f"notes/{agent}"

    def runs_dir(self, agent: int) -> str:
        return "runs/all" if self.config.runs_visibility == "all" else f"runs/{agent}"

    async def trusted_python(self, code: str, payload: dict | None = None):
        return await docker(
            "exec",
            "-i",
            self.helper,
            "python",
            "-c",
            code,
            stdin=json.dumps(payload or {}).encode(),
        )

    def agent_instructions(self, instructions: str, agent: int) -> str:
        return f"Your author ID is `{self.author_ids[agent]}`.\n\n{instructions}"

    async def start(self, instructions: str | list[str]):
        if isinstance(instructions, str):
            instructions = [
                self.agent_instructions(instructions, i) for i in range(self.config.agents)
            ]
        await docker("image", "inspect", self.config.environment.image)
        await docker("volume", "create", "--label", "mad.managed=true", self.volume)
        self.created_volume = True
        await docker(
            "run",
            "-d",
            "--name",
            self.helper,
            "--label",
            "mad.managed=true",
            "--network",
            "none",
            "--mount",
            f"type=volume,src={self.volume},dst=/state",
            self.config.environment.image,
        )
        self.created_helper = True
        initial = {}
        for name, source in self.config.task.initial_files.items():
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or name == "task.md":
                raise ValueError(
                    "initial files must have relative workspace paths other than task.md"
                )
            initial[name] = source.read_text()
        code = """
import json, os
from pathlib import Path
data = json.loads(input())
for entry in data['directories']:
    p = Path('/state') / entry['path']
    p.mkdir(parents=True, exist_ok=True)
    os.chown(p, entry['uid'], entry['uid'])
    p.chmod(0o700 if entry['path'].startswith('work/') else 0o755)
for i in range(data['agents']):
    for name, content in {'task.md': data['instructions'][i], **data['initial']}.items():
        p = Path('/state/work') / str(i) / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        os.chown(p, 10000 + i, 10000 + i)
        p.chmod(0o644)
    for p in (Path('/state/work') / str(i)).rglob('*'):
        if p.is_dir():
            os.chown(p, 10000 + i, 10000 + i)
            p.chmod(0o700)
"""
        directories = []
        for i in range(self.config.agents):
            directories.extend(
                [
                    dict(path=f"work/{i}", uid=10000 + i),
                    dict(path=self.notes_dir(i), uid=0),
                    dict(path=self.runs_dir(i), uid=0),
                ]
            )
        await self.trusted_python(
            code,
            dict(
                directories=directories,
                agents=self.config.agents,
                instructions=instructions,
                initial=initial,
            ),
        )
        for i in range(self.config.agents):
            name = f"mad-exec-{self.token}-{i}"
            mounts = [
                ("work/" + str(i), "/workspace", False),
                (self.notes_dir(i), "/lab/notes", True),
                (self.runs_dir(i), "/lab/runs", True),
            ]
            args = [
                "run",
                "-d",
                "--name",
                name,
                "--label",
                "mad.managed=true",
                "--hostname",
                "compute",
                "--user",
                f"{10000 + i}:{10000 + i}",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--memory",
                self.config.environment.memory,
                "--cpus",
                str(self.config.environment.cpus),
                "--pids-limit",
                str(self.config.environment.pids_limit),
                "--ulimit",
                "fsize=16777216:16777216",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=64m,mode=1777",
            ]
            for source, target, readonly in mounts:
                args += [
                    "--mount",
                    f"type=volume,src={self.volume},dst={target},"
                    f"volume-subpath={source}" + (",readonly" if readonly else ""),
                ]
            args += [self.config.environment.image]
            await docker(*args)
            self.containers[i] = name

    async def execute(self, agent: int, code: str, payload: dict, timeout: float = 30):
        result = await docker(
            "exec",
            "-i",
            self.containers[agent],
            "python",
            "-c",
            code,
            stdin=json.dumps(payload).encode(),
            timeout=timeout,
        )
        return json.loads(result)

    async def file(self, agent: int, operation: str, path: str, **kwargs):
        p = PurePosixPath(path)
        if not p.is_absolute() or ".." in p.parts:
            raise ValueError("use absolute paths without parent traversal")
        if operation in ("write", "append") and p.parent == PurePosixPath("/lab/notes"):
            content = kwargs["content"]
            if len(content) > 65536:
                raise ValueError("note exceeds 65536 characters")
            key = f"{self.notes_dir(agent)}/{p.name}"
            async with self.notes_lock:
                owner = self.note_owners.get(key)
                if owner is not None and owner != agent:
                    raise PermissionError("cannot modify a note you did not create")
                # Reserve ownership before awaiting Docker. Cancellation must not
                # leave a published file unclaimed and editable by another caller.
                self.note_owners[key] = agent
                await self.publish_file(
                    key,
                    content,
                    10000 + agent,
                    append=operation == "append",
                    header=(
                        f"Author: {self.author_ids[agent]}\n\n"
                        if self.config.note_author_headers
                        else ""
                    ),
                    note_timestamps=self.config.note_timestamps,
                )
            return {"written": path}
        result = await self.execute(
            agent, FILE_WORKER, dict(operation=operation, path=path, **kwargs)
        )
        if operation == "list":
            for entry in result:
                if p == PurePosixPath("/lab/runs"):
                    owner = self.run_owners.get(f"{self.runs_dir(agent)}/{entry['name']}")
                else:
                    uid = entry["author_id"]
                    owner = uid - 10000 if 10000 <= uid < 10000 + self.config.agents else None
                entry["author_id"] = self.author_ids[owner] if owner is not None else None
        return result

    async def publish_file(
        self,
        relative: str,
        content: str,
        uid: int = 0,
        *,
        append: bool = False,
        header: str = "",
        note_timestamps: bool = False,
    ):
        # Host-controlled paths only, never pass arbitrary agent paths here.
        await self.trusted_python(
            inspect.getsource(format_note)
            + """
import json, os, tempfile
from pathlib import Path
data = json.loads(input())
p = Path('/state') / data['relative']
content = data['content']
existing = p.read_text() if p.exists() else ''
if data['header'] or data['note_timestamps']:
    content = format_note(content, existing, author=data['header'].removeprefix('Author: ').strip(),
                          timestamps=data['note_timestamps'], append=data['append'], now=data['now'])
elif data['append']:
    content = existing + content
    if len(content) > 65536:
        raise ValueError('note exceeds 65536 characters')
staging = Path('/state/staging')
staging.mkdir(exist_ok=True, mode=0o700)
fd, name = tempfile.mkstemp(dir=staging)
try:
    with os.fdopen(fd, 'w') as f:
        f.write(content)
    os.chown(name, data['uid'], data['uid'])
    os.chmod(name, 0o644)
    os.replace(name, p)
finally:
    if os.path.exists(name):
        os.unlink(name)
""",
            dict(
                relative=relative,
                content=content,
                uid=uid,
                append=append,
                header=header,
                note_timestamps=note_timestamps,
                now=timestamp(),
            ),
        )

    async def publish_run(self, agent: int, record: dict):
        self.run_owners[f"{self.runs_dir(agent)}/{record['run_id']}.json"] = agent
        await self.publish_file(
            f"{self.runs_dir(agent)}/{record['run_id']}.json", json.dumps(record, indent=2)
        )

    async def python(self, agent: int, code: str):
        timeout = self.config.environment.python_timeout_seconds
        return await self.execute(
            agent, PYTHON_WORKER, dict(code=code, timeout=timeout), timeout + 5
        )

    async def stop_agent(self, agent: int):
        name = self.containers.get(agent)
        if name:
            await docker("stop", "-t", "0", name)

    async def snapshot(self, directory: Path):
        # Keep a tar archive rather than extracting potentially agent-created symlinks.
        process = await asyncio.create_subprocess_exec(
            "docker",
            "exec",
            self.helper,
            "tar",
            "-cf",
            "-",
            "-C",
            "/state",
            ".",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            with (directory / "artifacts.tar").open("wb") as output:
                while chunk := await process.stdout.read(65536):
                    output.write(chunk)
            stderr = await process.stderr.read()
            await process.wait()
            if process.returncode:
                raise RuntimeError(stderr.decode())
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        (directory / "note_ownership.json").write_text(json.dumps(self.note_owners, indent=2))

    async def close(self):
        errors = []
        for name in [*self.containers.values(), *([self.helper] if self.created_helper else [])]:
            try:
                await docker("rm", "-f", name)
            except RuntimeError as error:
                errors.append(str(error))
        if self.created_volume:
            try:
                await docker("volume", "rm", self.volume)
            except RuntimeError as error:
                errors.append(str(error))
        if errors:
            raise RuntimeError("; ".join(errors))
