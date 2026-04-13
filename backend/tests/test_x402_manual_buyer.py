from __future__ import annotations

from pathlib import Path
import sys

import pytest


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import x402_manual_buyer as buyer  # noqa: E402


def test_build_payment_payload_prefixes_signature_and_embeds_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(buyer.time, "time", lambda: 1_700_000_000)
    monkeypatch.setattr(buyer.secrets, "token_hex", lambda _: "ab" * 32)

    payload = buyer.build_payment_payload(
        private_key="0x52c80084d7aafe74ab5667d6a65351b8a3ee0a67c299ea0d14dc87b0facb5f77",
        chain_id=2368,
        asset="0x1b7425d288ea676FCBc65c29711fccF0B6D5c293",
        pay_to="0xb62a08Bdd7ba0cb8cdDa1e3E410fa964d07b9C97",
        amount="1000000000000000000",
        max_timeout_seconds=300,
        domain_name="Kite X402 USD",
        domain_version="1",
        accepted_requirement={
            "scheme": "exact",
            "network": "eip155:2368",
            "asset": "0x1b7425d288ea676FCBc65c29711fccF0B6D5c293",
            "amount": "1000000000000000000",
            "payTo": "0xb62a08Bdd7ba0cb8cdDa1e3E410fa964d07b9C97",
            "maxTimeoutSeconds": 300,
            "extra": {"name": "Kite X402 USD", "version": "1"},
        },
    )

    assert payload["x402Version"] == 2
    assert payload["accepted"]["scheme"] == "exact"
    signature = payload["payload"]["signature"]
    assert isinstance(signature, str)
    assert signature.startswith("0x")
    assert len(signature) == 132
    authorization = payload["payload"]["authorization"]
    assert authorization["nonce"] == "0x" + ("ab" * 32)
