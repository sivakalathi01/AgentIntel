from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import time
from dataclasses import dataclass

import httpx
from eth_account import Account
from web3 import Web3


@dataclass
class BuyerConfig:
    backend_url: str
    user_id: str
    agent_id: str
    budget_limit: float
    private_key: str
    domain_name: str
    domain_version: str
    rpc_url: str
    timeout_seconds: float


def parse_env_file(path: str) -> dict[str, str]:
    result: dict[str, str] = {}
    if not os.path.exists(path):
        return result
    with open(path, "r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def normalize_private_key(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Private key cannot be empty")
    return cleaned if cleaned.startswith("0x") else f"0x{cleaned}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manual x402 buyer for Kite service-provider flow using EIP-712 TransferWithAuthorization.",
    )
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000", help="Backend base URL")
    parser.add_argument("--user-id", default="buyer-user", help="user_id for /sessions")
    parser.add_argument("--agent-id", default="buyer-agent", help="agent_id for /sessions")
    parser.add_argument("--budget", type=float, default=5.0, help="budget_limit for /sessions")
    parser.add_argument("--private-key", default="", help="Buyer private key (hex). Defaults to KITE_PRIVATE_KEY")
    parser.add_argument("--domain-name", default="", help="Override EIP-712 domain name")
    parser.add_argument("--domain-version", default="", help="Override EIP-712 domain version")
    parser.add_argument("--rpc-url", default="", help="RPC URL used for token capability preflight")
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout in seconds")
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


def encode_b64_json(payload: dict[str, object]) -> str:
    return base64.b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("utf-8")


def token_supports_typed_authorization(*, rpc_url: str, asset: str, timeout_seconds: float) -> bool:
    # x402 exact on EVM needs an EIP-712 authorization primitive from the token.
    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": timeout_seconds}))
    if not w3.is_connected():
        raise RuntimeError(f"Could not connect to RPC endpoint: {rpc_url}")

    token = Web3.to_checksum_address(asset)
    code = w3.eth.get_code(token).hex()
    # EIP-2612 permit() and common EIP-3009 transferWithAuthorization() variants.
    return any(
        selector in code
        for selector in (
            "d505accf",  # permit(address,address,uint256,uint256,uint8,bytes32,bytes32)
            "8fcbaf0c",  # permit(address,address,uint256,uint256,bytes)
            "7f2eecc3",  # transferWithAuthorization(...,bytes)
            "c55897bf",  # transferWithAuthorization(...,uint8,bytes32,bytes32)
            "cf092995",  # transferWithAuthorization(address,address,uint256,uint256,uint256,bytes32,bytes)
            "e3ee160e",  # transferWithAuthorization(address,address,uint256,uint256,uint256,bytes32,uint8,bytes32,bytes32)
        )
    )


def build_payment_payload(
    *,
    private_key: str,
    chain_id: int,
    asset: str,
    pay_to: str,
    amount: str,
    max_timeout_seconds: int,
    domain_name: str,
    domain_version: str,
    accepted_requirement: dict[str, object],
) -> dict[str, object]:
    account = Account.from_key(private_key)
    now = int(time.time())
    message_data = {
        "from": account.address,
        "to": pay_to,
        "value": int(amount),
        "validAfter": now - 600,
        "validBefore": now + max_timeout_seconds,
        "nonce": "0x" + secrets.token_hex(32),
    }

    message_types = {
        "TransferWithAuthorization": [
            {"name": "from", "type": "address"},
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
            {"name": "validAfter", "type": "uint256"},
            {"name": "validBefore", "type": "uint256"},
            {"name": "nonce", "type": "bytes32"},
        ]
    }
    domain_data = {
        "name": domain_name,
        "version": domain_version,
        "chainId": chain_id,
        "verifyingContract": asset,
    }

    signed = Account.sign_typed_data(
        private_key=private_key,
        domain_data=domain_data,
        message_types=message_types,
        message_data=message_data,
    )
    signature_hex = signed.signature.hex()
    if not signature_hex.startswith("0x"):
        signature_hex = f"0x{signature_hex}"

    return {
        "x402Version": 2,
        "payload": {
            "signature": signature_hex,
            "authorization": {
                "from": message_data["from"],
                "to": message_data["to"],
                "value": str(message_data["value"]),
                "validAfter": str(message_data["validAfter"]),
                "validBefore": str(message_data["validBefore"]),
                "nonce": message_data["nonce"],
            },
        },
        "accepted": accepted_requirement,
    }


def main() -> int:
    args = parse_args()
    env = parse_env_file(os.path.join(os.path.dirname(__file__), "..", ".env"))

    private_key_raw = args.private_key or os.getenv("KITE_PRIVATE_KEY", "") or env.get("KITE_PRIVATE_KEY", "")
    if not private_key_raw:
        print("FAILED: missing private key. Pass --private-key or set KITE_PRIVATE_KEY.")
        return 1

    try:
        cfg = BuyerConfig(
            backend_url=args.backend_url,
            user_id=args.user_id,
            agent_id=args.agent_id,
            budget_limit=args.budget,
            private_key=normalize_private_key(private_key_raw),
            domain_name=args.domain_name,
            domain_version=args.domain_version,
            rpc_url=args.rpc_url or os.getenv("KITE_RPC_URL", "").strip() or env.get("KITE_RPC_URL", "https://rpc-testnet.gokite.ai"),
            timeout_seconds=args.timeout,
        )
    except ValueError as error:
        print(f"FAILED: {error}")
        return 1

    session_body = {
        "user_id": cfg.user_id,
        "agent_id": cfg.agent_id,
        "budget_limit": cfg.budget_limit,
    }

    with httpx.Client(timeout=cfg.timeout_seconds) as client:
        challenge = client.post(f"{cfg.backend_url}/sessions", json=session_body)
        if challenge.status_code == 200:
            print("SUCCESS")
            print("x402 is disabled; session created without payment")
            print(challenge.text)
            return 0
        if challenge.status_code != 402:
            print(f"FAILED: expected 402, got {challenge.status_code}: {challenge.text}")
            return 1

        challenge_payload = challenge.json()
        accepts = challenge_payload.get("accepts")
        if not isinstance(accepts, list) or not accepts:
            print("FAILED: 402 response missing accepts[]")
            return 1
        req = accepts[0]
        if not isinstance(req, dict):
            print("FAILED: accepts[0] is not an object")
            return 1

        network = str(req.get("network", ""))
        if not network.startswith("eip155:"):
            print(f"FAILED: unsupported network format for this script: {network}")
            return 1
        try:
            chain_id = int(network.split(":", 1)[1])
        except ValueError:
            print(f"FAILED: invalid chain id in network: {network}")
            return 1

        try:
            required_amount = str(req.get("maxAmountRequired") or req.get("amount") or "0")
            extra = req.get("extra") if isinstance(req.get("extra"), dict) else {}
            domain_name = str(extra.get("name") or cfg.domain_name or "").strip()
            domain_version = str(extra.get("version") or cfg.domain_version or "").strip()

            if not domain_name or not domain_version:
                print("FAILED: payment requirements missing EIP-712 domain metadata in extra.name/extra.version")
                print("Provide --domain-name and --domain-version, or configure backend to include them.")
                return 1

            asset = str(req.get("asset", "")).strip()
            if not asset:
                print("FAILED: payment requirements missing asset address")
                return 1

            if not token_supports_typed_authorization(
                rpc_url=cfg.rpc_url,
                asset=asset,
                timeout_seconds=cfg.timeout_seconds,
            ):
                print("WARNING: token authorization selectors not recognized by heuristic; attempting payment anyway")
                print(f"asset={asset}")

            accepted_req = {
                "scheme": str(req.get("scheme", "exact") or "exact"),
                "network": network,
                "asset": asset,
                "amount": required_amount,
                "maxAmountRequired": required_amount,
                "payTo": str(req.get("payTo", "")),
                "maxTimeoutSeconds": int(req.get("maxTimeoutSeconds", 300)),
                "resource": req.get("resource"),
                "description": req.get("description"),
                "mimeType": req.get("mimeType"),
                "merchantName": req.get("merchantName"),
                "outputSchema": req.get("outputSchema"),
                "extra": {
                    "name": domain_name,
                    "version": domain_version,
                    **extra,
                },
            }
            accepted_req = {k: v for k, v in accepted_req.items() if v is not None}

            payment_payload = build_payment_payload(
                private_key=cfg.private_key,
                chain_id=chain_id,
                asset=asset,
                pay_to=str(req.get("payTo", "")),
                amount=required_amount,
                max_timeout_seconds=int(req.get("maxTimeoutSeconds", 300)),
                domain_name=domain_name,
                domain_version=domain_version,
                accepted_requirement=accepted_req,
            )
        except Exception as error:
            print(f"FAILED: could not build payment payload: {error}")
            return 1

        payment_header = encode_b64_json(payment_payload)
        paid = client.post(
            f"{cfg.backend_url}/sessions",
            json=session_body,
            headers={"PAYMENT-SIGNATURE": payment_header},
        )

    if paid.status_code == 200:
        print("SUCCESS")
        print("Paid session created")
        print(paid.text)
        payment_response_header = paid.headers.get("PAYMENT-RESPONSE") or paid.headers.get("X-PAYMENT-RESPONSE")
        if payment_response_header:
            decoded = decode_b64_json("PAYMENT-RESPONSE", payment_response_header)
            print("payment_response=")
            print(json.dumps(decoded, indent=2))
        return 0

    if paid.status_code == 402:
        print("FAILED: payment rejected by verify/settle")
        print(paid.text)
        return 1

    print(f"FAILED: paid retry returned {paid.status_code}: {paid.text}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
