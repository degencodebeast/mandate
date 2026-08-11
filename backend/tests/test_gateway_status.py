"""Official Gateway x402 transfer-status boundary tests (ticket 11).

The official status boundary is ``GET /v1/x402/transfers/{id}`` on the Circle
Gateway API. It resolves the exact buyer-visible Payment Reference (the transfer
UUID that ``POST /v1/x402/settle`` returns) to a payment state and an optional
batch-level settlement transaction hash. Missing output, a timeout, a failed
lookup, or a document without a usable state is an Unknown Outcome: it proves
nothing, so the intent must stay frozen (ticket 11).
"""

from __future__ import annotations

import pytest

from mandate.gateway_status import (
    GatewayTransferStatusInspector,
    TransferLookupUnknownError,
    TransferStatus,
)


class RecordingRunner:
    """Capture the exact URL queried and answer with a fixed status body."""

    def __init__(self, body: str, *, status: int = 200) -> None:
        self.body = body
        self.status_code = status
        self.urls: list[str] = []

    def __call__(self, url: str) -> str:
        self.urls.append(url)
        if self.status_code != 200:
            raise RuntimeError(f"HTTP {self.status_code}")
        return self.body


def test_inspector_queries_exact_reference_and_reads_state() -> None:
    reference = "3e80e924-6263-4393-b639-b4ab56da6925"
    batch = "0x9a3af4c339eb81ddef60a1facb7cb6d9d6896a1fe4dbbcd755de6407886b5171"
    body = (
        '{"id": "' + reference + '", "status": "completed", "token": "USDC",'
        ' "sendingNetwork": "eip155:5042002", "recipientNetwork": "eip155:5042002",'
        ' "amount": "10000", "txHash": "' + batch + '"}'
    )
    runner = RecordingRunner(body)
    inspector = GatewayTransferStatusInspector(
        base_url="https://gateway-api-testnet.circle.com", runner=runner
    )

    status = inspector.lookup_transfer(reference)

    assert status == TransferStatus(
        payment_reference=reference,
        payment_state="completed",
        batch_tx_hash=batch,
    )
    assert runner.urls == [f"https://gateway-api-testnet.circle.com/v1/x402/transfers/{reference}"]


def test_inspector_unknown_when_batch_hash_absent() -> None:
    body = '{"id": "x", "status": "received", "txHash": null}'
    runner = RecordingRunner(body)
    inspector = GatewayTransferStatusInspector(
        base_url="https://gateway-api-testnet.circle.com", runner=runner
    )

    status = inspector.lookup_transfer("x")

    assert status.payment_state == "received"
    assert status.batch_tx_hash is None


def test_inspector_missing_output_is_unknown() -> None:
    runner = RecordingRunner("not json", status=500)
    inspector = GatewayTransferStatusInspector(
        base_url="https://gateway-api-testnet.circle.com", runner=runner
    )

    with pytest.raises(TransferLookupUnknownError):
        inspector.lookup_transfer("x")


def test_inspector_timeout_is_unknown() -> None:
    def timeout(_url: str) -> str:
        raise TimeoutError("timed out")

    inspector = GatewayTransferStatusInspector(
        base_url="https://gateway-api-testnet.circle.com", runner=timeout
    )

    with pytest.raises(TransferLookupUnknownError):
        inspector.lookup_transfer("x")


def test_inspector_document_without_state_is_unknown() -> None:
    runner = RecordingRunner('{"id": "x"}')
    inspector = GatewayTransferStatusInspector(
        base_url="https://gateway-api-testnet.circle.com", runner=runner
    )

    with pytest.raises(TransferLookupUnknownError):
        inspector.lookup_transfer("x")


def test_inspector_document_with_different_id_is_unknown() -> None:
    runner = RecordingRunner('{"id": "other", "status": "completed"}')
    inspector = GatewayTransferStatusInspector(
        base_url="https://gateway-api-testnet.circle.com", runner=runner
    )

    with pytest.raises(TransferLookupUnknownError):
        inspector.lookup_transfer("x")


def test_inspector_document_without_id_is_unknown() -> None:
    runner = RecordingRunner('{"status": "completed"}')
    inspector = GatewayTransferStatusInspector(
        base_url="https://gateway-api-testnet.circle.com", runner=runner
    )

    with pytest.raises(TransferLookupUnknownError):
        inspector.lookup_transfer("x")


def test_inspector_sends_a_user_agent_on_the_real_http_path() -> None:
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    captured: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            captured["user_agent"] = self.headers.get("User-Agent", "")
            body = b'{"id": "x", "status": "completed"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        inspector = GatewayTransferStatusInspector(base_url=f"http://127.0.0.1:{port}")
        status = inspector.lookup_transfer("x")
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status.payment_state == "completed"
    assert captured["user_agent"].startswith("mandate-service")
