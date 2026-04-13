# AgentIntel — Architecture

## Project Overview

**Project Name:** AgentIntel
**Category:** Agentic Commerce
**Channel:** Kite AI — Agentic Commerce Track

**Description:**
AgentIntel is an autonomous AI research and procurement agent built on Kite. Users delegate a scoped, revocable budget, and the agent independently discovers information sources, pays for APIs or services, executes research tasks, and delivers a verified report with on-chain settlement and attestations on Kite.

---

## Architecture Diagram

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
│                FRONTEND — Next.js 14 on Vercel                  │
│                                                                 │
│  ┌─────────────────┐  ┌──────────────────┐  ┌───────────────┐  │
│  │  Task Submit UI │  │  Agent Live Feed │  │  Proof Panel  │  │
│  │  Budget Selector│  │  Payment Events  │  │  Kitescan     │  │
│  │  Session Viewer │  │  Agent Reasoning │  │  Tx Links     │  │
│  └─────────────────┘  └──────────────────┘  └───────────────┘  │
│                                                                 │
│  GraphQL polling → Goldsky     REST calls → FastAPI backend     │
│  wagmi/ethers.js → Kite RPC    RainbowKit → Wallet Signing      │
└──────┬───────────────────────────────────────┬─────────────────┘
       │ GraphQL                               │ REST / HTTP
       │                                       │
┌──────▼──────────────┐            ┌───────────▼─────────────────┐
│  GOLDSKY SUBGRAPH   │            │  BACKEND — FastAPI           │
│                     │            │  Google Cloud Run            │
│  Indexes Kite chain │            │                              │
│  contract events:   │            │  POST /tasks        → start  │
│  - Sessions created │            │  GET  /tasks/{id}   → status │
│  - Delegations      │            │  GET  /tasks/{id}/report     │
│  - Payments         │            │  POST /sessions     → create │
│  - Attestations     │            │  DELETE /sessions/{id} →revoke│
│                     │            │                              │
│  Exposes GraphQL API│            │  Google Secret Manager       │
│  for frontend       │            │  Google Cloud Storage        │
│                     │            │  Google Cloud Tasks (queue)  │
└─────────────────────┘            └───────────┬─────────────────┘
                                               │ Enqueue task job
                                   ┌───────────▼─────────────────┐
                                   │  AGENT LAYER                │
                                   │  Google ADK + Gemini        │
                                   │  Google Cloud Run (worker)  │
                                   │                             │
                                   │  ┌─────────────────────┐   │
                                   │  │  COORDINATOR AGENT  │   │
                                   │  │                     │   │
                                   │  │  - Reads goal       │   │
                                   │  │  - Creates plan     │   │
                                   │  │  - Selects tools    │   │
                                   │  │  - Calls kite.pay() │   │
                                   │  │  - Invokes paid APIs│   │
                                   │  │  - Assembles output │   │
                                   │  └──────────┬──────────┘   │
                                   │             │ passes output │
                                   │  ┌──────────▼──────────┐   │
                                   │  │  VERIFIER AGENT     │   │
                                   │  │                     │   │
                                   │  │  - Checks sources   │   │
                                   │  │  - Validates quality│   │
                                   │  │  - Approves/rejects │   │
                                   │  │  - Triggers attest  │   │
                                   │  └──────────┬──────────┘   │
                                   └─────────────┼───────────────┘
                                                 │
                    ┌────────────────────────────┼──────────────────────┐
                    │  PAID EXTERNAL APIs        │                      │
                    │                            │                      │
                    │  Exa / Serper (search) ◄───┤                      │
                    │  Clearbit / Hunter (enrich)┤                      │
                    │  Gemini API () ◄──┘                      │
                    └───────────────────────────────────────────────────┘
                                                 │
                                                 │ kite.pay() per action
                                                 │ Delegations + Sessions
                    ┌────────────────────────────▼──────────────────────┐
                    │  KITE AGENT PASSPORT                              │
                    │                                                   │
                    │  - Agent Identity (registered agent ID)           │
                    │  - Session (budget, time window, merchants)       │
                    │  - Delegation (per-payment signed intent)         │
                    │  - x402 facilitator integration                   │
                    │  - Service Payment API (provider redemption)      │
                    │                                                   │
                    │  KITE AA SDK                                      │
                    │  - Smart account (agent AA wallet)                │
                    │  - Agent Vault (spending rule enforcement)        │
                    │  - Gasless via Bundler (ERC-4337)                 │
                    └────────────────────────────┬──────────────────────┘
                                                 │ on-chain txs
                    ┌────────────────────────────▼──────────────────────┐
                    │  KITE CHAIN — Testnet (Chain ID 2368)             │
                    │  RPC: https://rpc-testnet.gokite.ai               │
                    │                                                   │
                    │  Records:                                         │
                    │  ✓ Session creation                               │
                    │  ✓ Per-step payment Delegations                   │
                    │  ✓ Spend amounts and provider addresses           │
                    │  ✓ Task completion attestation                    │
                    │  ✓ Evidence hash (report hash on-chain)           │
                    │  ✓ Verifier agent approval                        │
                    │                                                   │
                    │  Explorer: https://testnet.kitescan.ai            │
                    └───────────────────────────────────────────────────┘
```

---

## Data Flow Summary

| Step | Who | What |
|---|---|---|
| 1 | User | Connects wallet, sets goal and budget, signs Session |
| 2 | Frontend | Sends task to FastAPI backend |
| 3 | Cloud Tasks | Queues async agent job |
| 4 | Coordinator Agent | Plans research, calls paid APIs, pays via `kite.pay()` |
| 5 | Kite Agent Passport | Validates Delegation, processes payment on-chain |
| 6 | Verifier Agent | Reviews outputs, approves quality |
| 7 | Backend | Writes attestation + report hash to Kite chain |
| 8 | Goldsky | Indexes all on-chain events |
| 9 | Frontend | Polls Goldsky GraphQL, renders live feed and proof panel |
| 10 | User | Reads final report, inspects Kitescan tx links |

---

## Key Design Properties

- **No human steps 2–9**: Fully autonomous once task is submitted
- **Gas abstraction**: Bundler handles gas so users and agents do not manage gas manually
- **Scoped permissions**: Session constrains budget, time, and allowed merchants
- **Revocation**: User can cancel Session at any time, agent cannot exceed limits
- **Multi-agent**: Coordinator acts, Verifier validates before final attestation
- **On-chain proof**: Every payment and the final report hash are immutably recorded

---

## Technology Stack

### Blockchain / On-Chain

| Component | Technology |
|---|---|
| Chain | Kite AI Testnet (Chain ID 2368) |
| Agent Identity & Payments | Kite Agent Passport |
| Smart Account | Kite AA SDK (`gokite-aa-sdk`) |
| Chain Interaction | ethers.js (frontend) + web3.py (backend) |
| Gas Abstraction | Kite Bundler (ERC-4337) |

### Indexing & Data

| Component | Technology |
|---|---|
| On-chain indexing | Goldsky Subgraph |
| Subgraph API | GraphQL (polled from frontend) |
| Transaction explorer | Kitescan |

### AI / Agent Runtime

| Component | Technology |
|---|---|
| Agent Orchestration | Google Agent Development Kit (ADK) |
| LLM | Google Gemini (Vertex AI) |
| Coordinator Agent | ADK Agent with Gemini + tool calls |
| Verifier Agent | ADK Agent with validation tools |

### External Paid APIs

| Service | Purpose |
|---|---|
| Exa or Serper | Web search |
| Clearbit or Hunter.io | Company/contact enrichment |
| Gemini API | Synthesis and summarization |

### Backend

| Component | Technology |
|---|---|
| Runtime | Google Cloud Run |
| Framework | FastAPI (Python 3.11+) |
| Job queue | Google Cloud Tasks |
| Secrets | Google Secret Manager |
| Storage | Google Cloud Storage |

### Frontend

| Component | Technology |
|---|---|
| Framework | Next.js 14+ (App Router) |
| Hosting | Vercel |
| Wallet connect | RainbowKit + wagmi |
| Styling | Tailwind CSS |
| Data fetching | GraphQL polling (Goldsky subgraph) |
| Language | TypeScript |

---

## Repository Structure

```
agentintel/
├── frontend/        ← Next.js / TypeScript
├── backend/         ← FastAPI / Python
└── README.md
```

---

## Network References

| Network | Value |
|---|---|
| Chain name | KiteAI Testnet |
| Chain ID | 2368 |
| RPC URL | https://rpc-testnet.gokite.ai |
| Explorer | https://testnet.kitescan.ai |
| Faucet | https://faucet.gokite.ai |
| Bundler RPC | https://bundler-service.staging.gokite.ai/rpc/ |
| Settlement Token | 0x0fF5393387ad2f9f691FD6Fd28e07E3969e27e63 |
| Settlement Contract | 0x8d9FaD78d5Ce247aA01C140798B9558fd64a63E3 |
| ClientAgentVault Implementation | 0xB5AAFCC6DD4DFc2B80fb8BCcf406E1a2Fd559e23 |
