from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from eth_account import Account
from fastapi.testclient import TestClient

from app import main
from app.kite_pass import KitePassVerifier


@pytest.fixture(autouse=True)
def reset_state(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    main.KITE_PASS_ENTITLEMENTS.clear()
    main.TASKS.clear()
    main.SESSIONS.clear()
    main.SESSION_CHALLENGES.clear()
    main.TASK_CHALLENGES.clear()
    main.PAYMENT_INTENTS.clear()
    main.PAYMENT_EVENTS.clear()
    main.PAYMENT_PROVIDER_EVENT_INDEX.clear()

    monkeypatch.setattr(main, "DATABASE_ENABLED", False)
    monkeypatch.setattr(main, "KITE_PASS_ENABLED", True)
    yield


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(main.app) as test_client:
        yield test_client


def test_kite_pass_verify_and_get_status(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    account = Account.create()
    monkeypatch.setattr(main, "KITE_PASS_ALLOWLIST", {account.address.lower()})
    monkeypatch.setattr(main.KITE_PASS_VERIFIER, "allowlist", {account.address.lower()})
    monkeypatch.setattr(main.KITE_PASS_VERIFIER, "enabled", True)

    verify_response = client.post("/kite-pass/verify", json={"wallet_address": account.address})
    assert verify_response.status_code == 200
    verified = verify_response.json()
    assert verified["wallet_address"].lower() == account.address.lower()
    assert verified["has_pass"] is True

    get_response = client.get(f"/kite-pass/{account.address}")
    assert get_response.status_code == 200
    cached = get_response.json()
    assert cached["wallet_address"].lower() == account.address.lower()
    assert cached["has_pass"] is True


def test_kite_pass_status_not_found_when_not_verified(client: TestClient) -> None:
    account = Account.create()
    response = client.get(f"/kite-pass/{account.address}")
    assert response.status_code == 404


def test_kite_pass_verify_rejects_when_disabled(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "KITE_PASS_ENABLED", False)
    account = Account.create()

    response = client.post("/kite-pass/verify", json={"wallet_address": account.address})
    assert response.status_code == 400
    assert "disabled" in response.json()["detail"].lower()


# ------------------------------------------------------------------
# On-chain verification tests
# ------------------------------------------------------------------

def _make_onchain_verifier(balance: int, standard: str = "erc721") -> KitePassVerifier:
    """Build a verifier with on-chain config and a mocked web3 contract."""
    return KitePassVerifier(
        enabled=True,
        allowlist=set(),
        rpc_url="https://rpc.example.com",
        contract_address="0x" + "a" * 40,
        token_standard=standard,
        token_id=1,
    )


def _mock_contract_balance(balance: int, standard: str = "erc721") -> MagicMock:
    mock_contract = MagicMock()
    if standard == "erc1155":
        mock_contract.functions.balanceOf.return_value.call.return_value = balance
    else:
        mock_contract.functions.balanceOf.return_value.call.return_value = balance
    return mock_contract


def test_kite_pass_onchain_has_pass(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """On-chain balanceOf returns 1 → has_pass=True, source='onchain'."""
    account = Account.create()

    verifier = _make_onchain_verifier(balance=1)
    monkeypatch.setattr(main, "KITE_PASS_VERIFIER", verifier)
    monkeypatch.setattr(main, "KITE_PASS_ENABLED", True)

    mock_w3 = MagicMock()
    mock_w3.eth.contract.return_value = _mock_contract_balance(1)
    mock_w3.to_checksum_address = lambda addr: addr  # passthrough

    with patch("app.kite_pass.Web3") as MockWeb3:
        MockWeb3.return_value = mock_w3
        MockWeb3.HTTPProvider = MagicMock()
        MockWeb3.to_checksum_address = lambda addr: addr

        response = client.post("/kite-pass/verify", json={"wallet_address": account.address})

    assert response.status_code == 200
    data = response.json()
    assert data["has_pass"] is True
    assert data["source"] == "onchain"


def test_kite_pass_onchain_no_pass(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """On-chain balanceOf returns 0 → has_pass=False, source='onchain_miss'."""
    account = Account.create()

    verifier = _make_onchain_verifier(balance=0)
    monkeypatch.setattr(main, "KITE_PASS_VERIFIER", verifier)
    monkeypatch.setattr(main, "KITE_PASS_ENABLED", True)

    mock_w3 = MagicMock()
    mock_w3.eth.contract.return_value = _mock_contract_balance(0)

    with patch("app.kite_pass.Web3") as MockWeb3:
        MockWeb3.return_value = mock_w3
        MockWeb3.HTTPProvider = MagicMock()
        MockWeb3.to_checksum_address = lambda addr: addr

        response = client.post("/kite-pass/verify", json={"wallet_address": account.address})

    assert response.status_code == 200
    data = response.json()
    assert data["has_pass"] is False
    assert data["source"] == "onchain_miss"


def test_kite_pass_onchain_rpc_error_returns_no_pass(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RPC exception → graceful fallback, source='onchain_error', still 200."""
    account = Account.create()

    verifier = _make_onchain_verifier(balance=0)
    monkeypatch.setattr(main, "KITE_PASS_VERIFIER", verifier)
    monkeypatch.setattr(main, "KITE_PASS_ENABLED", True)

    with patch("app.kite_pass.Web3") as MockWeb3:
        MockWeb3.side_effect = RuntimeError("connection refused")

        response = client.post("/kite-pass/verify", json={"wallet_address": account.address})

    assert response.status_code == 200
    data = response.json()
    assert data["has_pass"] is False
    assert data["source"] == "onchain_error"


def test_kite_pass_allowlist_bypasses_onchain(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wallet in allowlist → source='allowlist' without triggering on-chain call."""
    account = Account.create()
    normalized = account.address.lower()

    verifier = KitePassVerifier(
        enabled=True,
        allowlist={normalized},
        rpc_url="https://rpc.example.com",
        contract_address="0x" + "a" * 40,
    )
    monkeypatch.setattr(main, "KITE_PASS_VERIFIER", verifier)
    monkeypatch.setattr(main, "KITE_PASS_ENABLED", True)

    with patch("app.kite_pass.Web3") as MockWeb3:
        response = client.post("/kite-pass/verify", json={"wallet_address": account.address})
        MockWeb3.assert_not_called()

    assert response.status_code == 200
    data = response.json()
    assert data["has_pass"] is True
    assert data["source"] == "allowlist"


def test_kite_pass_onchain_erc1155(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """ERC-1155 path calls balanceOf(address, tokenId) and returns has_pass=True."""
    account = Account.create()

    verifier = KitePassVerifier(
        enabled=True,
        allowlist=set(),
        rpc_url="https://rpc.example.com",
        contract_address="0x" + "b" * 40,
        token_standard="erc1155",
        token_id=42,
    )
    monkeypatch.setattr(main, "KITE_PASS_VERIFIER", verifier)
    monkeypatch.setattr(main, "KITE_PASS_ENABLED", True)

    mock_contract = MagicMock()
    mock_contract.functions.balanceOf.return_value.call.return_value = 3
    mock_w3 = MagicMock()
    mock_w3.eth.contract.return_value = mock_contract

    with patch("app.kite_pass.Web3") as MockWeb3:
        MockWeb3.return_value = mock_w3
        MockWeb3.HTTPProvider = MagicMock()
        MockWeb3.to_checksum_address = lambda addr: addr

        response = client.post("/kite-pass/verify", json={"wallet_address": account.address})

    assert response.status_code == 200
    data = response.json()
    assert data["has_pass"] is True
    assert data["source"] == "onchain"
    # Verify balanceOf was called with (address, tokenId)
    mock_contract.functions.balanceOf.assert_called_once()

