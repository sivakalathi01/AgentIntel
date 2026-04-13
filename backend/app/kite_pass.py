from __future__ import annotations

import logging
from dataclasses import dataclass

from web3 import Web3

logger = logging.getLogger(__name__)

# Minimal ABI fragments needed for balance queries
_ERC721_BALANCE_ABI = [
    {
        "inputs": [{"name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    }
]

_ERC1155_BALANCE_ABI = [
    {
        "inputs": [
            {"name": "account", "type": "address"},
            {"name": "id", "type": "uint256"},
        ],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    }
]


@dataclass
class KitePassCheckResult:
    has_pass: bool
    source: str


class KitePassVerifier:
    """Verifier for Kite Pass ownership.

    Supports two modes:

    - **allowlist** (default): fast dev/staging mode; checks a configured set
      of wallet addresses.
    - **onchain**: production mode; calls ``balanceOf`` on an ERC-721 or
      ERC-1155 contract via an RPC endpoint.  Falls back gracefully to
      reporting no pass on RPC errors, recording ``source="onchain_error"``.

    When *both* ``rpc_url`` and ``contract_address`` are provided, on-chain
    verification is used.  Wallets in ``allowlist`` always receive a pass
    regardless of mode — useful for dev overrides in production.
    """

    def __init__(
        self,
        *,
        enabled: bool,
        allowlist: set[str] | None = None,
        rpc_url: str = "",
        contract_address: str = "",
        token_standard: str = "erc721",
        token_id: int = 0,
    ) -> None:
        self.enabled = enabled
        self.allowlist: set[str] = {
            item.lower() for item in (allowlist or set()) if item.strip()
        }
        self.rpc_url = rpc_url
        self.contract_address = contract_address
        self.token_standard = token_standard.lower()
        self.token_id = token_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def has_pass(self, wallet_address: str) -> KitePassCheckResult:
        if not self.enabled:
            return KitePassCheckResult(has_pass=False, source="disabled")

        normalized = wallet_address.lower()

        # Allowlist always wins — acts as an admin / dev-override bypass.
        if normalized in self.allowlist:
            return KitePassCheckResult(has_pass=True, source="allowlist")

        # On-chain check when RPC + contract are both configured.
        if self.rpc_url and self.contract_address:
            return self._check_onchain(normalized)

        # Pure allowlist mode — wallet is not in the list.
        return KitePassCheckResult(has_pass=False, source="allowlist_miss")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_onchain(self, wallet_address: str) -> KitePassCheckResult:
        """Call ``balanceOf`` on the configured ERC-721/1155 contract."""
        try:
            w3 = Web3(Web3.HTTPProvider(self.rpc_url))
            checksum_wallet = Web3.to_checksum_address(wallet_address)
            checksum_contract = Web3.to_checksum_address(self.contract_address)

            if self.token_standard == "erc1155":
                contract = w3.eth.contract(address=checksum_contract, abi=_ERC1155_BALANCE_ABI)
                balance: int = contract.functions.balanceOf(checksum_wallet, self.token_id).call()
            else:
                contract = w3.eth.contract(address=checksum_contract, abi=_ERC721_BALANCE_ABI)
                balance = contract.functions.balanceOf(checksum_wallet).call()

            has = int(balance) > 0
            return KitePassCheckResult(
                has_pass=has,
                source="onchain" if has else "onchain_miss",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Kite Pass on-chain check failed for %s — falling back to no-pass: %s",
                wallet_address,
                exc,
            )
            return KitePassCheckResult(has_pass=False, source="onchain_error")
