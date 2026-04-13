from __future__ import annotations

import argparse
from dataclasses import dataclass

import httpx


@dataclass
class ReadinessConfig:
    backend_url: str
    facilitator_url: str
    expected_network: str
    timeout_seconds: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Service provider readiness checks for Kite x402 integration.",
    )
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000", help="Backend base URL")
    parser.add_argument("--facilitator-url", default="https://facilitator.pieverse.io/v2", help="Facilitator base URL")
    parser.add_argument("--expected-network", default="eip155:2368", help="Expected network id in x402 accepts")
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout in seconds")
    return parser.parse_args()


def must(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    args = parse_args()
    cfg = ReadinessConfig(
        backend_url=args.backend_url.rstrip("/"),
        facilitator_url=args.facilitator_url.rstrip("/"),
        expected_network=args.expected_network,
        timeout_seconds=args.timeout,
    )

    with httpx.Client(timeout=cfg.timeout_seconds, follow_redirects=True) as client:
        print("[1/4] Checking backend health...")
        health = client.get(f"{cfg.backend_url}/health")
        must(health.status_code == 200, f"health failed: {health.status_code} {health.text}")

        print("[2/4] Checking facilitator supported networks...")
        supported = client.get(f"{cfg.facilitator_url}/supported")
        must(supported.status_code == 200, f"facilitator supported failed: {supported.status_code} {supported.text}")
        supported_payload = supported.json()
        kinds = supported_payload.get("kinds") if isinstance(supported_payload, dict) else None
        must(isinstance(kinds, list), "facilitator supported payload missing kinds[]")
        network_ids = {
            item.get("network")
            for item in kinds
            if isinstance(item, dict) and isinstance(item.get("network"), str)
        }
        must(cfg.expected_network in network_ids, f"expected network {cfg.expected_network} not in facilitator kinds: {sorted(network_ids)}")

        print("[3/4] Verifying 402 payment challenge from backend...")
        session_req = {
            "user_id": "readiness-user",
            "agent_id": "readiness-agent",
            "budget_limit": 5.0,
        }
        challenge = client.post(f"{cfg.backend_url}/sessions", json=session_req)
        must(challenge.status_code == 402, f"expected 402, got {challenge.status_code}: {challenge.text}")
        challenge_payload = challenge.json()
        accepts = challenge_payload.get("accepts") if isinstance(challenge_payload, dict) else None
        must(isinstance(accepts, list) and len(accepts) > 0, "402 payload missing accepts[]")
        first = accepts[0]
        must(isinstance(first, dict), "accepts[0] must be an object")
        must(first.get("network") == cfg.expected_network, f"accepts[0].network mismatch: {first.get('network')}")
        must(first.get("asset"), "accepts[0].asset missing")
        must(first.get("payTo"), "accepts[0].payTo missing")

        print("[4/4] Kite Service Payment API configuration check...")
        print("Kite Service Payment API callback is configured via backend/.env:")
        print("  KITE_SERVICE_PAYMENT_API_ENABLED=true|false")
        print("  KITE_SERVICE_PAYMENT_API_URL=<your-endpoint>")
        print("  KITE_SERVICE_PAYMENT_API_KEY=<optional bearer token>")

    print("SUCCESS")
    print("Service-provider prerequisites look healthy for challenge and facilitator discovery.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
