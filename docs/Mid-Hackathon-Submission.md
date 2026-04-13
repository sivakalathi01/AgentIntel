# AgentIntel — Mid-Hackathon Submission

## Project Name
**AgentIntel** — Autonomous AI Research Agent with On-Chain Payments on Kite

**Track:** Agentic Commerce — Kite L1 Testnet (Chain ID 2368)

---

## What It Does

AgentIntel is an autonomous AI research agent. A user gives it a natural-language research goal and a USD budget. The agent independently discovers information sources, pays for API services on-chain using the x402 payment protocol, executes multi-step research, and delivers a verified report — all with every payment recorded on the Kite blockchain.

**Core user journey:**
1. Connect wallet → set budget and goal
2. Sign a scoped spending session (Kite Agent Passport)
3. Agent autonomously runs research, paying for each tool call on-chain
4. Receive a structured report with sources, confidence score, and Kite transaction hash proof

**Agent runtime model:**
- Coordinator Agent handles planning, tool selection, and payment-triggering execution steps.
- Verifier Agent independently reviews evidence quality and source validity before finalization.

---

## What Was Built

### 1. Backend — FastAPI (Python)
`backend/app/main.py` · `backend/app/payments.py` · `backend/app/kite_pass.py` · `backend/app/passport_client.py`

The core API server powering agent lifecycle and payments:

- **Session management** — wallet-bound research sessions with budget limits, time windows, and provider allowlists. Enforced with EIP-191 wallet signature challenges to prevent unauthorized creation.
- **Task management** — queued/running/completed/failed task pipeline with live event streaming and structured report output (sources, summary, confidence %, cost breakdown per provider).
- **Real x402 payment enforcement** — every `POST /sessions` call requires an on-chain payment verified and settled via the Pieverse facilitator (`https://facilitator.pieverse.io/v2`) on Kite Testnet. This is a **real, non-simulated** payment flow:
  - Backend issues an HTTP 402 with canonical V2 payment requirements (EIP-712 domain metadata embedded in `accepts[].extra`)
  - Client constructs an EIP-712 `transferWithAuthorization` signed payload
  - Backend submits it to the facilitator for on-chain settlement
  - Settlement produces a real transaction hash recorded on Kite
- **Kite Pass access layer** — pass holders (allowlist or ERC-721/1155 on-chain balance) can bypass or get discounted payment requirements (configurable bypass/discount policy)
- **Kite Agent Passport alignment** — Passport-style session/delegation models and endpoints:
  - `GET/POST /passport/sessions` — budget delegation sessions
  - `GET/POST /passport/delegations` — per-payment signed intents with dedicated `dlg_<uuid>` IDs
  - Optional remote mode to forward to real Kite Passport API when credentials are provided, with configurable local fallback
- **Security hardening** — rate limiting per-wallet and per-IP for challenge issuance; challenge expiry and prune loops; signature normalization (`0x` prefix enforcement on all payment signatures); OWASP-compliant input validation throughout
- **PostgreSQL persistence** — full SQLAlchemy + Alembic schema for sessions, tasks, challenges, payment intents, payment events, security counters, and Kite Pass entitlements. In-memory fallback for local development
- **On-chain proof recording** — task completion writes a report hash attestation to Kite L1 via web3.py with explorer link in the response

### 2. Custom x402 Payment Token
`backend/scripts/deploy_x402_test_token.py`

A custom ERC-20 token (**Kite X402 USD**, contract `0x1b7425d288ea676FCBc65c29711fccF0B6D5c293`) was deployed to Kite Testnet with full `transferWithAuthorization` (EIP-3009) support — the exact signature scheme required by the x402 exact settlement flow. The standard testnet token (`Test USDT`) lacked `permit`/`transferWithAuthorization` support and could not be used for the real x402 exact flow; deploying and funding a compatible token was a required precondition for achieving real (non-mocked) payment settlement.

### 3. End-to-End x402 Buyer Script
`backend/scripts/x402_manual_buyer.py`

A fully self-contained buyer simulator that:
- Requests a session challenge and signs it
- Calls the service, receives an HTTP 402
- Constructs a canonical V2 x402 payment payload with EIP-712 `transferWithAuthorization` signature
- Submits payment and receives a real on-chain transaction hash

This was used to validate the real payment flow and diagnose signature issues (including fixing a missing `0x` prefix bug that caused all signature verifications to fail).

### 4. Frontend — Next.js 15
`frontend/`

- RainbowKit + wagmi for wallet connection to Kite Testnet
- Task submission UI with goal input and budget selection
- Session viewer and live agent activity feed
- Passport delegation viewer and on-chain proof/explorer links
- `x402-fetch` integration for client-side payment header construction

### 5. Operational Tooling and Tests
- `backend/scripts/smoke_x402_flow.py` — end-to-end smoke test against a live backend
- `backend/scripts/service_provider_readiness.py` — validates backend readiness as an x402 service provider
- `backend/X402_RUNBOOK.md` — step-by-step runbook for deploying, configuring, and validating the real payment flow
- **Test suites:**
  - `test_x402_payments.py` — full payment lifecycle, signature normalization, Kite Pass bypass, Passport endpoint mapping, delegation ID uniqueness, remote fallback behavior (12 passing)
  - `test_x402_manual_buyer.py` — buyer payload shape and signature prefix assertions
  - `test_kite_pass.py` — pass verification allowlist and on-chain balance check paths
  - `test_day5_security.py` — rate limiting, challenge expiry, replay protection

---

## Key Technical Decisions Made During Development

| Problem | What Was Done |
|---|---|
| Testnet token lacked `transferWithAuthorization` | Deployed a custom ERC-20 with EIP-3009 support |
| Facilitator crashed on malformed payload | Switched to canonical V2 payload with embedded `accepted` object |
| EIP-712 domain mismatch at facilitator | Added domain metadata (`name`, `version`) to `accepts[].extra` |
| Signatures rejected — missing `0x` prefix | Fixed in buyer script; added backend decode-time normalization as safeguard |
| Passport API (REST) not yet available from Kite | Implemented local Passport view with feature-flagged remote mode + fallback; Passport write endpoints scaffold ready for when credentials are issued |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER / BROWSER                           │
│                                                                 │
│  1. Connect wallet (RainbowKit + wagmi)                        │
│  2. Submit research goal + set budget                          │
│  3. Sign Session approval (Agent Passport)                     │
│  4. Monitor live task progress + results                       │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTPS
┌──────────────────────────▼──────────────────────────────────────┐
│                FRONTEND — Next.js 15                            │
│                                                                 │
│  Task Submit UI · Agent Live Feed · Proof Panel                │
│  wagmi/viem → Kite RPC · RainbowKit → Wallet Signing           │
│  x402-fetch → Payment Header Construction                       │
└──────────────────────────┬──────────────────────────────────────┘
                           │ REST / HTTP
┌──────────────────────────▼──────────────────────────────────────┐
│  BACKEND — FastAPI (Python 3.11)                                │
│                                                                 │
│  POST /sessions        → x402 payment enforced session create  │
│  GET  /sessions/{id}   → session status                        │
│  POST /tasks           → queue research task                   │
│  GET  /tasks/{id}      → task status + live events             │
│  GET  /tasks/{id}/report → structured report + proof           │
│  GET/POST /passport/sessions    → Passport session lifecycle   │
│  GET/POST /passport/delegations → per-payment delegation IDs   │
│  POST /kite-pass/verify → on-chain pass check                  │
│                                                                 │
│  PostgreSQL (SQLAlchemy + Alembic) · Gemini API (google-genai) │
│  web3.py → Kite RPC proof writes                               │
└──────────┬────────────────────────────┬────────────────────────┘
           │ verify + settle            │ on-chain proof write
           ▼                            ▼
┌──────────────────────┐   ┌────────────────────────────────────┐
│  PIEVERSE FACILITATOR│   │  KITE L1 TESTNET (Chain ID 2368)   │
│  /v2/verify          │   │  RPC: https://rpc-testnet.gokite.ai│
│  /v2/settle          │   │                                    │
│                      │   │  Records:                          │
│  Real on-chain EIP-712│  │  ✓ Session creation                │
│  transferWithAuth    │   │  ✓ Per-step payment Delegations    │
│  execution           │   │  ✓ Task completion attestation     │
└──────────────────────┘   │  ✓ Report hash (on-chain)         │
                           │  Explorer: testnet.kitescan.ai     │
                           └────────────────────────────────────┘
```

---

## Kite Integration Points

| Integration | Status |
|---|---|
| Kite L1 Testnet RPC (Chain ID 2368) | ✅ Live |
| Real x402 verify + settle via Pieverse facilitator | ✅ Live — real tx hashes produced |
| EIP-712 `transferWithAuthorization` payment token | ✅ Deployed on Kite Testnet (`0x1b7425d288ea676FCBc65c29711fccF0B6D5c293`) |
| On-chain proof attestation (report hash) | ✅ Live — Kitescan explorer links in API response |
| Kite Agent Passport aligned session/delegation model | ✅ Implemented locally with dedicated `dlg_<uuid>` IDs |
| Remote Passport API (when Kite issues credentials) | 🔧 Scaffolded, feature-flagged, ready to enable |
| Kite Pass (ERC-721/1155 balance check + allowlist) | ✅ Live with bypass/discount policy |

---

## How To Run

```powershell
# Backend
cd backend
cp .env.example .env        # fill in keys
python -m uvicorn app.main:app --reload

# Real end-to-end payment test
python scripts/x402_manual_buyer.py --budget 1

# Tests (all suites)
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONPATH='.'
pytest tests/ -q

# Frontend
cd frontend
npm install
npm run dev
```

---

## Stack Summary

| Layer | Technologies |
|---|---|
| Backend | Python 3.11, FastAPI, SQLAlchemy, PostgreSQL, Alembic, web3.py, eth-account, httpx, Google Gemini (`google-genai`), Pydantic, pytest |
| Frontend | Next.js 15, TypeScript, RainbowKit, wagmi, viem, `x402-fetch` |
| Chain | Kite L1 Testnet — EVM compatible, Chain ID 2368, 1-second block time |
| Payment protocol | x402 V2, EIP-712, EIP-3009 (`transferWithAuthorization`), EIP-4337 (AA wallet) |
| Facilitator | Pieverse (`https://facilitator.pieverse.io/v2`) |
| Explorer | `https://testnet.kitescan.ai` |
| Faucet | `https://faucet.gokite.ai` |
