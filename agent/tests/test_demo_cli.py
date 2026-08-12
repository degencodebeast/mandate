"""Demo command result and error output tests."""

from __future__ import annotations

import sys
from typing import Any

from agno_demo import demo


def test_demo_command_reports_one_concise_domain_error(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    monkeypatch.setattr(sys, "argv", ["agno-demo"])
    monkeypatch.setattr(demo, "_build_client", lambda _args: object())
    monkeypatch.setattr(demo, "build_model", lambda **_kwargs: object())

    def fail(**_kwargs: object) -> list[dict[str, object]]:
        raise RuntimeError("Service B outcome is unknown; no resolve is permitted.")

    monkeypatch.setattr(demo, "run_demo", fail)

    status = demo.main()

    captured = capsys.readouterr()
    assert status == 1
    assert captured.err == "ERROR: Service B outcome is unknown; no resolve is permitted.\n"
    assert "Traceback" not in captured.err


def test_demo_command_keeps_the_freeze_proof_visible_when_service_b_fails(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    monkeypatch.setattr(sys, "argv", ["agno-demo"])
    monkeypatch.setattr(demo, "_build_client", lambda _args: object())
    monkeypatch.setattr(demo, "build_model", lambda **_kwargs: object())

    freeze_report = {
        "scene": "freeze",
        "agent_intent_id": "intent-a",
        "backend_intent_id": "intent-a",
        "ui_intent_id": "intent-a",
        "ui_source": "Mandate status API",
        "decision_action": "wait",
        "may_authorize": False,
        "payment_reference": None,
        "receipt_anchor": None,
        "service_url": "https://service-a.example.com",
        "reason": "unknown outcome",
        "injected_response_loss": True,
        "switch_choice_action": None,
        "spend_attempt_count": 2,
        "payment_state": None,
    }

    def fail(**kwargs: object) -> list[dict[str, object]]:
        callback = kwargs["on_scene_complete"]
        assert callable(callback)
        callback(freeze_report)
        raise RuntimeError("Service B outcome is unknown.")

    monkeypatch.setattr(demo, "run_demo", fail)

    status = demo.main()

    captured = capsys.readouterr()
    assert status == 1
    assert "=== SCENE FREEZE ===" in captured.out
    assert (
        "Intent (Agent/Spend Result/dashboard input): intent-a / intent-a / intent-a"
        in captured.out
    )
    assert "Authorize: no" in captured.out
    assert "Mandate spend calls: 2" in captured.out
    assert captured.err == "ERROR: Service B outcome is unknown.\n"


def test_demo_command_reports_progress_and_success(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    monkeypatch.setattr(sys, "argv", ["agno-demo", "--freeze-only"])
    monkeypatch.setattr(demo, "_build_client", lambda _args: object())
    monkeypatch.setattr(demo, "build_model", lambda **_kwargs: object())
    monkeypatch.setattr(
        demo,
        "run_demo",
        lambda **_kwargs: [
            {
                "scene": "freeze",
                "agent_intent_id": "intent-a",
                "backend_intent_id": "intent-a",
                "ui_intent_id": "intent-a",
                "ui_source": "Mandate status API",
                "decision_action": "wait",
                "may_authorize": False,
                "payment_reference": None,
                "receipt_anchor": None,
                "service_url": "https://service-a.example.com",
                "reason": "unknown outcome",
                "injected_response_loss": True,
                "switch_choice_action": None,
                "spend_attempt_count": 2,
                "payment_state": None,
            }
        ],
    )

    status = demo.main()

    captured = capsys.readouterr()
    assert status == 0
    assert "STEP: Run the same-Intent UNKNOWN proof." in captured.out
    assert "SUCCESS: The same-Intent UNKNOWN proof passed." in captured.out
