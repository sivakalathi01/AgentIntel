from __future__ import annotations

import argparse
import base64
import json
from dataclasses import dataclass
from pathlib import Path

import httpx


@dataclass
class ExportConfig:
    backend_url: str = "http://127.0.0.1:8000"
    timeout_seconds: float = 15.0
    user_id: str = "smoke-user"
    agent_id: str = "smoke-agent"
    budget_limit: float = 5.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Request x402 challenge from /sessions and export payload for buyer clients.",
    )
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000", help="Backend base URL")
    parser.add_argument("--timeout", type=float, default=15.0, help="HTTP timeout in seconds")
    parser.add_argument("--user-id", default="smoke-user", help="User id for session request")
    parser.add_argument("--agent-id", default="smoke-agent", help="Agent id for session request")
    parser.add_argument("--budget", type=float, default=5.0, help="budget_limit for session request")
    parser.add_argument(
        "--output",
        default="",
        help="Optional path to write pretty challenge JSON. If omitted, only stdout is used.",
    )
    return parser.parse_args()


def decode_b64_json(header_name: str, value: str) -> dict[str, object]:
    try:
        decoded = base64.b64decode(value.encode("utf-8")).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as error:
        raise RuntimeError(f"Invalid {header_name} encoding: {error}") from error
    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Invalid {header_name} JSON: {error}") from error
    if not isinstance(payload, dict):
        raise RuntimeError(f"Invalid {header_name}: decoded payload must be an object")
    return payload


def main() -> int:
    args = parse_args()
    cfg = ExportConfig(
        backend_url=args.backend_url,
        timeout_seconds=args.timeout,
        user_id=args.user_id,
        agent_id=args.agent_id,
        budget_limit=args.budget,
    )
    body = {
        "user_id": cfg.user_id,
        "agent_id": cfg.agent_id,
        "budget_limit": cfg.budget_limit,
    }

    with httpx.Client(timeout=cfg.timeout_seconds) as client:
        health = client.get(f"{cfg.backend_url}/health")
        if not health.is_success:
            print(f"FAILED: health failed: {health.status_code} {health.text}")
            return 1

        response = client.post(f"{cfg.backend_url}/sessions", json=body)

    if response.status_code == 200:
        print("x402 appears disabled: /sessions returned 200 without challenge")
        print(response.text)
        return 0

    if response.status_code != 402:
        print(f"FAILED: expected 402, got {response.status_code}: {response.text}")
        return 1

    header_value = response.headers.get("PAYMENT-REQUIRED") or response.headers.get("X-PAYMENT-REQUIRED")
    if not header_value:
        print("FAILED: missing PAYMENT-REQUIRED header")
        return 1

    body_payload = response.json()
    header_payload = decode_b64_json("PAYMENT-REQUIRED", header_value)

    if body_payload.get("accepts") != header_payload.get("accepts"):
        print("FAILED: header payload does not match response accepts")
        return 1

    first_accept = {}
    accepts = body_payload.get("accepts")
    if isinstance(accepts, list) and accepts:
        item = accepts[0]
        if isinstance(item, dict):
            first_accept = item

    export = {
        "status_code": response.status_code,
        "payment_required_header": header_value,
        "payment_required_decoded": header_payload,
        "request": body,
        "accept_summary": {
            "network": first_accept.get("network"),
            "asset": first_accept.get("asset"),
            "amount": first_accept.get("amount"),
            "payTo": first_accept.get("payTo"),
            "resource": first_accept.get("resource"),
        },
    }

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(export, indent=2), encoding="utf-8")
        print(f"WROTE: {output_path}")

    print("SUCCESS")
    print(json.dumps(export, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
