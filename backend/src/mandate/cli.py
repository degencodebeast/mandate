"""Shared subprocess runner for Circle CLI adapters (ADR-0012).

Each adapter accepts an injectable runner so tests can script the CLI without a
binary or network (ADR-0024). In production this helper executes the fixed
command list with subprocess. The list is a literal constructed by the caller —
never a shell string — so no user input reaches a shell.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence


def run_cli(
    command: Sequence[str],
    runner: Callable[[Sequence[str]], str] | None = None,
    timeout: float | None = None,
) -> str:
    """Run a fixed Circle CLI command, or delegate to an injected test runner.

    A timeout bounds the subprocess when no runner is injected. The injected
    runner owns its own timing, so tests never rely on wall-clock time.
    """
    if runner is not None:
        return runner(command)
    completed = subprocess.run(  # noqa: S603 - fixed literal list, no shell, no user input
        list(command),
        capture_output=True,
        check=True,
        text=True,
        timeout=timeout,
    )
    return completed.stdout
