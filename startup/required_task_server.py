"""Bound required-task shutdown for the Railway ASGI worker entrypoint."""

import asyncio
import os
import threading


async def serve_required_tasks(server, app, *, sockets=None):
    """Return failure after drain; forcibly exit if cancellation cannot finish."""
    deadline = None

    def arm_deadline():
        nonlocal deadline
        if deadline is None:
            deadline = threading.Timer(25, lambda: os._exit(3))
            deadline.daemon = True
            deadline.start()

    async def monitor():
        while True:
            supervisor = getattr(app.state, "required_task_supervisor", None)
            if supervisor is not None:
                supervisor.snapshot()
                if supervisor.fatal.is_set() and not server.should_exit:
                    # Preserve a bounded opportunity to read the causal 503.
                    await asyncio.sleep(1)
                    server.should_exit = True
            if server.should_exit and deadline is None:
                # Gunicorn's own graceful timeout is an additional parent bound.
                arm_deadline()
            await asyncio.sleep(0.05)

    watcher = asyncio.create_task(monitor(), name="railway-required-task-monitor")
    serving = asyncio.create_task(server.serve(sockets=sockets), name="railway-api-server")
    monitor_failed = False
    try:
        done, _ = await asyncio.wait({serving, watcher}, return_when=asyncio.FIRST_COMPLETED)
        if watcher in done:
            monitor_failed = True
            server.should_exit = True
            arm_deadline()
        await serving
        supervisor = getattr(app.state, "required_task_supervisor", None)
        return bool(
            monitor_failed
            or not server.started
            or any(getattr(server.lifespan, field, False) for field in ("startup_failed", "shutdown_failed"))
            or (supervisor is not None and supervisor.fatal.is_set())
        )
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)
        supervisor = getattr(app.state, "required_task_supervisor", None)
        pending = supervisor is not None and any(not task.done() for task in supervisor.tasks.values())
        # asyncio.run will cancel remaining tasks after _serve returns. Keep the
        # process deadline armed while a resistant required task can block it.
        if pending:
            arm_deadline()
        if deadline is not None and not pending:
            deadline.cancel()
