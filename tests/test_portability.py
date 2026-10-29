import pytest
from sentinel.instance import gateway_lock
from sentinel.models import Action
from sentinel.tools import execute


def test_gateway_lock_excludes_second_owner_and_releases(tmp_path):
    path = tmp_path / 'gateway.lock'
    with gateway_lock(path):
        with pytest.raises(RuntimeError):
            with gateway_lock(path):
                pass
    with gateway_lock(path):
        pass


def test_portable_commands_are_bounded(tmp_path):
    (tmp_path / 'example.txt').write_text('example')
    for name in ('pwd', 'ls', 'whoami'):
        result = execute(Action(run_id='test', tool='run_command', args={'command': name}), tmp_path, tmp_path, [])
        assert result['stdout'].strip()
    with pytest.raises(ValueError):
        execute(Action(run_id='test', tool='run_command', args={'command': 'ls; whoami'}), tmp_path, tmp_path, [])


@pytest.mark.parametrize('name', ['NUL', 'con.txt', 'COM1', 'file:stream', 'C:\\outside', 'name.'])
def test_windows_special_paths_fail_closed(tmp_path, name):
    from sentinel.policy import safe_path
    with pytest.raises(ValueError):
        safe_path(tmp_path, name)
