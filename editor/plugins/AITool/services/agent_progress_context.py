"""Small dependency-free progress context shared by LANChat worker and agents."""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Callable, Optional

_PROGRESS_CONTEXT = threading.local()


@contextmanager
def agent_progress_sink(sink: Optional[Callable[[str], None]]):
    """Expose a sanitized progress sink for the current agent call only."""
    previous = getattr(_PROGRESS_CONTEXT, "sink", None)
    _PROGRESS_CONTEXT.sink = sink
    try:
        yield
    finally:
        _PROGRESS_CONTEXT.sink = previous


def get_current_progress_sink() -> Optional[Callable[[str], None]]:
    return getattr(_PROGRESS_CONTEXT, "sink", None)
