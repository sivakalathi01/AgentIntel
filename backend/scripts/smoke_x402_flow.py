from __future__ import annotations

import argparse
import base64
import json
import sys
from dataclasses import dataclass

import httpx


@dataclass
class SmokeConfig:
    backend_url: str = "http://127.0.0.1:8000"
    timeout_seconds: float = 15.0
    user_id: str = "smoke-user"
    agent_id: str = "smoke-agent"
    budget_limit: float = 5.0


def require_ok(response: httpx.Response, context: str) -> dict:
    if not response.is_success:
        raise RuntimeError(f"{context} failed: {response.status_code} {response.text}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"{context} returned non-object JSON")
    return payload


def decode_payment_header(header_value: str, *, header_name: str) -> dict[str, object]:
    try:
        decoded = base64.b64decode(header_value.encode("utf-8")).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as error:
        raise RuntimeError(f"Invalid {header_name} header encoding: {error}") from error
    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Invalid {header_name} header JSON: {error}") from error
    if not isinstance(payload, dict):
        raise RuntimeError(f"Invalid {header_name} header: decoded payload must be an object")
    return payload


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke-test real x402 HTTP 402 challenge flow for /sessions.",
    )
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000", help="Backend base URL")
    parser.add_argument("--timeout", type=float, default=15.0, help="HTTP timeout in seconds")
    parser.add_argument("--user-id", default="smoke-user", help="User id used for session creation")
    parser.add_argument("--agent-id", default="smoke-agent", help="Agent id used for session creation")
    parser.add_argument("--budget", type=float, default=5.0, help="Session budget_limit in USD")
    parser.add_argument(
        "--payment-header",
        default="",
        help=(
            "Base64 x402 payment payload to send in PAYMENT-SIGNATURE on retry. "
            "If omitted, the script validates only the 402 challenge response."
        ),
    )
    parser.add_argument(
        "--payment-header-name",
        choices=["PAYMENT-SIGNATURE", "X-PAYMENT"],
        default="PAYMENT-SIGNATURE",
        help="Header name to use when retrying the paid request",
    )
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args(sys.argv[1:])
    cfg = SmokeConfig(
        backend_url=args.backend_url,
        timeout_seconds=args.timeout,
        user_id=args.user_id,
        agent_id=args.agent_id,
        budget_limit=args.budget,
    )
    client = httpx.Client(timeout=cfg.timeout_seconds)

    try:
        print("[1/3] Checking health endpoint...")
        health = require_ok(client.get(f"{cfg.backend_url}/health"), "health")
        if health.get("status") != "ok":
            raise RuntimeError(f"Unexpected health payload: {health}")

        print("[2/3] Requesting session creation without payment header...")
        session_request = {
            "user_id": cfg.user_id,
            "agent_id": cfg.agent_id,
            "budget_limit": cfg.budget_limit,
        }
        challenge = client.post(
            f"{cfg.backend_url}/sessions",
            json=session_request,
        )

        if challenge.status_code == 200:
            session = require_ok(challenge, "create session")
            print("SUCCESS")
            print("x402 appears disabled (session created without payment challenge)")
            print(f"session_id={session.get('id')}")
            return 0

        if challenge.status_code != 402:
            raise RuntimeError(
                "Expected 402 Payment Required or 200 when x402 is disabled, "
                f"received {challenge.status_code}: {challenge.text}"
            )

        payment_required_header = challenge.headers.get("PAYMENT-REQUIRED") or challenge.headers.get("X-PAYMENT-REQUIRED")
        if not payment_required_header:
            raise RuntimeError("402 response missing PAYMENT-REQUIRED/X-PAYMENT-REQUIRED header")

        challenge_payload = challenge.json()
        header_payload = decode_payment_header(payment_required_header, header_name="PAYMENT-REQUIRED")
        accepts = challenge_payload.get("accepts") or []
        first_accept = accepts[0] if isinstance(accepts, list) and accepts else {}
        print("x402 challenge received")
        print(f"network={first_accept.get('network')}")
        print(f"asset={first_accept.get('asset')}")
        print(f"amount={first_accept.get('amount')}")
        print(f"payTo={first_accept.get('payTo')}")
        print(f"challenge_error={challenge_payload.get('error')}")

        if header_payload.get("accepts") != challenge_payload.get("accepts"):
            raise RuntimeError("PAYMENT-REQUIRED header payload does not match response body accepts")

        if not args.payment_header:
            print("SUCCESS")
            print("Validated real 402 challenge. Provide --payment-header to test paid retry.")
            return 0

        print("[3/3] Retrying with provided x402 payment header...")
        paid_response = client.post(
            f"{cfg.backend_url}/sessions",
            json=session_request,
            headers={args.payment_header_name: args.payment_header},
        )
        paid = require_ok(paid_response, "paid session create")

        payment_response_header = paid_response.headers.get("PAYMENT-RESPONSE") or paid_response.headers.get("X-PAYMENT-RESPONSE")
        if payment_response_header:
            response_payload = decode_payment_header(payment_response_header, header_name="PAYMENT-RESPONSE")
            print(f"settlement_success={response_payload.get('success')}")
            print(f"settlement_transaction={response_payload.get('transaction')}")

        print("SUCCESS")
        print("Validated 402 challenge and paid retry")
        print(f"session_id={paid.get('id')}")
        return 0
    except Exception as error:
        print(f"FAILED: {error}")
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
