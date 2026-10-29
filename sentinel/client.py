"""Model-independent gateway client; never executes tools locally."""
import os
import time
import httpx
from dotenv import dotenv_values
from .paths import DATA


class GatewayClient:
    def __init__(self, token=None, transport=None):
        values = dotenv_values(DATA / '.env')
        token = token or os.getenv('SENTINEL_AGENT_TOKEN') or values.get('SENTINEL_AGENT_TOKEN')
        if not token:
            raise ValueError('Configure SENTINEL_AGENT_TOKEN in the environment or SENTINEL_HOME/.env')
        self.http = httpx.Client(base_url='http://127.0.0.1:8000',
            headers={'Authorization': 'Bearer ' + token}, timeout=10,
            transport=transport, trust_env=False)

    def close(self):
        self.http.close()

    def request(self, method, path, body=None):
        response = self.http.request(method, path, json=body)
        response.raise_for_status()
        return response.json()

    def start(self, task):
        return self.request('POST', '/api/runs', {'task': task})

    def action(self, run_id, tool, args, note='', wait=True):
        result = self.request('POST', '/api/actions',
            {'run_id': run_id, 'tool': tool, 'args': args, 'agent_note': note})
        deadline = time.monotonic() + 75
        while wait and result['status'] in {'checking', 'executing', 'waiting_for_human'}:
            if time.monotonic() >= deadline:
                # A timeout is NOT cancellation: return the ID for status lookup.
                return {**result, 'client_wait_expired': True}
            time.sleep(.3)
            result = self.status(result['action_id'])
        return result

    def status(self, action_id):
        return self.request('GET', f'/api/actions/{int(action_id)}')

    def finish(self, run_id):
        return self.request('POST', f'/api/runs/{run_id}/finish', {})
