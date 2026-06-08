"""Network plugin — LAN collaborative editing bridge.

Routes JS cefQuery -> C++ CoronaEngine network_start_session (Python bindings via nanobind).
Peer events (connect/disconnect) are pushed back to the frontend via js_call_func('network-event').
"""

import logging

logger = logging.getLogger(__name__)

from CoronaCore.core.corona_editor import CoronaEditor
from CoronaPlugin.core.corona_plugin_base import PluginBase
from CoronaCore.utils.corona_engine_fallback import CoronaEngine as FallbackEngine


# ---------------------------------------------------------------------------
# Frontend push helper
# ---------------------------------------------------------------------------
FRONTEND_EVENT = "network-event"


def _push_to_frontend(event: dict) -> None:
    """Push a network event dict to the Vue frontend via coronaEventBus."""
    try:
        CoronaEditor.js_call_func(FRONTEND_EVENT, [event])
    except Exception:
        logger.exception("[Network] Failed to push event to frontend")


def _get_engine():
    """Return the engine module (real or fallback)."""
    eng = CoronaEditor.CoronaEngine
    if eng is None:
        eng = FallbackEngine
    return eng


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------
@PluginBase.register_web("Network")
class NetworkPlugin(PluginBase):
    """Thin proxy that calls CoronaEngine network_* functions."""

    @classmethod
    def start_session(cls, instance_name: str, project_id: int, port: int = 27960) -> dict:
        """Start a LAN collaborative editing session."""
        try:
            engine = _get_engine()
            logger.info("[Network] start_session: name=%s project=%s port=%s engine=%s",
                        instance_name, project_id, port, type(engine).__module__)
            ok = engine.network_start_session(instance_name, int(project_id), int(port))
            logger.info("[Network] start_session result: %s", ok)
            return {"ok": ok}
        except Exception as exc:
            logger.exception("[Network] start_session failed")
            return {"ok": False, "error": str(exc)}

    @classmethod
    def stop_session(cls) -> dict:
        """Stop the LAN collaborative editing session."""
        try:
            engine = _get_engine()
            engine.network_stop_session()
            return {"ok": True}
        except Exception as exc:
            logger.exception("[Network] stop_session failed")
            return {"ok": False, "error": str(exc)}

    @classmethod
    def get_peer_count(cls) -> dict:
        """Get the number of currently connected peers."""
        try:
            engine = _get_engine()
            count = engine.network_peer_count()
            return {"ok": True, "peer_count": count}
        except Exception as exc:
            logger.exception("[Network] get_peer_count failed")
            return {"ok": False, "peer_count": 0, "error": str(exc)}
