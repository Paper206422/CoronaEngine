import json
import logging


logger = logging.getLogger(__name__)


class StreamDispatcher:
    def __init__(self, js_call_func):
        self._js_call_func = js_call_func

    def dispatch_chunk(self, chunk: str, request_id: str | None, token: str | None) -> str:
        result_obj = json.loads(chunk)
        session_id = result_obj.get("session_id", "N/A")

        metadata = result_obj.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            result_obj["metadata"] = metadata
        if request_id:
            metadata.setdefault("request_id", request_id)
        if token:
            metadata["token"] = token

        event_type = self.get_stream_event_type(result_obj)
        result = json.dumps(result_obj, ensure_ascii=False)
        self._js_call_func("ai-chunk", [result])
        logger.debug(
            "[AI Bridge Stream] 已发送流式事件 [request=%s, session=%s, event=%s]",
            metadata.get("request_id", request_id or "N/A"),
            session_id,
            event_type,
        )
        return event_type

    def dispatch_error(self, error_payload: str):
        self._js_call_func("ai-chunk", [error_payload])

    @staticmethod
    def get_stream_event_type(result_obj: dict) -> str:
        metadata = result_obj.get("metadata")
        if isinstance(metadata, dict):
            if metadata.get("stream_done"):
                return "done"
            if metadata.get("heartbeat"):
                return "heartbeat"
        if result_obj.get("error_code"):
            return "error"
        chunk_type = result_obj.get("chunk_type")
        return chunk_type if isinstance(chunk_type, str) and chunk_type else "data"