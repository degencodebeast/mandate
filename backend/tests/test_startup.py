"""Production HTTP listener configuration tests."""

from __future__ import annotations

from typing import Any

from mandate.api.startup import start_server
from mandate.config import ApiSettings


def test_start_server_trusts_only_the_configured_reverse_proxy(monkeypatch: Any) -> None:
    recorded: dict[str, object] = {}

    def record_run(_app: str, **kwargs: object) -> None:
        recorded.update(kwargs)

    monkeypatch.setattr("mandate.api.startup.uvicorn.run", record_run)

    start_server(ApiSettings(forwarded_allow_ips="10.0.0.0/8"))

    assert recorded["proxy_headers"] is True
    assert recorded["forwarded_allow_ips"] == "10.0.0.0/8"
