import pytest

pytest.importorskip("agent.terminal_env_provider", reason="needs Hermes installed")

import hermes_cua_spaces as plugin  # noqa: E402


def test_provider_shape():
    p = plugin.CuaSpacesProvider()
    assert p.name == "cua" and p.is_remote and p.is_container
    assert "CUA_API_KEY" in p.strip_env_keys
    assert p.session_isolated_when_nonpersistent
    assert p.probe()[0] in ("ready", "needs_setup")
    assert all(len(row) == 3 for row in p.doctor_checks())


def test_guards_skipped_only_for_spaces_we_create():
    creating = plugin.CuaSpacesProvider(get_config=lambda k, default=None: default)
    assert creating.skip_container_guards is True
    named = plugin.CuaSpacesProvider(get_config=lambda k, default=None: "my-box" if k == "space" else default)
    assert named.skip_container_guards is False


def test_register_wires_provider():
    seen = []

    class Ctx:
        def register_terminal_environment_provider(self, p):
            seen.append(p)

    plugin.register(Ctx())
    assert len(seen) == 1 and seen[0].name == "cua"


def test_create_environment_passes_persistence(client):
    p = plugin.CuaSpacesProvider(get_config=lambda k, default=None: default, client=client)
    env = p.create_environment(cwd="/root", timeout=10, task_id="a", container_config={"container_persistent": False})
    env.cleanup()
    assert client.deleted == [client.space.id]
