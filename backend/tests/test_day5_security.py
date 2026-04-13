from __future__ import annotations

from collections.abc import Generator

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient

from app import main


def _sign_text(private_key: bytes, message: str) -> str:
    signature = Account.sign_message(encode_defunct(text=message), private_key=private_key)
    return signature.signature.hex()


@pytest.fixture(autouse=True)
def reset_in_memory_state(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    main.TASKS.clear()
    main.SESSIONS.clear()
    main.SESSION_CHALLENGES.clear()
    main.TASK_CHALLENGES.clear()
    main.SESSION_CHALLENGE_REQUESTS.clear()
    main.TASK_CHALLENGE_REQUESTS.clear()
    main.SESSION_CHALLENGE_REQUESTS_IP.clear()
    main.TASK_CHALLENGE_REQUESTS_IP.clear()

    for key in main.SECURITY_METRICS:
        main.SECURITY_METRICS[key] = 0

    monkeypatch.setattr(main, "X402_ENABLED", False)

    # Prevent background task execution from hitting external APIs during tests.
    def _drop_task(coro):
        coro.close()
        return None

    monkeypatch.setattr(main.asyncio, "create_task", _drop_task)
    yield


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(main.app) as test_client:
        yield test_client


def test_unsigned_session_and_task_flow_still_works(client: TestClient) -> None:
    session_response = client.post(
        "/sessions",
        json={
            "budget_limit": 5,
            "valid_for_hours": 2,
            "allowed_providers": ["primary_serper"],
        },
    )
    assert session_response.status_code == 200
    session_json = session_response.json()
    assert session_json["wallet_address"] is None

    task_response = client.post(
        "/tasks",
        json={
            "goal": "unsigned session task",
            "budget": 1.0,
            "session_id": session_json["id"],
        },
    )
    assert task_response.status_code == 200


def test_signed_session_requires_signed_task(client: TestClient) -> None:
    account = Account.create()

    challenge_response = client.post(
        "/sessions/challenge",
        json={"wallet_address": account.address},
    )
    assert challenge_response.status_code == 200
    challenge = challenge_response.json()

    signature = _sign_text(account.key, challenge["message"])
    create_session_response = client.post(
        "/sessions",
        json={
            "budget_limit": 5,
            "valid_for_hours": 2,
            "allowed_providers": ["primary_serper"],
            "wallet_address": account.address,
            "challenge_id": challenge["challenge_id"],
            "signature": signature,
        },
    )
    assert create_session_response.status_code == 200
    session = create_session_response.json()
    assert session["wallet_address"].lower() == account.address.lower()

    unsigned_task_response = client.post(
        "/tasks",
        json={
            "goal": "should fail unsigned task",
            "budget": 1.0,
            "session_id": session["id"],
        },
    )
    assert unsigned_task_response.status_code == 400
    assert "requires task signature" in unsigned_task_response.json()["detail"].lower()

    task_challenge_response = client.post(
        "/tasks/challenge",
        json={
            "session_id": session["id"],
            "goal": "signed task",
            "budget": 1.0,
            "wallet_address": account.address,
        },
    )
    assert task_challenge_response.status_code == 200
    task_challenge = task_challenge_response.json()

    task_signature = _sign_text(account.key, task_challenge["message"])
    signed_task_response = client.post(
        "/tasks",
        json={
            "goal": "signed task",
            "budget": 1.0,
            "session_id": session["id"],
            "wallet_address": account.address,
            "challenge_id": task_challenge["challenge_id"],
            "signature": task_signature,
        },
    )
    assert signed_task_response.status_code == 200


def test_session_challenge_replay_is_blocked(client: TestClient) -> None:
    account = Account.create()

    challenge_response = client.post(
        "/sessions/challenge",
        json={"wallet_address": account.address},
    )
    assert challenge_response.status_code == 200
    challenge = challenge_response.json()

    signature = _sign_text(account.key, challenge["message"])

    first_use_response = client.post(
        "/sessions",
        json={
            "budget_limit": 5,
            "valid_for_hours": 2,
            "allowed_providers": ["primary_serper"],
            "wallet_address": account.address,
            "challenge_id": challenge["challenge_id"],
            "signature": signature,
        },
    )
    assert first_use_response.status_code == 200

    replay_response = client.post(
        "/sessions",
        json={
            "budget_limit": 5,
            "valid_for_hours": 2,
            "allowed_providers": ["primary_serper"],
            "wallet_address": account.address,
            "challenge_id": challenge["challenge_id"],
            "signature": signature,
        },
    )
    assert replay_response.status_code == 400
    assert "already used" in replay_response.json()["detail"].lower()


def test_session_challenge_wallet_rate_limit(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "SESSION_CHALLENGE_RATE_LIMIT", 2)

    account = Account.create()
    statuses = []
    for _ in range(3):
        response = client.post(
            "/sessions/challenge",
            json={"wallet_address": account.address},
        )
        statuses.append(response.status_code)

    assert statuses == [200, 200, 429]

    metrics = client.get("/metrics/security")
    assert metrics.status_code == 200
    payload = metrics.json()
    assert payload["counters"]["session_challenge_rate_limited_wallet"] >= 1
