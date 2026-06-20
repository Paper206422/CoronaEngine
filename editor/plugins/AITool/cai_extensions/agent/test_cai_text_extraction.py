"""Focused tests for CAI chat envelope text extraction."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from cai_extensions.agent.agent_adapter import _extract_cai_text_chunk  # noqa: E402


def test_extract_build_success_response_text():
    chunk = (
        '{"session_id":"s","error_code":0,"status_info":"ok",'
        '"llm_content":[{"part":[{"content_type":"text","content_text":"hello"}]}]}'
    )
    assert _extract_cai_text_chunk(chunk) == "hello"


def test_extract_nested_stream_event_text():
    chunk = {
        "data": {
            "llm_content": [
                {"part": [{"content_type": "text", "content_text": "nested"}]},
            ],
        },
    }
    assert _extract_cai_text_chunk(chunk) == "nested"


def test_ignore_empty_status_envelope():
    assert _extract_cai_text_chunk({"session_id": "s", "status_info": "ok"}) == ""


def test_strip_tool_json_from_visible_text():
    chunk = {
        "llm_content": [
            {
                "part": [
                    {
                        "content_type": "text",
                        "content_text": (
                            '{"actor":"喷泉","position":[0,0.5,-8],'
                            '"scale":[1.5,1.5,1.5],"scene_json_updated":false}'
                            "已将喷泉抬高。"
                        ),
                    }
                ]
            }
        ]
    }
    text = _extract_cai_text_chunk(chunk)
    assert "actor" not in text and "position" not in text
    assert text == "已将喷泉抬高。"


if __name__ == "__main__":
    test_extract_build_success_response_text()
    test_extract_nested_stream_event_text()
    test_ignore_empty_status_envelope()
    test_strip_tool_json_from_visible_text()
    print("\n=== CAI text extraction ALL PASS ===")
