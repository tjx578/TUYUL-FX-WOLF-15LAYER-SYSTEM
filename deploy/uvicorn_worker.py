"""Custom UvicornWorker with per-message deflate enabled for WebSocket compression."""

from uvicorn.workers import UvicornWorker as _Base


class UvicornWorker(_Base):
    CONFIG_KWARGS: dict = {
        **_Base.CONFIG_KWARGS,
        "ws_per_message_deflate": True,
    }
