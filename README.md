# AgentIntel

AgentIntel is an autonomous, multi-agent research system with scoped on-chain payments on Kite Testnet.

## Demo in 2 Minutes

Use these steps for a fast judge walkthrough.

### 1. Start Backend

```powershell
cd backend
python -m uvicorn app.main:app --reload
```

### 2. Start Frontend

```powershell
cd frontend
npm install
npm run dev
```

### 3. Trigger Real Payment Flow

```powershell
cd backend
python scripts/x402_manual_buyer.py --budget 1
```

Expected result:

- Session creation succeeds after 402 challenge/retry
- Settlement returns success and transaction hash
- Payment is processed through facilitator on Kite Testnet

### 4. Verify Multi-Agent and Delegation Outputs

- Check task/session endpoints to see lifecycle state changes
- Check Passport-style delegation/session endpoints
- Confirm final task output includes report and trace metadata

## Judge Checklist

- Multi-agent architecture is active (Coordinator + Verifier roles)
- x402 payment is real (verify + settle), not mocked
- Payment path enforces budgeted session creation
- Passport-style delegation model is implemented (`dlg_<uuid>`)
- Security controls exist (challenge, replay/rate limiting, signature normalization)

It combines:

- Multi-agent execution (Coordinator + Verifier)
- Real x402 payment enforcement and settlement
- Kite Pass / Passport-aligned access and delegation flows
- Traceable outcomes with payment and proof metadata

## Project Overview

Users provide a research goal and budget. AgentIntel executes research autonomously, pays for required service access via x402, and returns a structured report with verifiable execution context.

Primary use case:

- Agentic commerce workflows where an AI agent must spend under strict budget and policy controls.

## Multi-Agent Architecture

AgentIntel uses two specialized agents:

- Coordinator Agent
- Responsibilities: decompose goals, choose tools/providers, trigger paid calls, assemble outputs.

- Verifier Agent
- Responsibilities: validate source quality and evidence completeness, approve/reject final output.

This separation provides better reliability than a single-agent flow by enforcing an explicit quality gate before finalization.

## End-to-End Flow

1. User connects wallet and creates a scoped session.
2. Backend enforces payment requirements by returning HTTP 402 with x402 requirements.
3. Buyer/agent signs EIP-712 authorization payload.
4. Request is retried with payment header.
5. Facilitator verifies and settles payment on Kite Testnet.
6. Task runs through Coordinator and Verifier agent stages.
7. Report is returned with execution and payment traceability.

## Implemented Features

- Real x402 verify + settle integration (not mocked)
- Canonical x402 V2 payload handling
- EIP-712 domain metadata support for exact settlement
- Signature normalization safeguards
- Session / Task lifecycle APIs
- Passport-style sessions and delegations APIs
- Dedicated delegation IDs (dlg_<uuid>) for Passport mapping
- Optional remote Passport mode with local fallback
- Kite Pass entitlement checks (allowlist and on-chain contract mode)
- Payment intent and event persistence
- Security controls (challenge expiry, pruning, wallet/IP rate limits)
- Test suite for payment, buyer, pass, and security behavior

## Technology Stack

- Backend: FastAPI, SQLAlchemy, Alembic, PostgreSQL, web3.py, httpx, eth-account, Pydantic
- Frontend: Next.js, TypeScript, RainbowKit, wagmi, viem
- Agent runtime: Google Gemini integration
- Payments: x402 + Pieverse facilitator
- Chain: KiteAI Testnet (EVM, Chain ID 2368)

## Repository Structure

- frontend: Next.js application
- backend: FastAPI APIs, payments, scripts, tests
- docs: architecture and submission documentation

## Quick Start

### 1. Backend

```powershell
cd backend
copy .env.example .env
python -m uvicorn app.main:app --reload
```

### 2. Frontend

```powershell
cd frontend
npm install
npm run dev
```

### 3. Validate Real x402 Flow

```powershell
cd backend
python scripts/x402_manual_buyer.py --budget 1
```

## Configuration Notes

Important environment groups are in backend/.env:

- x402 payment flow configuration
- Kite Pass policy and cache controls
- Passport remote mode flags
- Database and security hardening values

If Passport API credentials are not available yet:

- Keep KITE_PASSPORT_REMOTE_ENABLED=false
- Keep KITE_PASSPORT_LOCAL_FALLBACK=true

## API Surface (Selected)

- POST /sessions
- GET /sessions/{session_id}
- DELETE /sessions/{session_id}
- POST /tasks
- GET /tasks/{task_id}
- GET /tasks/{task_id}/report
- POST /kite-pass/verify
- GET /passport/sessions
- POST /passport/sessions
- GET /passport/delegations
- POST /passport/delegations

## Testing

Run backend tests:

```powershell
cd backend
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONPATH='.'
pytest tests/ -q
```

Core coverage includes:

- x402 verify/settle lifecycle
- buyer payload and signature formatting
- passport mapping and fallback behavior
- kite pass policy behavior
- security challenge and rate-limit protections

## Network References

- Chain: KiteAI Testnet
- Chain ID: 2368
- RPC: https://rpc-testnet.gokite.ai
- Explorer: https://testnet.kitescan.ai
- Faucet: https://faucet.gokite.ai
- Facilitator: https://facilitator.pieverse.io/v2

## Current Status and Limitations

- Real x402 payment path is working and validated.
- Passport remote API mode is scaffolded and feature-flagged.
- Remote Passport credentials are required to enable live API mode.
- Local Passport-mapped mode remains available as fallback.

## Documentation

- Detailed architecture: docs/Architecture.md
- Mid-hackathon write-up: docs/Mid-Hackathon-Submission.md
