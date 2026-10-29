"""JSON CLI for any agent that can launch a local command."""
import argparse
import json
import sys
import httpx
from .client import GatewayClient


def main(argv=None):
    parser = argparse.ArgumentParser(prog='sentinel', description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    start = commands.add_parser('start', help='Create a tracked task; keep its ID for subsequent actions')
    start.add_argument('task')
    action = commands.add_parser('action', help='Request a guarded action; never runs a local shell')
    action.add_argument('run_id')
    action.add_argument('tool')
    action.add_argument('--args', default='{}', help='JSON arguments, or - to read JSON from stdin')
    action.add_argument('--no-wait', action='store_true')
    status = commands.add_parser('status', help='Read one action result')
    status.add_argument('action_id', type=int)
    finish = commands.add_parser('finish', help='Close a task with no pending actions')
    finish.add_argument('run_id')
    commands.add_parser('mcp', help='Serve guarded tools over MCP stdio')
    args = parser.parse_args(argv)
    if args.command == 'mcp':
        from .mcp_server import main as serve
        serve()
        return 0
    client = None
    try:
        client = GatewayClient()
        if args.command == 'start':
            result = client.start(args.task)
        elif args.command == 'action':
            payload = json.loads(sys.stdin.read() if args.args == '-' else args.args)
            if not isinstance(payload, dict):
                raise ValueError('Arguments must be a JSON object')
            result = client.action(args.run_id, args.tool, payload, wait=not args.no_wait)
        elif args.command == 'status':
            result = client.status(args.action_id)
        else:
            result = client.finish(args.run_id)
        print(json.dumps(result))
        return 2 if result.get('status') in {'blocked', 'denied', 'failed'} else 0
    except httpx.HTTPStatusError as error:
        print(json.dumps({'error': 'Gateway rejected the request', 'http_status': error.response.status_code}), file=sys.stderr)
        return 1
    except (httpx.HTTPError, ValueError) as error:
        message = str(error) if isinstance(error, ValueError) else 'Gateway unavailable. Start SENTINEL before sending actions.'
        print(json.dumps({'error': message}), file=sys.stderr)
        return 1
    finally:
        if client:
            client.close()


if __name__ == '__main__':
    sys.exit(main())
