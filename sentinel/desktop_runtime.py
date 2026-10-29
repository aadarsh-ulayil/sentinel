"""Own only the gateway started by this desktop session."""
import threading
import uvicorn
from .app import BASE, create_app
from .instance import gateway_lock


class Gateway(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.server = None
        self.error = None
        self.stopping = threading.Event()

    def run(self):
        try:
            with gateway_lock(BASE / '.runtime' / 'gateway.lock'):
                if self.stopping.is_set():
                    return
                self.server = uvicorn.Server(uvicorn.Config(create_app(), host='127.0.0.1', port=8000,
                                             access_log=False, timeout_graceful_shutdown=3))
                if self.stopping.is_set():
                    return
                self.server.run()
        except (Exception, SystemExit) as error:
            self.error = str(error)

    def stop(self):
        self.stopping.set()
        if self.server:
            self.server.should_exit = True
        self.join(timeout=5)
