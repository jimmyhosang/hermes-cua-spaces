"""Installing the desktop stack into a Linux Space on request (`desktop: true`)."""

import sys

import pytest

pytest.importorskip("agent.terminal_env_provider", reason="needs Hermes installed")

import hermes_cua_spaces as plugin  # noqa: E402
from hermes_cua_spaces import desktop  # noqa: E402
from hermes_cua_spaces.config import load_settings  # noqa: E402

posix_only = pytest.mark.skipif(sys.platform.startswith("win"), reason="stand-in Space runs /bin/sh")


@pytest.fixture
def fake_stack(tmp_path, monkeypatch):
    """A harmless stand-in for desktop-stack.sh that records that it ran."""
    script = tmp_path / "stack.sh"
    done = tmp_path / "installed"
    script.write_text(f"#!/bin/bash\ntouch {done}\n")
    monkeypatch.setattr(desktop, "SCRIPT", script)
    monkeypatch.setattr(desktop, "REMOTE_PATH", str(tmp_path / "remote-stack.sh"))
    return done


def make_env(client, **settings):
    provider = plugin.CuaSpacesProvider(
        get_config=lambda k, default=None: settings.get(k, default), client=client
    )
    return provider.create_environment(cwd="~", timeout=10, task_id="t")


def test_desktop_setting_defaults_off_and_reads_config_and_env():
    assert load_settings(None, {}).desktop is False
    assert load_settings(lambda k, default=None: True if k == "desktop" else default, {}).desktop is True
    assert load_settings(None, {"HERMES_CUA_DESKTOP": "1"}).desktop is True
    assert load_settings(lambda k, default=None: True if k == "desktop" else default, {"HERMES_CUA_DESKTOP": "0"}).desktop is False


@posix_only
def test_default_installs_nothing(client, fake_stack):
    make_env(client)
    assert not fake_stack.exists()


@posix_only
def test_desktop_true_installs_once_when_the_stack_is_missing(client, fake_stack, monkeypatch):
    monkeypatch.setattr(desktop, "REQUIRED", ("definitely-not-installed-xyz",))
    make_env(client, desktop=True)
    assert fake_stack.exists()


@posix_only
def test_desktop_true_skips_a_space_that_has_the_stack(client, fake_stack, monkeypatch):
    monkeypatch.setattr(desktop, "REQUIRED", ("sh",))  # present everywhere
    make_env(client, desktop=True)
    assert not fake_stack.exists()


@posix_only
def test_a_failed_install_is_logged_and_the_terminal_still_works(client, tmp_path, monkeypatch, caplog):
    script = tmp_path / "fail.sh"
    script.write_text("#!/bin/bash\necho no network >&2\nexit 7\n")
    monkeypatch.setattr(desktop, "SCRIPT", script)
    monkeypatch.setattr(desktop, "REMOTE_PATH", str(tmp_path / "remote.sh"))
    monkeypatch.setattr(desktop, "REQUIRED", ("definitely-not-installed-xyz",))
    with caplog.at_level("WARNING"):
        env = make_env(client, desktop=True)
    assert any("Could not install the desktop stack" in r.getMessage() and "no network" in r.getMessage() for r in caplog.records)
    assert env.execute("echo still-works")["output"].strip() == "still-works"
    env.cleanup()


def test_the_shipped_script_is_present_and_idempotent_by_design():
    text = desktop.SCRIPT.read_text()
    assert text.startswith("#!/bin/bash") and "set -euo pipefail" in text
    assert "command -v agent-browser" in text and "cua-driver" in text and "tigervnc-standalone-server" in text
