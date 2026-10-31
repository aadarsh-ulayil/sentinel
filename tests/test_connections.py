from types import SimpleNamespace
import pytest
from sentinel import connections


@pytest.fixture
def setup(tmp_path, monkeypatch):
    data = tmp_path / 'folder with spaces'
    python = data / '.venv' / ('Scripts/python.exe' if connections.sys.platform == 'win32' else 'bin/python')
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setattr(connections, 'find_cli', lambda host: '/tools/' + host)
    monkeypatch.setattr(connections, 'existing_config', lambda host: None)
    return data


@pytest.mark.parametrize('host', ['codex', 'claude'])
def test_setup_passes_paths_as_arguments_and_no_secrets(setup, monkeypatch, host):
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(connections.subprocess, 'run', run)
    assert 'saved' in connections.connect(host, setup)
    args, kwargs = calls[1]
    assert 'SENTINEL_HOME=' + str(setup) in args
    assert args[-3:] == [str(setup / '.venv' / ('Scripts/python.exe' if connections.sys.platform == 'win32' else 'bin/python')), '-m', 'sentinel.mcp_server']
    assert not kwargs.get('shell')
    assert '--scope' in args if host == 'claude' else '--scope' not in args


def test_existing_connection_is_preserved(setup, monkeypatch):
    monkeypatch.setattr(connections, 'existing_config', lambda host: {'command': 'another-helper'})
    with pytest.raises(ValueError, match='left unchanged'):
        connections.connect('codex', setup)


def test_repeated_setup_is_noop(setup, monkeypatch):
    monkeypatch.setattr(connections, 'existing_config', lambda host: connections.bridge_config(setup))
    monkeypatch.setattr(connections.subprocess, 'run', lambda *a, **k: pytest.fail('must not write'))
    assert 'Already configured' in connections.connect('codex', setup)


def test_bad_helper_does_not_change_host(setup, monkeypatch):
    calls = []
    def run(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr(connections.subprocess, 'run', run)
    with pytest.raises(ValueError, match='dependencies'):
        connections.connect('claude', setup)
    assert len(calls) == 1
