"""Custom UvicornWorker with per-message deflate enabled for WebSocket compression."""

import sys

from gunicorn.arbiter import Arbiter
from uvicorn import Server
from uvicorn.workers import UvicornWorker as _Base

from startup.required_task_server import serve_required_tasks


class UvicornWorker(_Base):
    CONFIG_KWARGS: dict = {
        **_Base.CONFIG_KWARGS,
        "ws_per_message_deflate": True,
    }

    async def _serve(self) -> None:
        self.config.app = self.wsgi
        server = Server(config=self.config)
        self._install_sigquit_handler()
        try:
            failed = await serve_required_tasks(server, self.wsgi, sockets=self.sockets)
        except SystemExit as exc:
            if exc.code in (None, 0):
                raise
            sys.exit(Arbiter.WORKER_BOOT_ERROR)
        except Exception:
            sys.exit(Arbiter.WORKER_BOOT_ERROR)
        if failed:
            # A required role failure must fail the master, not restart forever.
            sys.exit(Arbiter.WORKER_BOOT_ERROR)
