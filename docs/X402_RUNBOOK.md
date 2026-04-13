# Real x402 Runbook (Kite Testnet)

## Prerequisites
- Backend virtual environment exists at .venv
- backend/.env contains KITE_PRIVATE_KEY and X402_PAY_TO
- Backend is running on http://127.0.0.1:8000

## 1) Deploy a funded compatible token
Run from backend/:

python scripts/deploy_x402_test_token.py

This writes deployment metadata to .tmp/deployed_x402_token.json.

## 2) Configure backend/.env
Set:

X402_ENABLED=true
X402_NETWORK=eip155:2368
X402_ASSET=<deployed token address>
X402_EIP712_DOMAIN_NAME=Kite X402 USD
X402_EIP712_DOMAIN_VERSION=1

## 3) Restart backend
PowerShell example:

Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess |
  Sort-Object -Unique |
  ForEach-Object { Stop-Process -Id $_ -Force }

& "c:\Work\DecentralizedAI\KiteAI\backend\.venv\Scripts\python.exe" -m uvicorn --app-dir "c:\Work\DecentralizedAI\KiteAI\backend" app.main:app --host 127.0.0.1 --port 8000

## 4) Verify 402 challenge
python scripts/x402_challenge_export.py --backend-url http://127.0.0.1:8000 --output .tmp/x402-challenge.json

Confirm accepts[0].asset and accepts[0].extra.name/version match .env.

## 5) Execute real payment
python scripts/x402_manual_buyer.py --backend-url http://127.0.0.1:8000 --budget 1

Expected successful output includes:
- SUCCESS
- Paid session created
- payment_response.success = true
- payment_response.transaction is a chain tx hash
