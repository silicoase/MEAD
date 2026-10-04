import asyncio

import pytest

from mad.config import RolloutConfig
from mad.environment import DockerEnvironment


async def test_cancelled_publication_keeps_creator_claim(monkeypatch):
    environment = DockerEnvironment(RolloutConfig(agents=2))
    publishing = asyncio.Event()

    async def interrupted_publication(*args, **kwargs):
        publishing.set()
        await asyncio.sleep(60)

    monkeypatch.setattr(environment, "publish_file", interrupted_publication)
    call = asyncio.create_task(
        environment.file(0, "write", "/lab/notes/calibration.md", content="first")
    )
    await publishing.wait()
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    with pytest.raises(PermissionError):
        await environment.file(1, "write", "/lab/notes/calibration.md", content="second")


def test_author_ids_are_opaque_unique_and_fresh():
    from uuid import UUID

    first = DockerEnvironment(RolloutConfig(agents=100))
    second = DockerEnvironment(RolloutConfig(agents=100))
    assert len(set(first.author_ids)) == 100
    assert set(first.author_ids).isdisjoint(second.author_ids)
    assert all(UUID(value).version == 4 for value in first.author_ids)
