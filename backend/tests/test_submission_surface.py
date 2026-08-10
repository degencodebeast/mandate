"""Public submission claim tests for ticket 12."""

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def test_readme_leads_judges_to_real_and_injected_proof_without_pending_claims() -> None:
    readme = (_ROOT / "README.md").read_text()

    assert readme.index("## 60-second judge path") < readme.index("## How Mandate works")
    assert "7def6214-d8d1-4562-9d0a-b50bcff80b72" in readme
    assert "0xc29eecd907ee53038e1c35c8d974b735f8f996b259f1025bbd77d3cf691c01fd" in readme
    assert "Real Arc testnet economic action" in readme
    assert "Deliberately injected failure" in readme
    assert "REST is the stable interface" in readme
    assert "final submission still needs" not in readme.lower()
    assert "mcp" not in readme.lower()
    assert "erc-8004" not in readme.lower()
    assert "payment fee" not in readme.lower()

    local_links = re.findall(r"\[[^\]]+\]\((?!https?://)([^)#]+)(?:#[^)]+)?\)", readme)
    assert all((_ROOT / target).exists() for target in local_links)


def test_public_package_and_receipt_contract_use_truthful_boundary_names() -> None:
    package = (_ROOT / "backend" / "pyproject.toml").read_text()
    registry = (_ROOT / "contracts" / "src" / "ReceiptRegistry.sol").read_text()

    assert "MCP" not in package
    assert "ERC-8004" not in registry
    assert "userId" not in registry
    assert "txHash" not in registry
    assert "feeTxHash" not in registry
    assert "authorityId" in registry
    assert "paymentReference" in registry
