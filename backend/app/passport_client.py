from __future__ import annotations

from dataclasses import dataclass

import httpx


class KitePassportClientError(RuntimeError):
    pass


@dataclass
class KitePassportClient:
    base_url: str
    api_key: str = ""
    timeout_seconds: int = 15

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _get(self, path: str, params: dict[str, str] | None = None) -> object:
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        try:
            response = httpx.get(url, headers=self._headers(), params=params, timeout=float(self.timeout_seconds))
            response.raise_for_status()
        except Exception as error:  # noqa: BLE001
            raise KitePassportClientError(str(error)) from error

        data = response.json()
        # Accept either raw payloads or wrappers like {"data": ...}.
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return data

    def _post(self, path: str, payload: dict[str, object]) -> object:
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        try:
            response = httpx.post(url, headers=self._headers(), json=payload, timeout=float(self.timeout_seconds))
            response.raise_for_status()
        except Exception as error:  # noqa: BLE001
            raise KitePassportClientError(str(error)) from error

        data = response.json()
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return data

    def list_sessions(self, wallet_address: str | None = None) -> list[dict[str, object]]:
        params = {"walletAddress": wallet_address} if wallet_address else None
        data = self._get("sessions", params=params)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return [item for item in data["items"] if isinstance(item, dict)]
        raise KitePassportClientError("Unexpected sessions response shape")

    def get_session(self, session_id: str) -> dict[str, object]:
        data = self._get(f"sessions/{session_id}")
        if isinstance(data, dict):
            return data
        raise KitePassportClientError("Unexpected session response shape")

    def create_session(self, payload: dict[str, object]) -> dict[str, object]:
        data = self._post("sessions", payload=payload)
        if isinstance(data, dict):
            return data
        raise KitePassportClientError("Unexpected create session response shape")

    def list_delegations(self, session_id: str | None = None) -> list[dict[str, object]]:
        params = {"sessionId": session_id} if session_id else None
        data = self._get("delegations", params=params)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return [item for item in data["items"] if isinstance(item, dict)]
        raise KitePassportClientError("Unexpected delegations response shape")

    def get_delegation(self, delegation_id: str) -> dict[str, object]:
        data = self._get(f"delegations/{delegation_id}")
        if isinstance(data, dict):
            return data
        raise KitePassportClientError("Unexpected delegation response shape")

    def create_delegation(self, payload: dict[str, object]) -> dict[str, object]:
        data = self._post("delegations", payload=payload)
        if isinstance(data, dict):
            return data
        raise KitePassportClientError("Unexpected create delegation response shape")
