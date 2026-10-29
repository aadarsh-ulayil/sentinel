from pathlib import Path
from scripts.background import manifests, LABELS


def test_login_services_keep_secrets_out_of_launch_arguments(tmp_path):
    jobs = manifests(tmp_path, tmp_path / 'SENTINEL.app')
    gateway = jobs[LABELS[0]]
    companion = jobs[LABELS[1]]
    assert gateway['ProgramArguments'] == [str(tmp_path / '.venv/bin/python'), '-m', 'sentinel']
    assert gateway['RunAtLoad'] and gateway['KeepAlive']
    assert companion['KeepAlive'] == {'SuccessfulExit': False}
    assert all('EnvironmentVariables' not in job for job in jobs.values())
    assert all('token' not in ' '.join(job['ProgramArguments']).lower() for job in jobs.values())
    assert all(Path(job['StandardErrorPath']).is_relative_to(tmp_path / '.runtime') for job in jobs.values())
