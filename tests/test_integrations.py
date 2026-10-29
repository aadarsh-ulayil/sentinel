import json
import httpx
from sentinel.client import GatewayClient


def test_agent_client_uses_restricted_token_and_never_redirects():
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(202, json={'action_id': 12, 'status': 'waiting_for_human'})
    client = GatewayClient(token='agent-only', transport=httpx.MockTransport(handler))
    try:
        result = client.action('test', 'spend_money', {'amount_inr': 300, 'payee': 'Demo'}, wait=False)
        assert result['status'] == 'waiting_for_human'
        assert seen[0].headers['authorization'] == 'Bearer agent-only'
        assert json.loads(seen[0].content)['run_id'] == 'test'
        assert not client.http.follow_redirects
    finally:
        client.close()


def test_blocked_result_is_returned_without_retry():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(202, json={'action_id': 3, 'status': 'blocked', 'reason': 'Not allowed'})
    client = GatewayClient(token='agent-only', transport=httpx.MockTransport(handler))
    try:
        assert client.action('test', 'run_command', {'command': 'rm -rf /'})['status'] == 'blocked'
        assert len(requests) == 1
    finally:
        client.close()


def test_mcp_exposes_no_operator_tools():
    import asyncio
    import pytest
    pytest.importorskip('mcp')
    from sentinel.mcp_server import mcp
    names = {tool.name for tool in asyncio.run(mcp.list_tools())}
    assert names == {'start_task', 'guarded_action', 'action_status', 'finish_task'}
