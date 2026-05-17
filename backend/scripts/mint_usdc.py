#!/usr/bin/env python3
"""Mint USDC to a target wallet on Kite testnet using raw JSON-RPC."""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

import requests
from eth_account import Account
from web3 import Web3


USDC_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
        ],
        "name": "mint",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]


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
        raise ValueError("KITE_PRIVATE_KEY not set")
    return cleaned if cleaned.startswith("0x") else f"0x{cleaned}"


def rpc_call(session: requests.Session, rpc_url: str, method: str, params: list[Any], timeout: int = 20) -> Any:
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            response = session.post(rpc_url, json=payload, timeout=timeout)
            response.raise_for_status()
            body = response.json()
            if "error" in body:
                raise RuntimeError(f"RPC {method} failed: {json.dumps(body['error'])}")
            return body["result"]
        except (requests.RequestException, ValueError, KeyError, RuntimeError) as error:
            last_error = error
            if attempt == 5:
                break
            print(f"RPC {method} attempt {attempt}/5 failed: {error}")
            time.sleep(attempt)
    raise RuntimeError(f"RPC {method} failed after 5 attempts: {last_error}")


def hex_to_int(value: str) -> int:
    return int(value, 16)


def get_balance(contract: Any, session: requests.Session, rpc_url: str, holder: str) -> int:
    call_data = contract.functions.balanceOf(holder)._encode_transaction_data()
    result = rpc_call(
        session,
        rpc_url,
        "eth_call",
        [{"to": contract.address, "data": call_data}, "latest"],
    )
    return hex_to_int(result)


def wait_for_receipt(session: requests.Session, rpc_url: str, tx_hash: str, timeout_seconds: int = 180) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        receipt = rpc_call(session, rpc_url, "eth_getTransactionReceipt", [tx_hash], timeout=30)
        if receipt is not None:
            return receipt
        time.sleep(2)
    raise TimeoutError(f"Timed out waiting for receipt: {tx_hash}")


def main() -> int:
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    env = parse_env_file(env_path)

    rpc_url = os.getenv("KITE_RPC_URL") or env.get("KITE_RPC_URL", "https://rpc-testnet.gokite.ai")
    private_key = normalize_private_key(os.getenv("KITE_PRIVATE_KEY") or env.get("KITE_PRIVATE_KEY", ""))
    chain_id = int(os.getenv("KITE_CHAIN_ID") or env.get("KITE_CHAIN_ID", "2368"))
    usdc_contract = Web3.to_checksum_address("0x0309764915AFC7a2a7CDd1E64c58a57c1F1705E3")
    recipient = Web3.to_checksum_address("0x8794c866DB97E0E7c1a0E2CF51D3E1460cB37F9e")
    amount_human = 1_000_000
    decimals = 6
    amount_atomic = amount_human * 10**decimals

    account = Account.from_key(private_key)
    contract = Web3().eth.contract(address=usdc_contract, abi=USDC_ABI)
    session = requests.Session()

    try:
        print("Probing RPC...")
        client_version = rpc_call(session, rpc_url, "web3_clientVersion", [], timeout=20)
        print(f"RPC OK: {client_version}")

        print(f"\nMinter account: {account.address}")
        print(f"USDC contract: {usdc_contract}")
        print(f"Recipient: {recipient}")
        print(f"Amount: {amount_human:,} USDC ({amount_atomic:,} atomic units)")

        balance_before = get_balance(contract, session, rpc_url, recipient)
        print(f"\nBalance before: {balance_before / 10**decimals:,.2f} USDC")

        nonce = hex_to_int(rpc_call(session, rpc_url, "eth_getTransactionCount", [account.address, "pending"]))
        latest_gas_price = hex_to_int(rpc_call(session, rpc_url, "eth_gasPrice", []))
        mint_data = contract.functions.mint(recipient, amount_atomic)._encode_transaction_data()

        tx = {
            "type": 2,
            "chainId": chain_id,
            "nonce": nonce,
            "to": usdc_contract,
            "value": 0,
            "data": mint_data,
            "gas": 3_000_000,
            "maxPriorityFeePerGas": latest_gas_price,
            "maxFeePerGas": latest_gas_price * 2,
        }

        print("\nSigning and sending transaction...")
        signed = Account.sign_transaction(tx, private_key)
        tx_hash = rpc_call(session, rpc_url, "eth_sendRawTransaction", [Web3.to_hex(signed.raw_transaction)])
        print(f"Mint transaction sent: {tx_hash}")
        print("Waiting for confirmation...")

        receipt = wait_for_receipt(session, rpc_url, tx_hash)
        if hex_to_int(receipt["status"]) != 1:
            raise RuntimeError(f"Mint transaction reverted: {json.dumps(receipt)}")

        balance_after = get_balance(contract, session, rpc_url, recipient)
        print(f"\nBalance after: {balance_after / 10**decimals:,.2f} USDC")
        print(f"\nSUCCESS: Minted {amount_human:,} USDC to {recipient}")
        print(f"Transaction: https://testnet.kitescan.ai/tx/{tx_hash}")
        return 0
    except Exception as error:
        print(f"FAILED: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
