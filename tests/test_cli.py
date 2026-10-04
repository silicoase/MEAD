import os
import sys

import pytest

from mad import cli


@pytest.mark.parametrize("shell_value", [None, "shell-test-value"])
def test_run_loads_local_dotenv_without_overriding_shell(
    tmp_path, monkeypatch, capsys, shell_value
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PYTHON_DOTENV_DISABLED", raising=False)
    if shell_value is not None:
        monkeypatch.setenv("OPENAI_API_KEY", shell_value)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=file-test-value\n")
    (tmp_path / "config.toml").write_text("agents = 1\n")
    observed = []

    async def fake_rollout(config, directory):
        observed.append(os.environ.get("OPENAI_API_KEY"))
        return {"agents": []}

    monkeypatch.setattr(cli, "run_rollout", fake_rollout)
    monkeypatch.setattr(sys, "argv", ["mad", "run", "config.toml"])
    cli.main()
    assert observed == [shell_value or "file-test-value"]
    assert "test-value" not in capsys.readouterr().out
