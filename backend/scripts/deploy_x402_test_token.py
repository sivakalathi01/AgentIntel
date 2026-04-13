from __future__ import annotations

import json
import os

from eth_account import Account
from solcx import compile_source, install_solc, set_solc_version
from web3 import Web3


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


def main() -> int:
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    env = parse_env_file(env_path)

    rpc_url = env.get("KITE_RPC_URL", "https://rpc-testnet.gokite.ai")
    private_key = normalize_private_key(env.get("KITE_PRIVATE_KEY", ""))

    source = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract KiteX402Token {
    string public name;
    string public symbol;
    uint8 public immutable decimals = 18;
    uint256 public totalSupply;

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    mapping(address => mapping(bytes32 => bool)) private _authorizationStates;

    bytes32 public immutable DOMAIN_SEPARATOR;
    bytes32 public constant TRANSFER_WITH_AUTHORIZATION_TYPEHASH = keccak256(
        "TransferWithAuthorization(address from,address to,uint256 value,uint256 validAfter,uint256 validBefore,bytes32 nonce)"
    );

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);

    constructor(string memory name_, string memory symbol_, address initialHolder, uint256 initialSupply) {
        name = name_;
        symbol = symbol_;

        uint256 chainId;
        assembly {
            chainId := chainid()
        }

        DOMAIN_SEPARATOR = keccak256(
            abi.encode(
                keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"),
                keccak256(bytes(name_)),
                keccak256(bytes("1")),
                chainId,
                address(this)
            )
        );

        _mint(initialHolder, initialSupply);
    }

    function transfer(address to, uint256 value) external returns (bool) {
        _transfer(msg.sender, to, value);
        return true;
    }

    function approve(address spender, uint256 value) external returns (bool) {
        allowance[msg.sender][spender] = value;
        emit Approval(msg.sender, spender, value);
        return true;
    }

    function transferFrom(address from, address to, uint256 value) external returns (bool) {
        uint256 current = allowance[from][msg.sender];
        require(current >= value, "insufficient allowance");
        unchecked {
            allowance[from][msg.sender] = current - value;
        }
        emit Approval(from, msg.sender, allowance[from][msg.sender]);
        _transfer(from, to, value);
        return true;
    }

    function authorizationState(address authorizer, bytes32 nonce) external view returns (bool) {
        return _authorizationStates[authorizer][nonce];
    }

    function transferWithAuthorization(
        address from,
        address to,
        uint256 value,
        uint256 validAfter,
        uint256 validBefore,
        bytes32 nonce,
        bytes calldata signature
    ) external {
        require(block.timestamp > validAfter, "not yet valid");
        require(block.timestamp < validBefore, "expired");
        require(!_authorizationStates[from][nonce], "authorization used");
        require(signature.length == 65, "invalid signature length");

        bytes32 structHash = keccak256(
            abi.encode(
                TRANSFER_WITH_AUTHORIZATION_TYPEHASH,
                from,
                to,
                value,
                validAfter,
                validBefore,
                nonce
            )
        );
        bytes32 digest = keccak256(abi.encodePacked("\\x19\\x01", DOMAIN_SEPARATOR, structHash));
        address signer = _recover(digest, signature);
        require(signer != address(0) && signer == from, "invalid signature");

        _authorizationStates[from][nonce] = true;
        _transfer(from, to, value);
    }

    function _recover(bytes32 digest, bytes calldata signature) internal pure returns (address signer) {
        bytes32 r;
        bytes32 s;
        uint8 v;
        assembly {
            r := calldataload(signature.offset)
            s := calldataload(add(signature.offset, 32))
            v := byte(0, calldataload(add(signature.offset, 64)))
        }
        if (v < 27) {
            v += 27;
        }
        signer = ecrecover(digest, v, r, s);
    }

    function _transfer(address from, address to, uint256 value) internal {
        require(to != address(0), "transfer to zero");
        uint256 fromBalance = balanceOf[from];
        require(fromBalance >= value, "insufficient balance");
        unchecked {
            balanceOf[from] = fromBalance - value;
        }
        balanceOf[to] += value;
        emit Transfer(from, to, value);
    }

    function _mint(address to, uint256 value) internal {
        require(to != address(0), "mint to zero");
        totalSupply += value;
        balanceOf[to] += value;
        emit Transfer(address(0), to, value);
    }
}
"""

    install_solc("0.8.20")
    set_solc_version("0.8.20")

    compiled = compile_source(source, output_values=["abi", "bin"])
    _, iface = compiled.popitem()

    abi = iface["abi"]
    bytecode = iface["bin"]

    account = Account.from_key(private_key)
    w3 = Web3(Web3.HTTPProvider(rpc_url))

    if not w3.is_connected():
        raise RuntimeError(f"Could not connect to RPC endpoint: {rpc_url}")

    nonce = w3.eth.get_transaction_count(account.address)
    chain_id = w3.eth.chain_id
    gas_price = w3.eth.gas_price

    token_name = "Kite X402 USD"
    token_symbol = "KXUSD"
    initial_supply = 10**28

    contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx = contract.constructor(token_name, token_symbol, account.address, initial_supply).build_transaction(
        {
            "from": account.address,
            "nonce": nonce,
            "chainId": chain_id,
            "gas": 3_500_000,
            "maxFeePerGas": gas_price * 2,
            "maxPriorityFeePerGas": gas_price,
        }
    )

    signed = w3.eth.account.sign_transaction(tx, private_key=private_key)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)

    if receipt.status != 1:
        raise RuntimeError("Deployment transaction failed")

    deployed_address = receipt.contractAddress
    deployed = w3.eth.contract(address=deployed_address, abi=abi)

    result = {
        "address": deployed_address,
        "tx": tx_hash.hex(),
        "name": deployed.functions.name().call(),
        "symbol": deployed.functions.symbol().call(),
        "version": "1",
        "buyer": account.address,
        "buyer_balance": str(deployed.functions.balanceOf(account.address).call()),
    }

    out_path = os.path.join(os.path.dirname(__file__), "..", ".tmp", "deployed_x402_token.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)

    print(json.dumps(result, indent=2))
    print(f"WROTE: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
