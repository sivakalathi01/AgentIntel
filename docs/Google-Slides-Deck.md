# AgentIntel Presentation Deck (Google Slides)

## Slide 1: Title
- AgentIntel
- Autonomous Multi-Agent Research with Real On-Chain x402 Payments
- Kite AI Hackathon Submission
- Team: [Your Team Name]

Speaker note:
- AgentIntel is a production-style agentic commerce system where AI agents can execute paid actions safely under user-defined budget controls.

## Slide 2: Problem
- AI agents can discover and reason, but payment execution is often unsafe or mocked.
- Typical gaps:
  - No scoped spending controls
  - No verifiable payment trail
  - No quality gate before returning results

Speaker note:
- The key gap is trust. If an autonomous agent spends money, users need scoped controls, auditable evidence, and reliable output quality.

## Slide 3: Solution Overview
- AgentIntel combines:
  - Multi-agent execution
  - Real x402 payment settlement on Kite Testnet
  - Passport-style session and delegation lifecycle
  - Traceable report + payment metadata

Speaker note:
- The central idea is to separate planning/execution from verification while forcing payments through a real on-chain protocol.

## Slide 4: Multi-Agent Architecture (Core Differentiator)
- Coordinator Agent:
  - Breaks goal into steps
  - Selects tools/providers
  - Triggers paid operations
  - Assembles draft output
- Verifier Agent:
  - Validates source quality
  - Checks evidence completeness
  - Approves/rejects final output

Speaker note:
- This two-agent architecture reduces hallucination and low-quality output risk by inserting a dedicated verification stage before final response.

## Slide 5: End-to-End Flow
1. User sets goal + budget
2. Backend returns HTTP 402 x402 requirement
3. Buyer/agent signs EIP-712 authorization
4. Facilitator verify + settle on Kite Testnet
5. Coordinator executes task
6. Verifier validates and approves
7. Final report returned with payment traceability

Speaker note:
- The critical point: settlement is real, not simulated. We obtain settlement responses including transaction identifiers.

## Slide 6: Real Payment Proof
- Network: Kite Testnet (Chain ID 2368)
- Facilitator: Pieverse /v2 verify + settle
- Exact scheme: EIP-712 transferWithAuthorization
- Implemented safeguards:
  - Canonical V2 payload
  - Domain metadata forwarding
  - Signature normalization guard

Speaker note:
- We solved real integration blockers and moved from failing mock-like behavior to end-to-end successful settlement.

## Slide 7: Kite Passport + Delegations
- Implemented Passport-style APIs:
  - /passport/sessions
  - /passport/delegations
- Dedicated delegation IDs: dlg_<uuid>
- Remote mode scaffolded with local fallback for resilience

Speaker note:
- This ensures our payment lifecycle maps cleanly to Passport semantics and is ready for live remote API mode when credentials are available.

## Slide 8: Security and Control
- Wallet-bound challenge flow
- Per-wallet and per-IP rate limiting
- Session-based budget scope and revocation
- Pass-aware policy support (bypass/discount)
- Payment intent/event persistence for audit trail

Speaker note:
- The design prioritizes bounded autonomy. Agent power increases, but user risk stays controlled.

## Slide 9: Tech Stack
- Backend: FastAPI, SQLAlchemy, PostgreSQL, web3.py
- Frontend: Next.js, TypeScript, RainbowKit, wagmi
- Agent Runtime: Gemini-backed orchestration
- Payment: x402 + Pieverse facilitator
- Chain: Kite AI Testnet

Speaker note:
- We built the system as a realistic integration stack, not a thin demo-only prototype.

## Slide 10: Live Demo Plan (2 Minutes)
- Start backend + frontend
- Run x402 buyer script with budget=1
- Show successful session creation after 402 challenge
- Show delegation/session endpoints
- Show final task report and trace metadata

Speaker note:
- Keep the demo focused on three proof points: multi-agent flow, real settlement, and verifiable output.

## Slide 11: Results Achieved
- Real x402 settlement path validated
- Multi-agent workflow integrated and documented
- Passport-aligned model and APIs completed
- Regression tests passing for critical payment and delegation flows

Speaker note:
- We can confidently claim real payment capability with architecture-level safeguards and test coverage.

## Slide 12: Roadmap
- Enable live Passport remote mode with issued API credentials
- Expand verifier scoring and policy thresholds
- Add richer observability dashboards
- Prepare mainnet-ready configuration profile

Speaker note:
- The next milestone is enabling remote Passport endpoints and tightening production observability.
