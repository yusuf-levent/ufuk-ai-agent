from __future__ import annotations

from app.logging import redact_processor


def test_redact_processor_scrubs_sensitive_keys() -> None:
    event = redact_processor(
        None,
        "info",
        {
            "authorization": "Bearer abc",
            "x-api-key": "k",
            "password": "hunter2",
            "upstream_api_key": "secret",
            "user_api_key_name": "x",
            "user_id": "u-1",
            "prompt_tokens": 10,
            "nested": {"api_key": "k", "count": 2, "deep": [{"refresh_token": "t"}]},
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert event["authorization"] == "[REDACTED]"
    assert event["x-api-key"] == "[REDACTED]"
    assert event["password"] == "[REDACTED]"
    assert event["upstream_api_key"] == "[REDACTED]"
    assert event["user_api_key_name"] == "[REDACTED]"
    assert event["messages"] == "[REDACTED]"
    assert event["user_id"] == "u-1"
    assert event["prompt_tokens"] == 10
    nested = event["nested"]
    assert nested["api_key"] == "[REDACTED]"
    assert nested["count"] == 2
    assert nested["deep"][0]["refresh_token"] == "[REDACTED]"


def test_redact_processor_keeps_normal_metadata() -> None:
    event = redact_processor(
        None,
        "info",
        {
            "event": "upstream_call",
            "request_id": "abc",
            "tier_alias": "fast",
            "status": 200,
            "latency_ms": 123,
            "prompt_tokens": 100,
            "completion_tokens": 50,
        },
    )
    assert event == {
        "event": "upstream_call",
        "request_id": "abc",
        "tier_alias": "fast",
        "status": 200,
        "latency_ms": 123,
        "prompt_tokens": 100,
        "completion_tokens": 50,
    }
