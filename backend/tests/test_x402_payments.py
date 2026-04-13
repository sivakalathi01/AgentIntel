from __future__ import annotations

import base64
import json
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from app import database as app_database
from app import main
from app.passport_client import KitePassportClientError
from app.payments import X402SettleResult, X402VerifyResult


def encode_payment_header(payload: dict[str, object]) -> str:
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


@pytest.fixture(autouse=True)
def reset_state(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    main.TASKS.clear()
    main.SESSIONS.clear()
    main.SESSION_CHALLENGES.clear()
    main.TASK_CHALLENGES.clear()
    main.PAYMENT_INTENTS.clear()
    main.PAYMENT_EVENTS.clear()
    main.PAYMENT_PROVIDER_EVENT_INDEX.clear()
    main.KITE_PASS_ENTITLEMENTS.clear()

    main.SESSION_CHALLENGE_REQUESTS.clear()
    main.TASK_CHALLENGE_REQUESTS.clear()
    main.SESSION_CHALLENGE_REQUESTS_IP.clear()
    main.TASK_CHALLENGE_REQUESTS_IP.clear()

    for key in main.SECURITY_METRICS:
        main.SECURITY_METRICS[key] = 0

    monkeypatch.setattr(main, "DATABASE_ENABLED", False)
    monkeypatch.setattr(app_database, "DATABASE_ENABLED", False)
    monkeypatch.setattr(main, "init_database", lambda: None)
    monkeypatch.setattr(main, "X402_PAY_TO", "0x4A50DCA63d541372ad36E5A36F1D542d51164F19")
    monkeypatch.setattr(main.X402_CLIENT, "pay_to", "0x4A50DCA63d541372ad36E5A36F1D542d51164F19")
    monkeypatch.setattr(main, "PRUNE_TASK", None)

    async def _pruner_noop() -> None:
        return None

    monkeypatch.setattr(main, "challenge_pruner_loop", _pruner_noop)
    yield


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(main.app) as test_client:
        yield test_client


def test_legacy_payment_intent_endpoint_removed(client: TestClient) -> None:
    response = client.post("/payments/intents", json={"amount_usd": 7.5, "currency": "USD"})
    assert response.status_code == 410
    assert "legacy payment intent flow removed" in response.json()["detail"].lower()


def test_session_returns_402_with_payment_requirements(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "X402_ENABLED", True)

    response = client.post(
        "/sessions",
        json={
            "budget_limit": 10,
            "valid_for_hours": 2,
            "allowed_providers": ["primary_serper"],
        },
    )

    assert response.status_code == 402
    payload = response.json()
    assert payload["x402Version"] == 2
    assert payload["accepts"][0]["scheme"] == "exact"
    assert payload["accepts"][0]["network"] == main.X402_NETWORK
    assert payload["accepts"][0]["payTo"] == main.X402_PAY_TO
    assert "PAYMENT-REQUIRED" in response.headers


def test_session_succeeds_after_verify_and_settle(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "X402_ENABLED", True)
    payer = "0x8794c866DB97E0E7c1a0E2CF51D3E1460cB37F9e"

    async def verify_ok(*, payment_payload: dict[str, object], payment_requirements: dict[str, object], x402_version: int) -> X402VerifyResult:
        del payment_payload, payment_requirements, x402_version
        return X402VerifyResult(is_valid=True, payer=payer, raw={"isValid": True, "payer": payer})

    async def settle_ok(*, payment_payload: dict[str, object], payment_requirements: dict[str, object], x402_version: int) -> X402SettleResult:
        del payment_payload, payment_requirements, x402_version
        return X402SettleResult(
            success=True,
            payer=payer,
            transaction="0xtestsettlement",
            network=main.X402_NETWORK,
            raw={"success": True, "payer": payer, "transaction": "0xtestsettlement", "network": main.X402_NETWORK},
        )

    monkeypatch.setattr(main.X402_CLIENT, "verify", verify_ok)
    monkeypatch.setattr(main.X402_CLIENT, "settle", settle_ok)

    payment_header = encode_payment_header(
        {
            "x402Version": 2,
            "accepted": {
                "scheme": "exact",
                "network": main.X402_NETWORK,
                "asset": main.X402_ASSET,
                "maxAmountRequired": "10000000000000000000",
                "payTo": main.X402_PAY_TO,
            },
            "payload": {"signature": "0xdeadbeef", "authorization": {"from": payer}},
        }
    )

    response = client.post(
        "/sessions",
        headers={"PAYMENT-SIGNATURE": payment_header},
        json={
            "budget_limit": 10,
            "valid_for_hours": 2,
            "allowed_providers": ["primary_serper"],
        },
    )

    assert response.status_code == 200
    assert "PAYMENT-RESPONSE" in response.headers
    assert len(main.PAYMENT_INTENTS) == 1
    stored_intent = next(iter(main.PAYMENT_INTENTS.values()))
    assert stored_intent.status == "confirmed"
    assert stored_intent.provider_intent_id == "0xtestsettlement"
    assert len(main.PAYMENT_EVENTS) == 2


def test_invalid_payment_returns_402(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "X402_ENABLED", True)

    async def verify_invalid(*, payment_payload: dict[str, object], payment_requirements: dict[str, object], x402_version: int) -> X402VerifyResult:
        del payment_payload, payment_requirements, x402_version
        return X402VerifyResult(
            is_valid=False,
            invalid_reason="signature_invalid",
            raw={"isValid": False, "invalidReason": "signature_invalid"},
        )

    monkeypatch.setattr(main.X402_CLIENT, "verify", verify_invalid)

    payment_header = encode_payment_header({"x402Version": 2, "payload": {"signature": "0xdeadbeef"}})
    response = client.post(
        "/sessions",
        headers={"PAYMENT-SIGNATURE": payment_header},
        json={
            "budget_limit": 10,
            "valid_for_hours": 2,
            "allowed_providers": ["primary_serper"],
        },
    )

    assert response.status_code == 402
    assert "signature_invalid" in response.json()["error"]


def test_signature_is_prefixed_before_verify(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "X402_ENABLED", True)
    payer = "0x8794c866DB97E0E7c1a0E2CF51D3E1460cB37F9e"

    async def verify_ok(*, payment_payload: dict[str, object], payment_requirements: dict[str, object], x402_version: int) -> X402VerifyResult:
        del payment_requirements, x402_version
        nested = payment_payload.get("payload")
        signature = nested.get("signature") if isinstance(nested, dict) else payment_payload.get("signature")
        assert isinstance(signature, str)
        assert signature.startswith("0x")
        return X402VerifyResult(is_valid=True, payer=payer, raw={"isValid": True, "payer": payer})

    async def settle_ok(*, payment_payload: dict[str, object], payment_requirements: dict[str, object], x402_version: int) -> X402SettleResult:
        del payment_payload, payment_requirements, x402_version
        return X402SettleResult(
            success=True,
            payer=payer,
            transaction="0xtestsettlement",
            network=main.X402_NETWORK,
            raw={"success": True, "payer": payer, "transaction": "0xtestsettlement", "network": main.X402_NETWORK},
        )

    monkeypatch.setattr(main.X402_CLIENT, "verify", verify_ok)
    monkeypatch.setattr(main.X402_CLIENT, "settle", settle_ok)

    payment_header = encode_payment_header(
        {
            "x402Version": 2,
            "accepted": {
                "scheme": "exact",
                "network": main.X402_NETWORK,
                "asset": main.X402_ASSET,
                "maxAmountRequired": "1000000000000000000",
                "payTo": main.X402_PAY_TO,
            },
            # Intentionally missing 0x prefix to verify backend normalization.
            "payload": {"signature": "deadbeef", "authorization": {"from": payer}},
        }
    )

    response = client.post(
        "/sessions",
        headers={"PAYMENT-SIGNATURE": payment_header},
        json={
            "budget_limit": 10,
            "valid_for_hours": 2,
            "allowed_providers": ["primary_serper"],
        },
    )

    assert response.status_code == 200


def test_kite_pass_bypass_skips_x402_requirement(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import datetime, timedelta, timezone

    from eth_account import Account

    monkeypatch.setattr(main, "X402_ENABLED", True)
    monkeypatch.setattr(main, "KITE_PASS_ENABLED", True)
    monkeypatch.setattr(main, "KITE_PASS_PAYWALL_POLICY", "bypass")

    account = Account.create()
    monkeypatch.setattr(main, "verify_wallet_signature", lambda _payload: account.address)

    now = datetime.now(tz=timezone.utc)
    entitlement = main.InMemoryKitePassEntitlement(
        wallet_address=account.address.lower(),
        has_pass=True,
        source="allowlist",
        checked_at=now.isoformat(),
        expires_at=(now + timedelta(hours=1)).isoformat(),
    )
    main.persist_kite_pass_entitlement(entitlement)

    response = client.post(
        "/sessions",
        json={
            "budget_limit": 10,
            "allowed_providers": ["fallback_wikipedia"],
        },
    )

    assert response.status_code == 200


def test_passport_sessions_endpoint_maps_existing_session(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "X402_ENABLED", False)

    create = client.post(
        "/sessions",
        json={
            "budget_limit": 7,
            "valid_for_hours": 2,
            "allowed_providers": ["primary_serper"],
        },
    )
    assert create.status_code == 200
    created = create.json()

    sessions_response = client.get("/passport/sessions")
    assert sessions_response.status_code == 200
    sessions = sessions_response.json()
    mapped = next(item for item in sessions if item["session_id"] == created["id"])
    assert mapped["max_total_spend_usd"] == 7
    assert mapped["available_usd"] == 7
    assert mapped["revoked"] is False

    single = client.get(f"/passport/sessions/{created['id']}")
    assert single.status_code == 200
    assert single.json()["session_id"] == created["id"]


def test_passport_delegations_endpoint_maps_confirmed_x402_payment(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "X402_ENABLED", True)
    payer = "0x8794c866DB97E0E7c1a0E2CF51D3E1460cB37F9e"

    async def verify_ok(*, payment_payload: dict[str, object], payment_requirements: dict[str, object], x402_version: int) -> X402VerifyResult:
        del payment_payload, payment_requirements, x402_version
        return X402VerifyResult(is_valid=True, payer=payer, raw={"isValid": True, "payer": payer})

    async def settle_ok(*, payment_payload: dict[str, object], payment_requirements: dict[str, object], x402_version: int) -> X402SettleResult:
        del payment_payload, payment_requirements, x402_version
        return X402SettleResult(
            success=True,
            payer=payer,
            transaction="0xtestsettlement",
            network=main.X402_NETWORK,
            raw={"success": True, "payer": payer, "transaction": "0xtestsettlement", "network": main.X402_NETWORK},
        )

    monkeypatch.setattr(main.X402_CLIENT, "verify", verify_ok)
    monkeypatch.setattr(main.X402_CLIENT, "settle", settle_ok)

    payment_header = encode_payment_header(
        {
            "x402Version": 2,
            "accepted": {
                "scheme": "exact",
                "network": main.X402_NETWORK,
                "asset": main.X402_ASSET,
                "maxAmountRequired": "1000000000000000000",
                "payTo": main.X402_PAY_TO,
            },
            "payload": {"signature": "0xdeadbeef", "authorization": {"from": payer}},
        }
    )

    paid = client.post(
        "/sessions",
        headers={"PAYMENT-SIGNATURE": payment_header},
        json={
            "budget_limit": 10,
            "valid_for_hours": 2,
            "allowed_providers": ["primary_serper"],
        },
    )
    assert paid.status_code == 200

    delegations_response = client.get("/passport/delegations")
    assert delegations_response.status_code == 200
    delegations = delegations_response.json()
    assert delegations
    delegation = delegations[0]
    assert delegation["status"] == "confirmed"
    assert delegation["provider"] == "x402"
    assert delegation["provider_intent_id"] == "0xtestsettlement"
    assert delegation["delegation_id"].startswith("dlg_")
    payment_intent_id = next(iter(main.PAYMENT_INTENTS.values())).id
    assert delegation["delegation_id"] != payment_intent_id

    single = client.get(f"/passport/delegations/{delegation['delegation_id']}")
    assert single.status_code == 200
    assert single.json()["delegation_id"] == delegation["delegation_id"]


def test_passport_sessions_remote_error_falls_back_to_local(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "X402_ENABLED", False)
    monkeypatch.setattr(main, "KITE_PASSPORT_REMOTE_ENABLED", True)
    monkeypatch.setattr(main, "KITE_PASSPORT_API_URL", "https://passport.example")
    monkeypatch.setattr(main, "KITE_PASSPORT_LOCAL_FALLBACK", True)

    def _list_sessions_fail(*args: object, **kwargs: object) -> list[dict[str, object]]:
        del args, kwargs
        raise KitePassportClientError("remote unavailable")

    monkeypatch.setattr(main.KITE_PASSPORT_CLIENT, "list_sessions", _list_sessions_fail)

    create = client.post(
        "/sessions",
        json={
            "budget_limit": 5,
            "valid_for_hours": 2,
            "allowed_providers": ["primary_serper"],
        },
    )
    assert create.status_code == 200

    response = client.get("/passport/sessions")
    assert response.status_code == 200
    assert response.json()


def test_passport_sessions_remote_error_is_502_when_fallback_disabled(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "KITE_PASSPORT_REMOTE_ENABLED", True)
    monkeypatch.setattr(main, "KITE_PASSPORT_API_URL", "https://passport.example")
    monkeypatch.setattr(main, "KITE_PASSPORT_LOCAL_FALLBACK", False)

    def _list_sessions_fail(*args: object, **kwargs: object) -> list[dict[str, object]]:
        del args, kwargs
        raise KitePassportClientError("remote unavailable")

    monkeypatch.setattr(main.KITE_PASSPORT_CLIENT, "list_sessions", _list_sessions_fail)

    response = client.get("/passport/sessions")
    assert response.status_code == 502
    assert "Kite Passport API error" in response.json()["detail"]


def test_create_passport_session_uses_local_fallback_when_remote_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "KITE_PASSPORT_REMOTE_ENABLED", True)
    monkeypatch.setattr(main, "KITE_PASSPORT_API_URL", "https://passport.example")
    monkeypatch.setattr(main, "KITE_PASSPORT_LOCAL_FALLBACK", True)

    def _create_session_fail(payload: dict[str, object]) -> dict[str, object]:
        del payload
        raise KitePassportClientError("remote unavailable")

    monkeypatch.setattr(main.KITE_PASSPORT_CLIENT, "create_session", _create_session_fail)

    response = client.post(
        "/passport/sessions",
        json={
            "max_total_spend_usd": 12,
            "valid_for_hours": 6,
            "wallet_address": "0x8794c866DB97E0E7c1a0E2CF51D3E1460cB37F9e",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["max_total_spend_usd"] == 12
    assert body["wallet_address"].lower() == "0x8794c866db97e0e7c1a0e2cf51d3e1460cb37f9e"
