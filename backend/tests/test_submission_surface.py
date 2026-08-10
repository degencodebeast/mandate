"""Public submission claim tests for ticket 12."""

import re
import zipfile
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


def test_pitch_and_video_script_keep_the_truthful_submission_boundary() -> None:
    pitch = _ROOT / "evidence" / "Mandate-Hackathon-Pitch.pptx"
    video_script = (_ROOT / "evidence" / "demo-video-script.md").read_text()

    assert pitch.exists()
    with zipfile.ZipFile(pitch) as archive:
        slides = sorted(
            name for name in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
        )
        slide_text = " ".join(archive.read(name).decode() for name in slides)

    assert len(slides) == 8
    assert "NO BLIND RETRIES" in slide_text
    assert "ONE PAYMENT" not in slide_text
    assert "No new wallet" not in slide_text
    assert "No new agent framework" not in slide_text
    assert "No replacement for Circle" not in slide_text
    assert "ERC-8004" not in slide_text
    assert "MCP" not in slide_text
    assert "Payment Reference" in video_script
    assert "Receipt Anchor" in video_script
    assert "ERC-8004" not in video_script
    assert "MCP" not in video_script
