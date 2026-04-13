from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

import httpx


@dataclass
class X402VerifyResult:
    is_valid: bool
    payer: str | None = None
    invalid_reason: str | None = None
    invalid_message: str | None = None
    raw: dict[str, object] | None = None


@dataclass
class X402SettleResult:
    success: bool
    payer: str | None = None
    transaction: str | None = None
    network: str | None = None
    error_reason: str | None = None
    error_message: str | None = None
    raw: dict[str, object] | None = None


class X402FacilitatorClient:
    def __init__(
        self,
        *,
        facilitator_url: str,
        network: str,
        asset: str,
        pay_to: str,
        merchant_name: str,
        max_timeout_seconds: int,
        token_decimals: int,
    ) -> None:
        self.facilitator_url = facilitator_url.rstrip("/")
        self.network = network
        self.asset = asset
        self.pay_to = pay_to
        self.merchant_name = merchant_name
        self.max_timeout_seconds = max_timeout_seconds
        self.token_decimals = token_decimals

    @staticmethod
    def _extract_payment_fields(payment_payload: dict[str, object]) -> tuple[dict[str, object], str, str]:
        # Support both guide-style tokens and x402-style wrapped payloads.
        if isinstance(payment_payload.get("authorization"), dict):
            authorization = payment_payload["authorization"]
            signature = str(payment_payload.get("signature", "")).strip()
            network = str(payment_payload.get("network", "")).strip()
        else:
            nested = payment_payload.get("payload")
            authorization = nested.get("authorization") if isinstance(nested, dict) else None
            signature = str((nested or {}).get("signature", "")).strip() if isinstance(nested, dict) else ""
            network = str(payment_payload.get("network", "")).strip()

        if not isinstance(authorization, dict):
            raise ValueError("Invalid x402 payment: missing authorization object")
        if not signature:
            raise ValueError("Invalid x402 payment: missing signature")
        if not network:
            raise ValueError("Invalid x402 payment: missing network")

        return authorization, signature, network

    @staticmethod
    def _to_json_safe(obj: object) -> object:
        """Convert to JSON-safe format, turning big ints (> 2^53) into strings."""
        return json.loads(
            json.dumps(obj, default=lambda x: str(x) if isinstance(x, int) and x > 2**53 else x)
        )

    def usd_to_atomic(self, amount_usd: float) -> str:
        scaled = Decimal(str(amount_usd)) * (Decimal(10) ** self.token_decimals)
        return str(int(scaled.quantize(Decimal("1"), rounding=ROUND_HALF_UP)))

    def build_payment_requirements(
        self,
        *,
        resource: str,
        amount_usd: float,
        description: str,
        mime_type: str,
        output_schema: dict[str, object] | None = None,
        extra: dict[str, object] | None = None,
    ) -> dict[str, object]:
        atomic_amount = self.usd_to_atomic(amount_usd)
        requirements: dict[str, object] = {
            "scheme": "exact",
            "network": self.network,
            "maxAmountRequired": atomic_amount,
            "amount": atomic_amount,
            "asset": self.asset,
            "payTo": self.pay_to,
            "resource": resource,
            "description": description,
            "mimeType": mime_type,
            "maxTimeoutSeconds": self.max_timeout_seconds,
            "merchantName": self.merchant_name,
        }
        if output_schema is not None:
            requirements["outputSchema"] = output_schema
        if extra is not None:
            requirements["extra"] = extra
        return requirements

    def build_payment_required(self, *, requirements: dict[str, object], error: str) -> dict[str, object]:
        return {
            "x402Version": 2,
            "error": error,
            "accepts": [requirements],
        }

    def encode_header(self, payload: dict[str, object]) -> str:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        return base64.b64encode(body).decode("ascii")

    def decode_payment_header(self, header_value: str) -> dict[str, object]:
        padded = header_value + "=" * (-len(header_value) % 4)
        try:
            raw = base64.b64decode(padded.encode("ascii"))
            payload = json.loads(raw.decode("utf-8"))
        except Exception as error:  # noqa: BLE001
            raise ValueError(f"Invalid x402 payment header: {error}") from error
        if not isinstance(payload, dict):
            raise ValueError("Invalid x402 payment header: decoded payload must be an object")
        top_level_signature = payload.get("signature")
        if isinstance(top_level_signature, str) and top_level_signature and not top_level_signature.startswith("0x"):
            payload["signature"] = f"0x{top_level_signature}"
        nested = payload.get("payload")
        if isinstance(nested, dict):
            nested_signature = nested.get("signature")
            if isinstance(nested_signature, str) and nested_signature and not nested_signature.startswith("0x"):
                nested["signature"] = f"0x{nested_signature}"
        return payload

    async def verify(
        self,
        *,
        payment_payload: dict[str, object],
        payment_requirements: dict[str, object],
        x402_version: int,
    ) -> X402VerifyResult:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.post(
                f"{self.facilitator_url}/verify",
                json={
                    "x402Version": x402_version,
                    "paymentPayload": self._to_json_safe(payment_payload),
                    "paymentRequirements": self._to_json_safe(payment_requirements),
                },
            )
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Facilitator verify response must be an object")
        is_valid = bool(data.get("isValid"))
        payer = str(data.get("payer", "")).strip() or None
        invalid_reason = str(data.get("invalidReason", "")).strip() or None
        invalid_message = (
            str(data.get("invalidMessage", "")).strip()
            or str(data.get("error", "")).strip()
            or None
        )
        return X402VerifyResult(
            is_valid=is_valid,
            payer=payer,
            invalid_reason=invalid_reason,
            invalid_message=invalid_message,
            raw=data,
        )

    async def settle(
        self,
        *,
        payment_payload: dict[str, object],
        payment_requirements: dict[str, object],
        x402_version: int,
    ) -> X402SettleResult:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.post(
                f"{self.facilitator_url}/settle",
                json={
                    "x402Version": x402_version,
                    "paymentPayload": self._to_json_safe(payment_payload),
                    "paymentRequirements": self._to_json_safe(payment_requirements),
                },
            )
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Facilitator settle response must be an object")
        return X402SettleResult(
            success=bool(data.get("success")),
            payer=str(data.get("payer", "")).strip() or None,
            transaction=str(data.get("transaction", "")).strip() or None,
            network=str(data.get("network", "")).strip() or None,
            error_reason=str(data.get("errorReason", "")).strip() or None,
            error_message=(
                str(data.get("errorMessage", "")).strip()
                or str(data.get("error", "")).strip()
                or None
            ),
            raw=data,
        )
