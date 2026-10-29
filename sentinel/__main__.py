"""One loopback gateway process, protected against duplicate startup."""
import uvicorn
from .app import BASE, create_app
from .instance import gateway_lock


def main():
    try:
        with gateway_lock(BASE / '.runtime' / 'gateway.lock'):
            uvicorn.run(create_app(), host='127.0.0.1', port=8000, workers=1,
                        timeout_graceful_shutdown=3, access_log=False)
    except RuntimeError as error:
        raise SystemExit(str(error)) from None


if __name__ == '__main__':
    main()
