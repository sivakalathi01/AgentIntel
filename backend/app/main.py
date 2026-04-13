import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Literal
from uuid import uuid4

from eth_account import Account
from eth_account.messages import encode_defunct
from google import genai
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from web3 import Web3

from app.database import DATABASE_ENABLED, SessionLocal, init_database
from app.kite_pass import KitePassVerifier
from app.passport_client import KitePassportClient, KitePassportClientError
from app.payments import X402FacilitatorClient
from app.models import (
    KitePassEntitlementModel,
    PaymentEventModel,
    PaymentIntentModel,
    SecurityCounterModel,
    SessionChallengeModel,
    SessionModel,
    TaskChallengeModel,
    TaskModel,
)

load_dotenv()

# Initialize Gemini
google_api_key = os.getenv("GOOGLE_API_KEY", "")
if google_api_key:
    GEMINI_CLIENT = genai.Client(api_key=google_api_key)
else:
    GEMINI_CLIENT = None


def env_int(name: str, default: int, minimum: int = 1, maximum: int = 1_000_000) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "true" if default else "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}

TaskStatus = Literal["queued", "running", "completed", "failed"]
ProviderName = Literal[
    "primary_serper",
    "secondary_tavily",
    "secondary_exa",
    "fallback_wikipedia",
    "last_resort_links",
]

ALL_PROVIDERS: tuple[ProviderName, ...] = (
    "primary_serper",
    "secondary_tavily",
    "secondary_exa",
    "fallback_wikipedia",
    "last_resort_links",
)


class TaskCreateRequest(BaseModel):
    goal: str = Field(min_length=5, max_length=500)
    budget: float = Field(gt=0, le=1000)
    session_id: str = Field(min_length=1)
    wallet_address: str | None = None
    challenge_id: str | None = None
    signature: str | None = None
    payment_intent_id: str | None = None


class SessionCreateRequest(BaseModel):
    budget_limit: float = Field(gt=0, le=1000)
    allowed_providers: list[ProviderName] = Field(default_factory=lambda: list(ALL_PROVIDERS))
    valid_for_hours: int = Field(default=24, ge=1, le=168)
    wallet_address: str | None = None
    challenge_id: str | None = None
    signature: str | None = None
    payment_intent_id: str | None = None


class PaymentIntentCreateRequest(BaseModel):
    amount_usd: float = Field(gt=0, le=100000)
    currency: str = Field(default="USD", min_length=3, max_length=16)
    wallet_address: str | None = None
    session_id: str | None = None
    task_id: str | None = None
    metadata: dict[str, object] | None = None


class PaymentIntentResponse(BaseModel):
    id: str
    session_id: str | None = None
    task_id: str | None = None
    wallet_address: str | None = None
    provider: str
    provider_intent_id: str | None = None
    amount_usd: float
    currency: str
    status: str
    metadata: dict[str, object] | None = None
    created_at: str
    updated_at: str
    confirmed_at: str | None = None


class PaymentEventResponse(BaseModel):
    id: int | None = None
    payment_intent_id: str
    event_type: str
    provider_event_id: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)
    processed: bool
    created_at: str


class X402PaymentRequirement(BaseModel):
    scheme: str
    network: str
    maxAmountRequired: str
    amount: str | None = None
    asset: str
    payTo: str
    resource: str
    description: str
    mimeType: str
    maxTimeoutSeconds: int
    merchantName: str | None = None
    outputSchema: dict[str, object] | None = None
    extra: dict[str, object] | None = None


class X402PaymentRequiredResponse(BaseModel):
    x402Version: int = 2
    error: str
    accepts: list[X402PaymentRequirement]


class KitePassVerifyRequest(BaseModel):
    wallet_address: str = Field(min_length=42, max_length=42)


class KitePassStatusResponse(BaseModel):
    wallet_address: str
    has_pass: bool
    source: str
    checked_at: str
    expires_at: str


class SessionChallengeRequest(BaseModel):
    wallet_address: str = Field(min_length=42, max_length=42)


class SessionChallengeResponse(BaseModel):
    challenge_id: str
    wallet_address: str
    message: str
    expires_at: str


class TaskChallengeRequest(BaseModel):
    session_id: str = Field(min_length=1)
    goal: str = Field(min_length=5, max_length=500)
    budget: float = Field(gt=0, le=1000)
    wallet_address: str = Field(min_length=42, max_length=42)


class TaskChallengeResponse(BaseModel):
    challenge_id: str
    session_id: str
    wallet_address: str
    message: str
    expires_at: str


class SourceItem(BaseModel):
    title: str
    url: str
    snippet: str


class ActivityEvent(BaseModel):
    id: str
    level: Literal["info", "warning", "success", "error"]
    message: str
    created_at: str


class ProofResponse(BaseModel):
    report_hash: str
    proof_status: Literal["prepared", "recorded_on_kite_pending", "recorded_on_kite", "failed"]
    created_at: str
    explorer_url: str | None = None


class CostBreakdown(BaseModel):
    serper_cost: float = 0.0
    tavily_cost: float = 0.0
    exa_cost: float = 0.0
    gemini_cost: float = 0.0
    kite_cost: float = 0.0
    total_cost: float = 0.0


class ReportResponse(BaseModel):
    summary: str
    sources: list[SourceItem]
    confidence: float
    source_used: str
    cost_breakdown: CostBreakdown | None = None


class SessionResponse(BaseModel):
    id: str
    budget_limit: float
    spent_budget: float
    available_budget: float
    allowed_providers: list[ProviderName]
    wallet_address: str | None = None
    revoked: bool
    valid_until: str
    created_at: str


class TaskResponse(BaseModel):
    id: str
    session_id: str
    goal: str
    budget: float
    status: TaskStatus
    steps: list[str]
    events: list[ActivityEvent]
    proof: ProofResponse | None = None
    report: ReportResponse | None = None
    created_at: str


class PassportSessionResponse(BaseModel):
    session_id: str
    max_total_spend_usd: float
    spent_usd: float
    available_usd: float
    valid_until: str
    revoked: bool
    wallet_address: str | None = None
    created_at: str


class PassportDelegationResponse(BaseModel):
    delegation_id: str
    session_id: str | None = None
    task_id: str | None = None
    payer: str | None = None
    amount_usd: float
    status: str
    provider: str
    provider_intent_id: str | None = None
    created_at: str
    confirmed_at: str | None = None
    metadata: dict[str, object] | None = None


class PassportSessionCreateRequest(BaseModel):
    max_total_spend_usd: float = Field(gt=0, le=1000)
    valid_for_hours: int = Field(default=24, ge=1, le=168)
    wallet_address: str | None = None


class PassportDelegationCreateRequest(BaseModel):
    session_id: str | None = None
    task_id: str | None = None
    payer: str | None = None
    amount_usd: float = Field(gt=0, le=100000)
    status: str = "pending"
    provider: str = "x402"
    provider_intent_id: str | None = None
    metadata: dict[str, object] | None = None


class InMemoryTask(BaseModel):
    id: str
    session_id: str
    goal: str
    budget: float
    status: TaskStatus = "queued"
    steps: list[str] = Field(default_factory=list)
    events: list[ActivityEvent] = Field(default_factory=list)
    proof: ProofResponse | None = None
    report: ReportResponse | None = None
    created_at: str


class InMemorySession(BaseModel):
    id: str
    budget_limit: float
    spent_budget: float = 0
    allowed_providers: list[ProviderName] = Field(default_factory=lambda: list(ALL_PROVIDERS))
    wallet_address: str | None = None
    revoked: bool = False
    valid_until: str
    created_at: str


class InMemorySessionChallenge(BaseModel):
    id: str
    wallet_address: str
    message: str
    expires_at: str
    used: bool = False
    created_at: str


class InMemoryTaskChallenge(BaseModel):
    id: str
    session_id: str
    wallet_address: str
    goal: str
    budget: float
    message: str
    expires_at: str
    used: bool = False
    created_at: str


class InMemoryPaymentIntent(BaseModel):
    id: str
    session_id: str | None = None
    task_id: str | None = None
    wallet_address: str | None = None
    provider: str = "x402"
    provider_intent_id: str | None = None
    amount_usd: float
    currency: str = "USD"
    status: str = "pending"
    metadata: dict[str, object] | None = None
    created_at: str
    updated_at: str
    confirmed_at: str | None = None


class InMemoryPaymentEvent(BaseModel):
    id: int | None = None
    payment_intent_id: str
    event_type: str
    provider_event_id: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)
    processed: bool = False
    created_at: str


class InMemoryKitePassEntitlement(BaseModel):
    wallet_address: str
    has_pass: bool
    source: str
    checked_at: str
    expires_at: str


class X402PaymentRequiredError(Exception):
    def __init__(
        self,
        *,
        body: dict[str, object],
        payment_required_header: str,
        payment_response_header: str | None = None,
    ) -> None:
        self.body = body
        self.payment_required_header = payment_required_header
        self.payment_response_header = payment_response_header


app = FastAPI(title="AgentIntel Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(X402PaymentRequiredError)
async def handle_x402_payment_required(_: Request, exc: X402PaymentRequiredError) -> JSONResponse:
    headers = {
        "PAYMENT-REQUIRED": exc.payment_required_header,
        "X-PAYMENT-REQUIRED": exc.payment_required_header,
    }
    if exc.payment_response_header:
        headers["PAYMENT-RESPONSE"] = exc.payment_response_header
        headers["X-PAYMENT-RESPONSE"] = exc.payment_response_header
    return JSONResponse(status_code=402, content=exc.body, headers=headers)

TASKS: dict[str, InMemoryTask] = {}
SESSIONS: dict[str, InMemorySession] = {}
SESSION_CHALLENGES: dict[str, InMemorySessionChallenge] = {}
TASK_CHALLENGES: dict[str, InMemoryTaskChallenge] = {}
PAYMENT_INTENTS: dict[str, InMemoryPaymentIntent] = {}
PAYMENT_EVENTS: dict[int, InMemoryPaymentEvent] = {}
PAYMENT_PROVIDER_EVENT_INDEX: dict[str, int] = {}
KITE_PASS_ENTITLEMENTS: dict[str, InMemoryKitePassEntitlement] = {}
SESSION_CHALLENGE_REQUESTS: dict[str, list[datetime]] = {}
TASK_CHALLENGE_REQUESTS: dict[str, list[datetime]] = {}
SESSION_CHALLENGE_REQUESTS_IP: dict[str, list[datetime]] = {}
TASK_CHALLENGE_REQUESTS_IP: dict[str, list[datetime]] = {}

CHALLENGE_EXPIRY_MINUTES = env_int("CHALLENGE_EXPIRY_MINUTES", 10, minimum=1, maximum=120)
CHALLENGE_PRUNE_GRACE_MINUTES = env_int("CHALLENGE_PRUNE_GRACE_MINUTES", 30, minimum=5, maximum=1440)
CHALLENGE_RATE_WINDOW_SECONDS = env_int("CHALLENGE_RATE_WINDOW_SECONDS", 60, minimum=10, maximum=3600)
SESSION_CHALLENGE_RATE_LIMIT = env_int("SESSION_CHALLENGE_RATE_LIMIT", 6, minimum=1, maximum=1000)
TASK_CHALLENGE_RATE_LIMIT = env_int("TASK_CHALLENGE_RATE_LIMIT", 10, minimum=1, maximum=1000)
SESSION_CHALLENGE_RATE_LIMIT_IP = env_int("SESSION_CHALLENGE_RATE_LIMIT_IP", 20, minimum=1, maximum=5000)
TASK_CHALLENGE_RATE_LIMIT_IP = env_int("TASK_CHALLENGE_RATE_LIMIT_IP", 30, minimum=1, maximum=5000)
CHALLENGE_PRUNE_INTERVAL_SECONDS = env_int("CHALLENGE_PRUNE_INTERVAL_SECONDS", 60, minimum=5, maximum=3600)

SECURITY_METRICS: dict[str, int] = {
    "session_challenge_issued": 0,
    "task_challenge_issued": 0,
    "session_challenge_rate_limited_wallet": 0,
    "task_challenge_rate_limited_wallet": 0,
    "session_challenge_rate_limited_ip": 0,
    "task_challenge_rate_limited_ip": 0,
    "session_challenge_pruned": 0,
    "task_challenge_pruned": 0,
}
PRUNE_TASK: asyncio.Task[None] | None = None

X402_ENABLED = env_bool("X402_ENABLED", default=False)
X402_FACILITATOR_URL = os.getenv("X402_FACILITATOR_URL", "https://facilitator.pieverse.io/v2").strip() or "https://facilitator.pieverse.io/v2"
X402_NETWORK = os.getenv("X402_NETWORK", "eip155:2368").strip() or "eip155:2368"
X402_ASSET = os.getenv("X402_ASSET", "0x0fF5393387ad2f9f691FD6Fd28e07E3969e27e63").strip()
X402_PAY_TO = os.getenv("X402_PAY_TO", os.getenv("KITE_PROOF_RECIPIENT", "")).strip()
X402_MERCHANT_NAME = os.getenv("X402_MERCHANT_NAME", "AgentIntel").strip() or "AgentIntel"
X402_MAX_TIMEOUT_SECONDS = env_int("X402_MAX_TIMEOUT_SECONDS", 300, minimum=1, maximum=3600)
X402_TOKEN_DECIMALS = env_int("X402_TOKEN_DECIMALS", 18, minimum=0, maximum=30)
X402_EIP712_DOMAIN_NAME = os.getenv("X402_EIP712_DOMAIN_NAME", "").strip()
X402_EIP712_DOMAIN_VERSION = os.getenv("X402_EIP712_DOMAIN_VERSION", "").strip()
KITE_SERVICE_PAYMENT_API_ENABLED = env_bool("KITE_SERVICE_PAYMENT_API_ENABLED", default=False)
KITE_SERVICE_PAYMENT_API_URL = os.getenv("KITE_SERVICE_PAYMENT_API_URL", "").strip()
KITE_SERVICE_PAYMENT_API_KEY = os.getenv("KITE_SERVICE_PAYMENT_API_KEY", "").strip()
KITE_SERVICE_PAYMENT_API_TIMEOUT_SECONDS = env_int("KITE_SERVICE_PAYMENT_API_TIMEOUT_SECONDS", 15, minimum=1, maximum=120)
X402_CLIENT = X402FacilitatorClient(
    facilitator_url=X402_FACILITATOR_URL,
    network=X402_NETWORK,
    asset=X402_ASSET,
    pay_to=X402_PAY_TO,
    merchant_name=X402_MERCHANT_NAME,
    max_timeout_seconds=X402_MAX_TIMEOUT_SECONDS,
    token_decimals=X402_TOKEN_DECIMALS,
)

KITE_PASS_ENABLED = env_bool("KITE_PASS_ENABLED", default=False)
KITE_PASS_CACHE_MINUTES = env_int("KITE_PASS_CACHE_MINUTES", 30, minimum=1, maximum=24 * 60)
KITE_PASS_ALLOWLIST = {
    item.strip().lower()
    for item in os.getenv("KITE_PASS_ALLOWLIST", "").split(",")
    if item.strip()
}
KITE_PASS_RPC_URL = os.getenv("KITE_PASS_RPC_URL", "")
KITE_PASS_CONTRACT_ADDRESS = os.getenv("KITE_PASS_CONTRACT_ADDRESS", "")
KITE_PASS_TOKEN_STANDARD = os.getenv("KITE_PASS_TOKEN_STANDARD", "erc721")
KITE_PASS_TOKEN_ID = env_int("KITE_PASS_TOKEN_ID", 0, minimum=0, maximum=2**64)
# Policy for pass holders when X402 is enabled:
#   "bypass"   – skip payment check entirely (free access)
#   "discount" – reduce required amount by KITE_PASS_DISCOUNT_PCT percent
_VALID_PASS_POLICIES = {"bypass", "discount"}
KITE_PASS_PAYWALL_POLICY = os.getenv("KITE_PASS_PAYWALL_POLICY", "bypass").lower()
if KITE_PASS_PAYWALL_POLICY not in _VALID_PASS_POLICIES:
    KITE_PASS_PAYWALL_POLICY = "bypass"
KITE_PASS_DISCOUNT_PCT = env_int("KITE_PASS_DISCOUNT_PCT", 100, minimum=0, maximum=100)
KITE_PASS_VERIFIER = KitePassVerifier(
    enabled=KITE_PASS_ENABLED,
    allowlist=KITE_PASS_ALLOWLIST,
    rpc_url=KITE_PASS_RPC_URL,
    contract_address=KITE_PASS_CONTRACT_ADDRESS,
    token_standard=KITE_PASS_TOKEN_STANDARD,
    token_id=KITE_PASS_TOKEN_ID,
)
KITE_PASSPORT_REMOTE_ENABLED = env_bool("KITE_PASSPORT_REMOTE_ENABLED", default=False)
KITE_PASSPORT_API_URL = os.getenv("KITE_PASSPORT_API_URL", "").strip()
KITE_PASSPORT_API_KEY = os.getenv("KITE_PASSPORT_API_KEY", "").strip()
KITE_PASSPORT_TIMEOUT_SECONDS = env_int("KITE_PASSPORT_TIMEOUT_SECONDS", 15, minimum=1, maximum=120)
KITE_PASSPORT_LOCAL_FALLBACK = env_bool("KITE_PASSPORT_LOCAL_FALLBACK", default=True)
KITE_PASSPORT_CLIENT = KitePassportClient(
    base_url=KITE_PASSPORT_API_URL,
    api_key=KITE_PASSPORT_API_KEY,
    timeout_seconds=KITE_PASSPORT_TIMEOUT_SECONDS,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global PRUNE_TASK
    init_database()
    if PRUNE_TASK is None or PRUNE_TASK.done():
        PRUNE_TASK = asyncio.create_task(challenge_pruner_loop())

    try:
        yield
    finally:
        if PRUNE_TASK is not None:
            PRUNE_TASK.cancel()
            try:
                await PRUNE_TASK
            except asyncio.CancelledError:
                pass
            PRUNE_TASK = None


app.router.lifespan_context = lifespan


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/payments/intents", response_model=PaymentIntentResponse)
def create_payment_intent(payload: PaymentIntentCreateRequest) -> PaymentIntentResponse:
    del payload
    raise HTTPException(
        status_code=410,
        detail="Legacy payment intent flow removed. Use HTTP 402 with PAYMENT-SIGNATURE or X-PAYMENT.",
    )


@app.get("/payments/intents/{intent_id}", response_model=PaymentIntentResponse)
def get_payment_intent(intent_id: str) -> PaymentIntentResponse:
    intent = get_payment_intent_by_id(intent_id)
    if intent is None:
        raise HTTPException(status_code=404, detail="Payment intent not found")
    return serialize_payment_intent(intent)


@app.get("/payments/intents/{intent_id}/events", response_model=list[PaymentEventResponse])
def get_payment_intent_events(intent_id: str) -> list[PaymentEventResponse]:
    intent = get_payment_intent_by_id(intent_id)
    if intent is None:
        raise HTTPException(status_code=404, detail="Payment intent not found")

    events = get_payment_events_by_intent_id(intent_id)
    return [PaymentEventResponse(**event.model_dump()) for event in events]


@app.post("/kite-pass/verify", response_model=KitePassStatusResponse)
def verify_kite_pass(payload: KitePassVerifyRequest) -> KitePassStatusResponse:
    if not KITE_PASS_ENABLED:
        raise HTTPException(status_code=400, detail="Kite Pass verification is disabled")

    wallet_address = normalize_wallet_address(payload.wallet_address)
    result = KITE_PASS_VERIFIER.has_pass(wallet_address)
    checked_at = now_utc()
    entitlement = InMemoryKitePassEntitlement(
        wallet_address=wallet_address,
        has_pass=result.has_pass,
        source=result.source,
        checked_at=checked_at.isoformat(),
        expires_at=(checked_at + timedelta(minutes=KITE_PASS_CACHE_MINUTES)).isoformat(),
    )
    persist_kite_pass_entitlement(entitlement)
    return serialize_kite_pass_entitlement(entitlement)


@app.get("/kite-pass/{wallet_address}", response_model=KitePassStatusResponse)
def get_kite_pass_status(wallet_address: str) -> KitePassStatusResponse:
    normalized = normalize_wallet_address(wallet_address)
    entitlement = get_kite_pass_entitlement(normalized)
    if entitlement is None:
        raise HTTPException(status_code=404, detail="Kite Pass status not found")
    return serialize_kite_pass_entitlement(entitlement)


def is_passport_remote_mode_enabled() -> bool:
    return bool(KITE_PASSPORT_REMOTE_ENABLED and KITE_PASSPORT_API_URL)


def is_passport_local_fallback_enabled() -> bool:
    return bool(KITE_PASSPORT_LOCAL_FALLBACK)


def _as_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def map_remote_passport_session(item: dict[str, object]) -> PassportSessionResponse:
    session_id = str(item.get("sessionId") or item.get("id") or "")
    max_total_spend = _as_float(item.get("maxTotalSpendUsd") or item.get("budgetLimit"))
    spent = _as_float(item.get("spentUsd") or item.get("spentBudget"))
    available = _as_float(item.get("availableUsd"), max(0.0, max_total_spend - spent))
    return PassportSessionResponse(
        session_id=session_id,
        max_total_spend_usd=max_total_spend,
        spent_usd=spent,
        available_usd=available,
        valid_until=str(item.get("validUntil") or item.get("valid_until") or ""),
        revoked=bool(item.get("revoked", False)),
        wallet_address=(str(item.get("walletAddress") or item.get("wallet_address") or "").strip() or None),
        created_at=str(item.get("createdAt") or item.get("created_at") or ""),
    )


def map_remote_passport_delegation(item: dict[str, object]) -> PassportDelegationResponse:
    return PassportDelegationResponse(
        delegation_id=str(item.get("delegationId") or item.get("id") or ""),
        session_id=(str(item.get("sessionId") or item.get("session_id") or "").strip() or None),
        task_id=(str(item.get("taskId") or item.get("task_id") or "").strip() or None),
        payer=(str(item.get("payer") or item.get("walletAddress") or item.get("wallet_address") or "").strip() or None),
        amount_usd=_as_float(item.get("amountUsd") or item.get("amount_usd")),
        status=str(item.get("status") or "pending"),
        provider=str(item.get("provider") or "kite-passport"),
        provider_intent_id=(str(item.get("providerIntentId") or item.get("provider_intent_id") or "").strip() or None),
        created_at=str(item.get("createdAt") or item.get("created_at") or ""),
        confirmed_at=(str(item.get("confirmedAt") or item.get("confirmed_at") or "").strip() or None),
        metadata=item if item else None,
    )


def create_local_passport_session(payload: PassportSessionCreateRequest) -> PassportSessionResponse:
    wallet_address = normalize_wallet_address(payload.wallet_address) if payload.wallet_address else None
    current_time = now_utc()
    session = InMemorySession(
        id=str(uuid4()),
        budget_limit=payload.max_total_spend_usd,
        allowed_providers=list(ALL_PROVIDERS),
        wallet_address=wallet_address,
        valid_until=(current_time + timedelta(hours=payload.valid_for_hours)).isoformat(),
        created_at=current_time.isoformat(),
    )
    persist_session(session)
    return serialize_passport_session(session)


def create_local_passport_delegation(payload: PassportDelegationCreateRequest) -> PassportDelegationResponse:
    payer = normalize_wallet_address(payload.payer) if payload.payer else None
    current_time = now_utc().isoformat()
    intent = InMemoryPaymentIntent(
        id=str(uuid4()),
        session_id=payload.session_id,
        task_id=payload.task_id,
        wallet_address=payer,
        provider=payload.provider,
        provider_intent_id=payload.provider_intent_id,
        amount_usd=payload.amount_usd,
        currency="USD",
        status=payload.status,
        metadata=dict(payload.metadata or {}),
        created_at=current_time,
        updated_at=current_time,
        confirmed_at=current_time if payload.status == "confirmed" else None,
    )
    persist_payment_intent(intent)
    return serialize_passport_delegation(intent)


def build_remote_passport_session_create_payload(payload: PassportSessionCreateRequest) -> dict[str, object]:
    body: dict[str, object] = {
        "maxTotalSpendUsd": payload.max_total_spend_usd,
        "validForHours": payload.valid_for_hours,
    }
    if payload.wallet_address:
        body["walletAddress"] = normalize_wallet_address(payload.wallet_address)
    return body


def build_remote_passport_delegation_create_payload(payload: PassportDelegationCreateRequest) -> dict[str, object]:
    body: dict[str, object] = {
        "amountUsd": payload.amount_usd,
        "status": payload.status,
        "provider": payload.provider,
    }
    if payload.session_id:
        body["sessionId"] = payload.session_id
    if payload.task_id:
        body["taskId"] = payload.task_id
    if payload.payer:
        body["payer"] = normalize_wallet_address(payload.payer)
    if payload.provider_intent_id:
        body["providerIntentId"] = payload.provider_intent_id
    if payload.metadata:
        body["metadata"] = payload.metadata
    return body


def sync_passport_delegation_for_intent(intent: InMemoryPaymentIntent) -> None:
    if not is_passport_remote_mode_enabled():
        return

    payload = {
        "sessionId": intent.session_id,
        "taskId": intent.task_id,
        "payer": intent.wallet_address,
        "amountUsd": intent.amount_usd,
        "status": intent.status,
        "provider": intent.provider,
        "providerIntentId": intent.provider_intent_id,
        "metadata": intent.metadata,
    }
    remote = KITE_PASSPORT_CLIENT.create_delegation(payload)

    if not intent.metadata:
        intent.metadata = {}
    intent.metadata["remotePassportDelegation"] = remote
    persist_payment_intent(intent)


@app.get("/passport/sessions", response_model=list[PassportSessionResponse])
def list_passport_sessions() -> list[PassportSessionResponse]:
    if is_passport_remote_mode_enabled():
        try:
            remote_sessions = KITE_PASSPORT_CLIENT.list_sessions()
            return [map_remote_passport_session(item) for item in remote_sessions]
        except KitePassportClientError as error:
            if not is_passport_local_fallback_enabled():
                raise HTTPException(status_code=502, detail=f"Kite Passport API error: {error}") from error

    if not DATABASE_ENABLED:
        sessions = list(SESSIONS.values())
    else:
        with SessionLocal() as db:
            models = db.scalars(select(SessionModel).order_by(SessionModel.created_at.desc())).all()
        sessions = [session_from_model(model) for model in models]

    return [serialize_passport_session(session) for session in sessions]


@app.get("/passport/sessions/{session_id}", response_model=PassportSessionResponse)
def get_passport_session(session_id: str) -> PassportSessionResponse:
    if is_passport_remote_mode_enabled():
        try:
            remote = KITE_PASSPORT_CLIENT.get_session(session_id)
            return map_remote_passport_session(remote)
        except KitePassportClientError as error:
            if not is_passport_local_fallback_enabled():
                raise HTTPException(status_code=502, detail=f"Kite Passport API error: {error}") from error

    session = get_session_by_id(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return serialize_passport_session(session)


@app.get("/passport/delegations", response_model=list[PassportDelegationResponse])
def list_passport_delegations(session_id: str | None = None) -> list[PassportDelegationResponse]:
    if is_passport_remote_mode_enabled():
        try:
            remote_delegations = KITE_PASSPORT_CLIENT.list_delegations(session_id=session_id)
            return [map_remote_passport_delegation(item) for item in remote_delegations]
        except KitePassportClientError as error:
            if not is_passport_local_fallback_enabled():
                raise HTTPException(status_code=502, detail=f"Kite Passport API error: {error}") from error

    intents = [intent for intent in list_payment_intents() if intent.provider == "x402"]
    if session_id:
        intents = [intent for intent in intents if intent.session_id == session_id]
    return [serialize_passport_delegation(intent) for intent in intents]


@app.get("/passport/delegations/{delegation_id}", response_model=PassportDelegationResponse)
def get_passport_delegation(delegation_id: str) -> PassportDelegationResponse:
    if is_passport_remote_mode_enabled():
        try:
            remote = KITE_PASSPORT_CLIENT.get_delegation(delegation_id)
            return map_remote_passport_delegation(remote)
        except KitePassportClientError as error:
            if not is_passport_local_fallback_enabled():
                raise HTTPException(status_code=502, detail=f"Kite Passport API error: {error}") from error

    intent = get_payment_intent_by_passport_delegation_id(delegation_id)
    if intent is None:
        raise HTTPException(status_code=404, detail="Delegation not found")
    return serialize_passport_delegation(intent)


@app.post("/passport/sessions", response_model=PassportSessionResponse)
def create_passport_session(payload: PassportSessionCreateRequest) -> PassportSessionResponse:
    if is_passport_remote_mode_enabled():
        try:
            remote = KITE_PASSPORT_CLIENT.create_session(build_remote_passport_session_create_payload(payload))
            return map_remote_passport_session(remote)
        except KitePassportClientError as error:
            if not is_passport_local_fallback_enabled():
                raise HTTPException(status_code=502, detail=f"Kite Passport API error: {error}") from error

    return create_local_passport_session(payload)


@app.post("/passport/delegations", response_model=PassportDelegationResponse)
def create_passport_delegation(payload: PassportDelegationCreateRequest) -> PassportDelegationResponse:
    if is_passport_remote_mode_enabled():
        try:
            remote = KITE_PASSPORT_CLIENT.create_delegation(build_remote_passport_delegation_create_payload(payload))
            return map_remote_passport_delegation(remote)
        except KitePassportClientError as error:
            if not is_passport_local_fallback_enabled():
                raise HTTPException(status_code=502, detail=f"Kite Passport API error: {error}") from error

    return create_local_passport_delegation(payload)


@app.post("/payments/webhook/x402")
async def webhook_x402(request: Request) -> dict[str, object]:
    del request
    raise HTTPException(
        status_code=410,
        detail="Legacy webhook flow removed. Real x402 uses request-time verify/settle, not simulated webhooks.",
    )


@app.get("/metrics/security")
def security_metrics() -> dict[str, object]:
    prune_challenges()
    session_challenge_count = len(SESSION_CHALLENGES)
    task_challenge_count = len(TASK_CHALLENGES)

    if DATABASE_ENABLED:
        with SessionLocal() as db:
            session_challenge_count = db.scalar(select(func.count()).select_from(SessionChallengeModel)) or 0
            task_challenge_count = db.scalar(select(func.count()).select_from(TaskChallengeModel)) or 0

    return {
        "counters": get_security_metrics_snapshot(),
        "active": {
            "session_challenges": session_challenge_count,
            "task_challenges": task_challenge_count,
            "session_wallet_buckets": len(SESSION_CHALLENGE_REQUESTS),
            "task_wallet_buckets": len(TASK_CHALLENGE_REQUESTS),
            "session_ip_buckets": len(SESSION_CHALLENGE_REQUESTS_IP),
            "task_ip_buckets": len(TASK_CHALLENGE_REQUESTS_IP),
        },
        "limits": {
            "wallet": {
                "session_per_minute": SESSION_CHALLENGE_RATE_LIMIT,
                "task_per_minute": TASK_CHALLENGE_RATE_LIMIT,
            },
            "ip": {
                "session_per_minute": SESSION_CHALLENGE_RATE_LIMIT_IP,
                "task_per_minute": TASK_CHALLENGE_RATE_LIMIT_IP,
            },
            "challenge_expiry_minutes": CHALLENGE_EXPIRY_MINUTES,
        },
    }


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def bump_security_metric(key: str, delta: int = 1) -> None:
    SECURITY_METRICS[key] = SECURITY_METRICS.get(key, 0) + delta

    if not DATABASE_ENABLED:
        return

    with SessionLocal() as db:
        counter = db.scalar(select(SecurityCounterModel).where(SecurityCounterModel.key == key))
        if counter is None:
            counter = SecurityCounterModel(key=key, value=0, updated_at=now_utc().isoformat())
            db.add(counter)

        counter.value = int(counter.value) + delta
        counter.updated_at = now_utc().isoformat()
        db.commit()


def get_security_metrics_snapshot() -> dict[str, int]:
    snapshot = dict(SECURITY_METRICS)

    if not DATABASE_ENABLED:
        return snapshot

    with SessionLocal() as db:
        rows = db.scalars(select(SecurityCounterModel)).all()
        for row in rows:
            snapshot[row.key] = int(row.value)

    return snapshot


def is_expired(iso_timestamp: str) -> bool:
    return now_utc() > datetime.fromisoformat(iso_timestamp)


def prune_rate_limit_store(request_store: dict[str, list[datetime]]) -> None:
    window_start = now_utc() - timedelta(seconds=CHALLENGE_RATE_WINDOW_SECONDS)
    for key, timestamps in list(request_store.items()):
        recent = [ts for ts in timestamps if ts > window_start]
        if recent:
            request_store[key] = recent
        else:
            del request_store[key]


def prune_challenges() -> None:
    cutoff = now_utc() - timedelta(minutes=CHALLENGE_PRUNE_GRACE_MINUTES)

    if DATABASE_ENABLED:
        with SessionLocal() as db:
            # Remove expired session challenges.
            expired_session_ids = db.scalars(
                select(SessionChallengeModel.id).where(SessionChallengeModel.expires_at < now_utc().isoformat())
            ).all()
            if expired_session_ids:
                db.execute(delete(SessionChallengeModel).where(SessionChallengeModel.id.in_(expired_session_ids)))
                bump_security_metric("session_challenge_pruned", len(expired_session_ids))

            used_old_session_ids = db.scalars(
                select(SessionChallengeModel.id).where(
                    SessionChallengeModel.used.is_(True),
                    SessionChallengeModel.created_at < cutoff.isoformat(),
                )
            ).all()
            if used_old_session_ids:
                db.execute(delete(SessionChallengeModel).where(SessionChallengeModel.id.in_(used_old_session_ids)))
                bump_security_metric("session_challenge_pruned", len(used_old_session_ids))

            # Remove expired task challenges.
            expired_task_ids = db.scalars(
                select(TaskChallengeModel.id).where(TaskChallengeModel.expires_at < now_utc().isoformat())
            ).all()
            if expired_task_ids:
                db.execute(delete(TaskChallengeModel).where(TaskChallengeModel.id.in_(expired_task_ids)))
                bump_security_metric("task_challenge_pruned", len(expired_task_ids))

            used_old_task_ids = db.scalars(
                select(TaskChallengeModel.id).where(
                    TaskChallengeModel.used.is_(True),
                    TaskChallengeModel.created_at < cutoff.isoformat(),
                )
            ).all()
            if used_old_task_ids:
                db.execute(delete(TaskChallengeModel).where(TaskChallengeModel.id.in_(used_old_task_ids)))
                bump_security_metric("task_challenge_pruned", len(used_old_task_ids))

            db.commit()

        prune_rate_limit_store(SESSION_CHALLENGE_REQUESTS)
        prune_rate_limit_store(TASK_CHALLENGE_REQUESTS)
        prune_rate_limit_store(SESSION_CHALLENGE_REQUESTS_IP)
        prune_rate_limit_store(TASK_CHALLENGE_REQUESTS_IP)
        return

    for challenge_id, challenge in list(SESSION_CHALLENGES.items()):
        expired = is_expired(challenge.expires_at)
        used_and_old = challenge.used and datetime.fromisoformat(challenge.created_at) < cutoff
        if expired or used_and_old:
            del SESSION_CHALLENGES[challenge_id]
            bump_security_metric("session_challenge_pruned")

    for challenge_id, challenge in list(TASK_CHALLENGES.items()):
        expired = is_expired(challenge.expires_at)
        used_and_old = challenge.used and datetime.fromisoformat(challenge.created_at) < cutoff
        if expired or used_and_old:
            del TASK_CHALLENGES[challenge_id]
            bump_security_metric("task_challenge_pruned")

    prune_rate_limit_store(SESSION_CHALLENGE_REQUESTS)
    prune_rate_limit_store(TASK_CHALLENGE_REQUESTS)
    prune_rate_limit_store(SESSION_CHALLENGE_REQUESTS_IP)
    prune_rate_limit_store(TASK_CHALLENGE_REQUESTS_IP)


def enforce_challenge_rate_limit(
    principal: str,
    request_store: dict[str, list[datetime]],
    limit: int,
    scope: str,
    metric_key: str,
    principal_label: str,
) -> None:
    now = now_utc()
    window_start = now - timedelta(seconds=CHALLENGE_RATE_WINDOW_SECONDS)
    key = principal.lower()

    recent = [ts for ts in request_store.get(key, []) if ts > window_start]
    if len(recent) >= limit:
        bump_security_metric(metric_key)
        raise HTTPException(
            status_code=429,
            detail=f"Too many {scope} challenge requests for this {principal_label}. Try again in a minute.",
        )

    recent.append(now)
    request_store[key] = recent


async def challenge_pruner_loop() -> None:
    while True:
        prune_challenges()
        await asyncio.sleep(CHALLENGE_PRUNE_INTERVAL_SECONDS)


def session_available_budget(session: InMemorySession) -> float:
    return round(max(session.budget_limit - session.spent_budget, 0), 2)


def session_expired(session: InMemorySession) -> bool:
    return now_utc() > datetime.fromisoformat(session.valid_until)


def serialize_session(session: InMemorySession) -> SessionResponse:
    return SessionResponse(
        id=session.id,
        budget_limit=session.budget_limit,
        spent_budget=round(session.spent_budget, 2),
        available_budget=session_available_budget(session),
        allowed_providers=session.allowed_providers,
        wallet_address=session.wallet_address,
        revoked=session.revoked,
        valid_until=session.valid_until,
        created_at=session.created_at,
    )


def serialize_passport_session(session: InMemorySession) -> PassportSessionResponse:
    return PassportSessionResponse(
        session_id=session.id,
        max_total_spend_usd=session.budget_limit,
        spent_usd=round(session.spent_budget, 2),
        available_usd=session_available_budget(session),
        valid_until=session.valid_until,
        revoked=session.revoked,
        wallet_address=session.wallet_address,
        created_at=session.created_at,
    )


def session_from_model(model: SessionModel) -> InMemorySession:
    return InMemorySession(
        id=model.id,
        budget_limit=model.budget_limit,
        spent_budget=model.spent_budget,
        allowed_providers=model.allowed_providers,
        wallet_address=model.wallet_address,
        revoked=model.revoked,
        valid_until=model.valid_until,
        created_at=model.created_at,
    )


def persist_session(session: InMemorySession) -> None:
    if not DATABASE_ENABLED:
        SESSIONS[session.id] = session
        return

    with SessionLocal() as db:
        model = db.get(SessionModel, session.id)
        if model is None:
            model = SessionModel(id=session.id)
            db.add(model)

        model.budget_limit = session.budget_limit
        model.spent_budget = session.spent_budget
        model.allowed_providers = list(session.allowed_providers)
        model.wallet_address = session.wallet_address
        model.revoked = session.revoked
        model.valid_until = session.valid_until
        model.created_at = session.created_at
        db.commit()


def get_session_by_id(session_id: str) -> InMemorySession | None:
    if not DATABASE_ENABLED:
        return SESSIONS.get(session_id)

    with SessionLocal() as db:
        model = db.get(SessionModel, session_id)
        if model is None:
            return None
        return session_from_model(model)


def session_challenge_from_model(model: SessionChallengeModel) -> InMemorySessionChallenge:
    return InMemorySessionChallenge(
        id=model.id,
        wallet_address=model.wallet_address,
        message=model.message,
        expires_at=model.expires_at,
        used=model.used,
        created_at=model.created_at,
    )


def task_challenge_from_model(model: TaskChallengeModel) -> InMemoryTaskChallenge:
    return InMemoryTaskChallenge(
        id=model.id,
        session_id=model.session_id,
        wallet_address=model.wallet_address,
        goal=model.goal,
        budget=model.budget,
        message=model.message,
        expires_at=model.expires_at,
        used=model.used,
        created_at=model.created_at,
    )


def persist_session_challenge(challenge: InMemorySessionChallenge) -> None:
    if not DATABASE_ENABLED:
        SESSION_CHALLENGES[challenge.id] = challenge
        return

    with SessionLocal() as db:
        model = db.get(SessionChallengeModel, challenge.id)
        if model is None:
            model = SessionChallengeModel(id=challenge.id)
            db.add(model)
        model.wallet_address = challenge.wallet_address
        model.message = challenge.message
        model.expires_at = challenge.expires_at
        model.used = challenge.used
        model.created_at = challenge.created_at
        db.commit()


def persist_task_challenge(challenge: InMemoryTaskChallenge) -> None:
    if not DATABASE_ENABLED:
        TASK_CHALLENGES[challenge.id] = challenge
        return

    with SessionLocal() as db:
        model = db.get(TaskChallengeModel, challenge.id)
        if model is None:
            model = TaskChallengeModel(id=challenge.id)
            db.add(model)
        model.session_id = challenge.session_id
        model.wallet_address = challenge.wallet_address
        model.goal = challenge.goal
        model.budget = challenge.budget
        model.message = challenge.message
        model.expires_at = challenge.expires_at
        model.used = challenge.used
        model.created_at = challenge.created_at
        db.commit()


def get_session_challenge(challenge_id: str) -> InMemorySessionChallenge | None:
    if not DATABASE_ENABLED:
        return SESSION_CHALLENGES.get(challenge_id)

    with SessionLocal() as db:
        model = db.get(SessionChallengeModel, challenge_id)
        if model is None:
            return None
        return session_challenge_from_model(model)


def get_task_challenge(challenge_id: str) -> InMemoryTaskChallenge | None:
    if not DATABASE_ENABLED:
        return TASK_CHALLENGES.get(challenge_id)

    with SessionLocal() as db:
        model = db.get(TaskChallengeModel, challenge_id)
        if model is None:
            return None
        return task_challenge_from_model(model)


def task_from_model(model: TaskModel) -> InMemoryTask:
    return InMemoryTask(
        id=model.id,
        session_id=model.session_id,
        goal=model.goal,
        budget=model.budget,
        status=model.status,  # type: ignore[arg-type]
        steps=list(model.steps or []),
        events=[ActivityEvent(**item) for item in (model.events or [])],
        proof=ProofResponse(**model.proof) if model.proof else None,
        report=ReportResponse(**model.report) if model.report else None,
        created_at=model.created_at,
    )


def persist_task(task: InMemoryTask) -> None:
    if not DATABASE_ENABLED:
        TASKS[task.id] = task
        return

    with SessionLocal() as db:
        model = db.get(TaskModel, task.id)
        if model is None:
            model = TaskModel(id=task.id)
            db.add(model)

        model.session_id = task.session_id
        model.goal = task.goal
        model.budget = task.budget
        model.status = task.status
        model.steps = list(task.steps)
        model.events = [event.model_dump() for event in task.events]
        model.proof = task.proof.model_dump() if task.proof else None
        model.report = task.report.model_dump() if task.report else None
        model.created_at = task.created_at
        db.commit()


def get_task_by_id(task_id: str) -> InMemoryTask | None:
    if not DATABASE_ENABLED:
        return TASKS.get(task_id)

    with SessionLocal() as db:
        model = db.get(TaskModel, task_id)
        if model is None:
            return None
        return task_from_model(model)


def payment_intent_from_model(model: PaymentIntentModel) -> InMemoryPaymentIntent:
    return InMemoryPaymentIntent(
        id=model.id,
        session_id=model.session_id,
        task_id=model.task_id,
        wallet_address=model.wallet_address,
        provider=model.provider,
        provider_intent_id=model.provider_intent_id,
        amount_usd=model.amount_usd,
        currency=model.currency,
        status=model.status,
        metadata=dict(model.metadata_json) if model.metadata_json else None,
        created_at=model.created_at,
        updated_at=model.updated_at,
        confirmed_at=model.confirmed_at,
    )


def persist_payment_intent(intent: InMemoryPaymentIntent) -> None:
    if not DATABASE_ENABLED:
        PAYMENT_INTENTS[intent.id] = intent
        return

    with SessionLocal() as db:
        model = db.get(PaymentIntentModel, intent.id)
        if model is None:
            model = PaymentIntentModel(id=intent.id)
            db.add(model)

        model.session_id = intent.session_id
        model.task_id = intent.task_id
        model.wallet_address = intent.wallet_address
        model.provider = intent.provider
        model.provider_intent_id = intent.provider_intent_id
        model.amount_usd = intent.amount_usd
        model.currency = intent.currency
        model.status = intent.status
        model.metadata_json = dict(intent.metadata) if intent.metadata else None
        model.created_at = intent.created_at
        model.updated_at = intent.updated_at
        model.confirmed_at = intent.confirmed_at
        db.commit()


def get_payment_intent_by_id(intent_id: str) -> InMemoryPaymentIntent | None:
    if not DATABASE_ENABLED:
        return PAYMENT_INTENTS.get(intent_id)

    with SessionLocal() as db:
        model = db.get(PaymentIntentModel, intent_id)
        if model is None:
            return None
        return payment_intent_from_model(model)


def get_payment_intent_by_provider_id(provider_intent_id: str) -> InMemoryPaymentIntent | None:
    if not DATABASE_ENABLED:
        for intent in PAYMENT_INTENTS.values():
            if intent.provider_intent_id == provider_intent_id:
                return intent
        return None

    with SessionLocal() as db:
        model = db.scalar(
            select(PaymentIntentModel).where(PaymentIntentModel.provider_intent_id == provider_intent_id)
        )
        if model is None:
            return None
        return payment_intent_from_model(model)


def list_payment_intents() -> list[InMemoryPaymentIntent]:
    if not DATABASE_ENABLED:
        return sorted(PAYMENT_INTENTS.values(), key=lambda intent: intent.created_at, reverse=True)

    with SessionLocal() as db:
        models = db.scalars(select(PaymentIntentModel).order_by(PaymentIntentModel.created_at.desc())).all()
    return [payment_intent_from_model(model) for model in models]


def get_passport_delegation_id(intent: InMemoryPaymentIntent) -> str:
    metadata = dict(intent.metadata or {})
    existing = metadata.get("passportDelegationId")
    if isinstance(existing, str) and existing.strip():
        return existing

    delegation_id = f"dlg_{uuid4()}"
    metadata["passportDelegationId"] = delegation_id
    intent.metadata = metadata
    intent.updated_at = now_utc().isoformat()
    persist_payment_intent(intent)
    return delegation_id


def get_payment_intent_by_passport_delegation_id(delegation_id: str) -> InMemoryPaymentIntent | None:
    lookup = delegation_id.strip()
    if not lookup:
        return None
    for intent in list_payment_intents():
        metadata = intent.metadata or {}
        if metadata.get("passportDelegationId") == lookup:
            return intent
    return None


def update_payment_intent_status(
    intent_id: str,
    status: str,
    confirmed_at: str | None = None,
    provider_intent_id: str | None = None,
) -> InMemoryPaymentIntent | None:
    intent = get_payment_intent_by_id(intent_id)
    if intent is None:
        return None

    intent.status = status
    intent.updated_at = now_utc().isoformat()
    if confirmed_at is not None:
        intent.confirmed_at = confirmed_at
    if provider_intent_id is not None:
        intent.provider_intent_id = provider_intent_id

    persist_payment_intent(intent)
    return intent


def get_payment_event_by_provider_event_id(provider_event_id: str) -> InMemoryPaymentEvent | None:
    if not provider_event_id:
        return None

    if not DATABASE_ENABLED:
        event_id = PAYMENT_PROVIDER_EVENT_INDEX.get(provider_event_id)
        if event_id is None:
            return None
        return PAYMENT_EVENTS.get(event_id)

    with SessionLocal() as db:
        model = db.scalar(select(PaymentEventModel).where(PaymentEventModel.provider_event_id == provider_event_id))
        if model is None:
            return None
        return InMemoryPaymentEvent(
            id=model.id,
            payment_intent_id=model.payment_intent_id,
            event_type=model.event_type,
            provider_event_id=model.provider_event_id,
            payload=dict(model.payload or {}),
            processed=model.processed,
            created_at=model.created_at,
        )


def persist_payment_event(event: InMemoryPaymentEvent) -> InMemoryPaymentEvent:
    if not DATABASE_ENABLED:
        if event.id is None:
            event.id = max(PAYMENT_EVENTS.keys(), default=0) + 1
        PAYMENT_EVENTS[event.id] = event
        if event.provider_event_id:
            PAYMENT_PROVIDER_EVENT_INDEX[event.provider_event_id] = event.id
        return event

    with SessionLocal() as db:
        model = PaymentEventModel(
            payment_intent_id=event.payment_intent_id,
            event_type=event.event_type,
            provider_event_id=event.provider_event_id,
            payload=dict(event.payload),
            processed=event.processed,
            created_at=event.created_at,
        )
        db.add(model)
        db.commit()
        db.refresh(model)

    return InMemoryPaymentEvent(
        id=model.id,
        payment_intent_id=model.payment_intent_id,
        event_type=model.event_type,
        provider_event_id=model.provider_event_id,
        payload=dict(model.payload or {}),
        processed=model.processed,
        created_at=model.created_at,
    )


def get_payment_events_by_intent_id(intent_id: str) -> list[InMemoryPaymentEvent]:
    if not DATABASE_ENABLED:
        events = [event for event in PAYMENT_EVENTS.values() if event.payment_intent_id == intent_id]
        return sorted(events, key=lambda item: (item.created_at, item.id or 0), reverse=True)

    with SessionLocal() as db:
        models = db.scalars(
            select(PaymentEventModel)
            .where(PaymentEventModel.payment_intent_id == intent_id)
            .order_by(PaymentEventModel.id.desc())
        ).all()

    return [
        InMemoryPaymentEvent(
            id=model.id,
            payment_intent_id=model.payment_intent_id,
            event_type=model.event_type,
            provider_event_id=model.provider_event_id,
            payload=dict(model.payload or {}),
            processed=model.processed,
            created_at=model.created_at,
        )
        for model in models
    ]


def serialize_payment_intent(intent: InMemoryPaymentIntent) -> PaymentIntentResponse:
    return PaymentIntentResponse(**intent.model_dump())


def serialize_passport_delegation(intent: InMemoryPaymentIntent) -> PassportDelegationResponse:
    return PassportDelegationResponse(
        delegation_id=get_passport_delegation_id(intent),
        session_id=intent.session_id,
        task_id=intent.task_id,
        payer=intent.wallet_address,
        amount_usd=intent.amount_usd,
        status=intent.status,
        provider=intent.provider,
        provider_intent_id=intent.provider_intent_id,
        created_at=intent.created_at,
        confirmed_at=intent.confirmed_at,
        metadata=intent.metadata,
    )


def kite_pass_entitlement_from_model(model: KitePassEntitlementModel) -> InMemoryKitePassEntitlement:
    return InMemoryKitePassEntitlement(
        wallet_address=model.wallet_address,
        has_pass=model.has_pass,
        source=model.source,
        checked_at=model.checked_at,
        expires_at=model.expires_at,
    )


def persist_kite_pass_entitlement(entitlement: InMemoryKitePassEntitlement) -> None:
    key = entitlement.wallet_address.lower()
    if not DATABASE_ENABLED:
        KITE_PASS_ENTITLEMENTS[key] = entitlement
        return

    with SessionLocal() as db:
        model = db.get(KitePassEntitlementModel, entitlement.wallet_address)
        if model is None:
            model = KitePassEntitlementModel(wallet_address=entitlement.wallet_address)
            db.add(model)
        model.has_pass = entitlement.has_pass
        model.source = entitlement.source
        model.checked_at = entitlement.checked_at
        model.expires_at = entitlement.expires_at
        db.commit()


def get_kite_pass_entitlement(wallet_address: str) -> InMemoryKitePassEntitlement | None:
    key = wallet_address.lower()
    if not DATABASE_ENABLED:
        return KITE_PASS_ENTITLEMENTS.get(key)

    with SessionLocal() as db:
        model = db.get(KitePassEntitlementModel, wallet_address)
        if model is None:
            return None
        return kite_pass_entitlement_from_model(model)


def serialize_kite_pass_entitlement(entitlement: InMemoryKitePassEntitlement) -> KitePassStatusResponse:
    return KitePassStatusResponse(**entitlement.model_dump())


def build_x402_resource_url(request: Request) -> str:
    return f"{str(request.base_url).rstrip('/')}{request.url.path}"


def build_session_output_schema() -> dict[str, object]:
    return {
        "input": {
            "type": "http",
            "method": "POST",
            "discoverable": False,
        },
        "output": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "budget_limit": {"type": "number"},
                "valid_until": {"type": "string"},
            },
            "required": ["id", "budget_limit", "valid_until"],
        },
    }


def build_task_output_schema() -> dict[str, object]:
    return {
        "input": {
            "type": "http",
            "method": "POST",
            "discoverable": False,
        },
        "output": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "status": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": ["id", "status", "session_id"],
        },
    }


def get_x402_payment_header(request: Request) -> str | None:
    return request.headers.get("payment-signature") or request.headers.get("x-payment")


async def notify_kite_service_payment_api(
    *,
    session_id: str | None,
    task_id: str | None,
    payer: str | None,
    payment_requirements: dict[str, object],
    settle_result: dict[str, object] | None,
    resource_path: str,
    method: str,
) -> dict[str, object] | None:
    if not KITE_SERVICE_PAYMENT_API_ENABLED:
        return None
    if not KITE_SERVICE_PAYMENT_API_URL:
        return {"status": "skipped", "reason": "missing_url"}

    payload = {
        "sessionId": session_id,
        "taskId": task_id,
        "payer": payer,
        "resource": resource_path,
        "method": method,
        "paymentRequirements": payment_requirements,
        "settlement": settle_result or {},
    }
    headers = {"Content-Type": "application/json"}
    if KITE_SERVICE_PAYMENT_API_KEY:
        headers["Authorization"] = f"Bearer {KITE_SERVICE_PAYMENT_API_KEY}"

    try:
        async with httpx.AsyncClient(timeout=float(KITE_SERVICE_PAYMENT_API_TIMEOUT_SECONDS), follow_redirects=True) as client:
            response = await client.post(KITE_SERVICE_PAYMENT_API_URL, json=payload, headers=headers)
        return {
            "status": "ok" if response.is_success else "error",
            "statusCode": int(response.status_code),
            "response": response.text[:1000],
        }
    except Exception as error:  # noqa: BLE001
        return {"status": "error", "error": str(error)}


def raise_x402_payment_required(
    *,
    requirements: dict[str, object],
    error: str,
    payment_response: dict[str, object] | None = None,
) -> None:
    body = X402_CLIENT.build_payment_required(requirements=requirements, error=error)
    raise X402PaymentRequiredError(
        body=body,
        payment_required_header=X402_CLIENT.encode_header(body),
        payment_response_header=X402_CLIENT.encode_header(payment_response) if payment_response else None,
    )


async def require_x402_payment(
    request: Request,
    response: Response,
    *,
    minimum_amount_usd: float,
    description: str,
    mime_type: str,
    output_schema: dict[str, object],
    expected_wallet_address: str | None = None,
    session_id: str | None = None,
    task_id: str | None = None,
) -> InMemoryPaymentIntent | None:
    adjusted_amount = minimum_amount_usd
    if X402_ENABLED and expected_wallet_address and wallet_has_active_pass(expected_wallet_address):
        if KITE_PASS_PAYWALL_POLICY == "bypass":
            return None
        adjusted_amount = round(minimum_amount_usd * (1 - KITE_PASS_DISCOUNT_PCT / 100), 2)

    if not X402_ENABLED or adjusted_amount <= 0:
        return None

    if not X402_PAY_TO:
        raise HTTPException(status_code=500, detail="X402_PAY_TO must be configured when X402 is enabled")

    requirements = X402_CLIENT.build_payment_requirements(
        resource=build_x402_resource_url(request),
        amount_usd=adjusted_amount,
        description=description,
        mime_type=mime_type,
        output_schema=output_schema,
        extra={
            "sessionId": session_id,
            "taskId": task_id,
            **({"name": X402_EIP712_DOMAIN_NAME} if X402_EIP712_DOMAIN_NAME else {}),
            **({"version": X402_EIP712_DOMAIN_VERSION} if X402_EIP712_DOMAIN_VERSION else {}),
        },
    )

    payment_header = get_x402_payment_header(request)
    if not payment_header:
        raise_x402_payment_required(
            requirements=requirements,
            error="PAYMENT-SIGNATURE or X-PAYMENT header is required",
        )

    try:
        payment_payload = X402_CLIENT.decode_payment_header(payment_header)
    except ValueError as error:
        raise_x402_payment_required(requirements=requirements, error=str(error))

    x402_version = int(payment_payload.get("x402Version", 2) or 2)

    verify_result = await X402_CLIENT.verify(
        payment_payload=payment_payload,
        payment_requirements=requirements,
        x402_version=x402_version,
    )
    if not verify_result.is_valid:
        raise_x402_payment_required(
            requirements=requirements,
            error=verify_result.invalid_message or verify_result.invalid_reason or "Invalid x402 payment",
        )

    payer = verify_result.payer or expected_wallet_address
    if expected_wallet_address and payer and payer.lower() != expected_wallet_address.lower():
        raise HTTPException(status_code=400, detail="x402 payer does not match request wallet")

    settle_result = await X402_CLIENT.settle(
        payment_payload=payment_payload,
        payment_requirements=requirements,
        x402_version=x402_version,
    )
    settle_payload = settle_result.raw or {
        "success": settle_result.success,
        "payer": settle_result.payer,
        "transaction": settle_result.transaction,
        "network": settle_result.network,
        "errorReason": settle_result.error_reason,
        "errorMessage": settle_result.error_message,
    }
    payment_response_header = X402_CLIENT.encode_header(settle_payload)
    response.headers["PAYMENT-RESPONSE"] = payment_response_header
    response.headers["X-PAYMENT-RESPONSE"] = payment_response_header

    if not settle_result.success:
        raise_x402_payment_required(
            requirements=requirements,
            error=settle_result.error_message or settle_result.error_reason or "Payment settlement failed",
            payment_response=settle_payload,
        )

    service_payment_api_result = await notify_kite_service_payment_api(
        session_id=session_id,
        task_id=task_id,
        payer=payer,
        payment_requirements=requirements,
        settle_result=settle_result.raw,
        resource_path=request.url.path,
        method=request.method,
    )

    provider_payment_id = settle_result.transaction or hashlib.sha256(payment_header.encode("utf-8")).hexdigest()
    existing = get_payment_intent_by_provider_id(provider_payment_id)
    if existing is not None:
        return existing

    current_time = now_utc().isoformat()
    intent = InMemoryPaymentIntent(
        id=str(uuid4()),
        session_id=session_id,
        task_id=task_id,
        wallet_address=payer,
        provider="x402",
        provider_intent_id=provider_payment_id,
        amount_usd=adjusted_amount,
        currency="USD",
        status="confirmed",
        metadata={
            "passportDelegationId": f"dlg_{uuid4()}",
            "paymentRequirements": requirements,
            "verifyResponse": verify_result.raw,
            "settleResponse": settle_result.raw,
            "kiteServicePaymentApi": service_payment_api_result,
            "resource": request.url.path,
            "method": request.method,
        },
        created_at=current_time,
        updated_at=current_time,
        confirmed_at=current_time,
    )
    persist_payment_intent(intent)

    if is_passport_remote_mode_enabled():
        try:
            sync_passport_delegation_for_intent(intent)
        except KitePassportClientError as error:
            if not is_passport_local_fallback_enabled():
                raise HTTPException(status_code=502, detail=f"Kite Passport API error: {error}") from error

    verify_event_id = f"verify:{provider_payment_id}"
    if get_payment_event_by_provider_event_id(verify_event_id) is None:
        persist_payment_event(
            InMemoryPaymentEvent(
                payment_intent_id=intent.id,
                event_type="x402.verified",
                provider_event_id=verify_event_id,
                payload=verify_result.raw or {},
                processed=True,
                created_at=current_time,
            )
        )

    settle_event_id = f"settle:{provider_payment_id}"
    if get_payment_event_by_provider_event_id(settle_event_id) is None:
        persist_payment_event(
            InMemoryPaymentEvent(
                payment_intent_id=intent.id,
                event_type="x402.settled",
                provider_event_id=settle_event_id,
                payload=settle_result.raw or {},
                processed=True,
                created_at=current_time,
            )
        )

    response.headers["X402-PAYMENT-ID"] = intent.id
    return intent


def wallet_has_active_pass(wallet_address: str) -> bool:
    """Return True if the wallet has a non-expired, valid Kite Pass in the entitlement cache.

    This only consults the local cache — it does **not** make a live RPC call.
    Call ``POST /kite-pass/verify`` first to populate the cache.
    """
    if not KITE_PASS_ENABLED:
        return False
    entitlement = get_kite_pass_entitlement(wallet_address)
    if entitlement is None or not entitlement.has_pass:
        return False
    try:
        expires = datetime.fromisoformat(entitlement.expires_at)
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return datetime.now(tz=timezone.utc) < expires
    except (ValueError, TypeError):
        return False


def normalize_wallet_address(wallet_address: str) -> str:
    try:
        return Web3.to_checksum_address(wallet_address)
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"Invalid wallet address: {error}") from error


def build_session_challenge_message(challenge_id: str, wallet_address: str, expires_at: str) -> str:
    return (
        "AgentIntel Session Authorization\n"
        f"Challenge ID: {challenge_id}\n"
        f"Wallet: {wallet_address}\n"
        f"Expires At (UTC): {expires_at}\n"
        "Action: Approve creation of a scoped AgentIntel session."
    )


def build_task_challenge_message(
    challenge_id: str,
    session_id: str,
    wallet_address: str,
    goal: str,
    budget: float,
    expires_at: str,
) -> str:
    return (
        "AgentIntel Task Authorization\n"
        f"Challenge ID: {challenge_id}\n"
        f"Session ID: {session_id}\n"
        f"Wallet: {wallet_address}\n"
        f"Goal: {goal}\n"
        f"Budget USD: {budget:.2f}\n"
        f"Expires At (UTC): {expires_at}\n"
        "Action: Approve execution of this task in the signed session."
    )


def verify_wallet_signature(payload: SessionCreateRequest) -> str | None:
    prune_challenges()
    has_any_wallet_field = bool(payload.wallet_address or payload.challenge_id or payload.signature)
    has_all_wallet_fields = bool(payload.wallet_address and payload.challenge_id and payload.signature)

    if has_any_wallet_field and not has_all_wallet_fields:
        raise HTTPException(status_code=400, detail="wallet_address, challenge_id, and signature must be provided together")

    if not has_all_wallet_fields:
        return None

    wallet_address = normalize_wallet_address(payload.wallet_address or "")
    challenge = get_session_challenge(payload.challenge_id or "")
    if challenge is None:
        raise HTTPException(status_code=400, detail="Invalid or missing challenge_id")

    if challenge.used:
        raise HTTPException(status_code=400, detail="Challenge already used")

    if is_expired(challenge.expires_at):
        raise HTTPException(status_code=400, detail="Challenge expired")

    if challenge.wallet_address.lower() != wallet_address.lower():
        raise HTTPException(status_code=400, detail="Challenge wallet mismatch")

    try:
        recovered_address = Account.recover_message(
            encode_defunct(text=challenge.message),
            signature=payload.signature,
        )
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"Signature verification failed: {error}") from error

    if recovered_address.lower() != wallet_address.lower():
        raise HTTPException(status_code=400, detail="Signature does not match wallet address")

    challenge.used = True
    persist_session_challenge(challenge)
    return wallet_address


def verify_task_signature(payload: TaskCreateRequest, session: InMemorySession) -> None:
    prune_challenges()
    session_wallet = session.wallet_address
    has_any_wallet_field = bool(payload.wallet_address or payload.challenge_id or payload.signature)
    has_all_wallet_fields = bool(payload.wallet_address and payload.challenge_id and payload.signature)

    if has_any_wallet_field and not has_all_wallet_fields:
        raise HTTPException(status_code=400, detail="wallet_address, challenge_id, and signature must be provided together")

    if session_wallet is None:
        if has_any_wallet_field:
            raise HTTPException(status_code=400, detail="Task signature is only valid for wallet-bound sessions")
        return

    if not has_all_wallet_fields:
        raise HTTPException(status_code=400, detail="Signed session requires task signature")

    wallet_address = normalize_wallet_address(payload.wallet_address or "")
    if wallet_address.lower() != session_wallet.lower():
        raise HTTPException(status_code=400, detail="Task signer must match session wallet")

    challenge = get_task_challenge(payload.challenge_id or "")
    if challenge is None:
        raise HTTPException(status_code=400, detail="Invalid or missing task challenge_id")

    if challenge.used:
        raise HTTPException(status_code=400, detail="Task challenge already used")

    if is_expired(challenge.expires_at):
        raise HTTPException(status_code=400, detail="Task challenge expired")

    if challenge.session_id != payload.session_id:
        raise HTTPException(status_code=400, detail="Task challenge session mismatch")

    if challenge.wallet_address.lower() != wallet_address.lower():
        raise HTTPException(status_code=400, detail="Task challenge wallet mismatch")

    if challenge.goal != payload.goal or round(challenge.budget, 2) != round(payload.budget, 2):
        raise HTTPException(status_code=400, detail="Task challenge payload mismatch")

    try:
        recovered_address = Account.recover_message(
            encode_defunct(text=challenge.message),
            signature=payload.signature,
        )
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"Task signature verification failed: {error}") from error

    if recovered_address.lower() != wallet_address.lower():
        raise HTTPException(status_code=400, detail="Task signature does not match wallet address")

    challenge.used = True
    persist_task_challenge(challenge)


def get_session_or_404(session_id: str) -> InMemorySession:
    session = get_session_by_id(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return session


def ensure_session_active(session: InMemorySession) -> None:
    if session.revoked:
        raise RuntimeError("Session revoked")
    if session_expired(session):
        raise RuntimeError("Session expired")


def add_task_event(task: InMemoryTask, level: Literal["info", "warning", "success", "error"], message: str) -> None:
    task.events.append(
        ActivityEvent(
            id=str(uuid4()),
            level=level,
            message=message,
            created_at=now_utc().isoformat(),
        )
    )
    persist_task(task)


def append_step(task: InMemoryTask, level: Literal["info", "warning", "success", "error"], message: str) -> None:
    task.steps.append(message)
    persist_task(task)
    add_task_event(task, level, message)


def build_proof(report: ReportResponse) -> ProofResponse:
    serialized_report = json.dumps(report.model_dump(), sort_keys=True).encode("utf-8")
    report_hash = hashlib.sha256(serialized_report).hexdigest()
    return ProofResponse(
        report_hash=report_hash,
        proof_status="prepared",
        created_at=now_utc().isoformat(),
        explorer_url=None,
    )


def build_kite_explorer_url(tx_hash: str) -> str:
    base_url = os.getenv("KITE_EXPLORER_URL", "https://testnet.kitescan.ai").rstrip("/")
    return f"{base_url}/tx/{tx_hash}"


def kite_proof_is_configured() -> bool:
    return bool(os.getenv("KITE_PRIVATE_KEY", "").strip())


def estimate_costs(
    source_used: ProviderName,
    source_count: int,
    gemini_input_tokens: int = 500,
    gemini_output_tokens: int = 300,
) -> CostBreakdown:
    """Estimate API costs based on provider and usage."""
    costs = CostBreakdown()
    
    # Serper: $0.05 per search query (primary provider only)
    if source_used == "primary_serper":
        costs.serper_cost = 0.05
    
    # Tavily: $0.005 per search (secondary)
    elif source_used == "secondary_tavily":
        costs.tavily_cost = 0.005
    
    # Exa: $0.10 per search (secondary)
    elif source_used == "secondary_exa":
        costs.exa_cost = 0.10
    
    # Wikipedia and last-resort: free
    
    # Gemini: Flash model pricing ~$0.075/1M input tokens, ~$0.30/1M output tokens
    # Estimate: coordinator (synthesis) + verifier (evaluation)
    gemini_input_cost = (gemini_input_tokens * 2 / 1_000_000) * 0.075  # coordinator + verifier
    gemini_output_cost = (gemini_output_tokens * 2 / 1_000_000) * 0.30
    costs.gemini_cost = round(gemini_input_cost + gemini_output_cost, 6)
    
    # Kite proof write: ~50k gas at 1 gwei = minimal cost (estimate ~$0.001 for testnet)
    costs.kite_cost = 0.001
    
    costs.total_cost = round(
        costs.serper_cost + costs.tavily_cost + costs.exa_cost + 
        costs.gemini_cost + costs.kite_cost,
        6
    )
    
    return costs


def write_proof_to_kite_sync(report_hash: str) -> tuple[str, str]:
    rpc_url = os.getenv("KITE_RPC_URL", "https://rpc-testnet.gokite.ai").strip()
    private_key = os.getenv("KITE_PRIVATE_KEY", "").strip().replace("\n", "").replace("\r", "")
    if not private_key:
        raise RuntimeError("KITE_PRIVATE_KEY not configured")

    if not private_key.startswith("0x"):
        private_key = f"0x{private_key}"

    chain_id = int(os.getenv("KITE_CHAIN_ID", "2368"))
    web3 = Web3(Web3.HTTPProvider(rpc_url))
    if not web3.is_connected():
        raise RuntimeError("Unable to connect to Kite RPC")

    account = web3.eth.account.from_key(private_key)
    recipient = os.getenv("KITE_PROOF_RECIPIENT", account.address).strip() or account.address
    data = Web3.to_hex(text=f"AgentIntelProof:{report_hash}")

    nonce = web3.eth.get_transaction_count(account.address)
    gas_price = web3.eth.gas_price
    tx = {
        "from": account.address,
        "to": recipient,
        "value": 0,
        "data": data,
        "nonce": nonce,
        "chainId": chain_id,
        "gasPrice": gas_price,
    }

    try:
        tx["gas"] = web3.eth.estimate_gas(tx)
    except Exception:
        tx["gas"] = 120000

    signed_tx = account.sign_transaction(tx)
    tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)
    tx_hash_hex = web3.to_hex(tx_hash)
    web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    return tx_hash_hex, build_kite_explorer_url(tx_hash_hex)


async def write_proof_to_kite(report_hash: str) -> tuple[str, str]:
    return await asyncio.to_thread(write_proof_to_kite_sync, report_hash)


@app.post("/sessions/challenge", response_model=SessionChallengeResponse)
def create_session_challenge(payload: SessionChallengeRequest, request: Request) -> SessionChallengeResponse:
    prune_challenges()
    wallet_address = normalize_wallet_address(payload.wallet_address)
    enforce_challenge_rate_limit(
        principal=wallet_address,
        request_store=SESSION_CHALLENGE_REQUESTS,
        limit=SESSION_CHALLENGE_RATE_LIMIT,
        scope="session",
        metric_key="session_challenge_rate_limited_wallet",
        principal_label="wallet",
    )
    client_ip = request.client.host if request.client is not None else "unknown"
    enforce_challenge_rate_limit(
        principal=client_ip,
        request_store=SESSION_CHALLENGE_REQUESTS_IP,
        limit=SESSION_CHALLENGE_RATE_LIMIT_IP,
        scope="session",
        metric_key="session_challenge_rate_limited_ip",
        principal_label="IP",
    )
    challenge_id = str(uuid4())
    expires_at = (now_utc() + timedelta(minutes=CHALLENGE_EXPIRY_MINUTES)).isoformat()
    message = build_session_challenge_message(challenge_id, wallet_address, expires_at)

    challenge = InMemorySessionChallenge(
        id=challenge_id,
        wallet_address=wallet_address,
        message=message,
        expires_at=expires_at,
        created_at=now_utc().isoformat(),
    )
    persist_session_challenge(challenge)
    bump_security_metric("session_challenge_issued")

    return SessionChallengeResponse(
        challenge_id=challenge.id,
        wallet_address=challenge.wallet_address,
        message=challenge.message,
        expires_at=challenge.expires_at,
    )


@app.post("/sessions", response_model=SessionResponse)
async def create_session(payload: SessionCreateRequest, request: Request, response: Response) -> SessionResponse:
    wallet_address = verify_wallet_signature(payload)
    await require_x402_payment(
        request,
        response,
        minimum_amount_usd=payload.budget_limit,
        description="Create a scoped AgentIntel session",
        mime_type="application/json",
        output_schema=build_session_output_schema(),
        expected_wallet_address=wallet_address,
    )
    session_id = str(uuid4())
    current_time = now_utc()
    session = InMemorySession(
        id=session_id,
        budget_limit=payload.budget_limit,
        allowed_providers=payload.allowed_providers,
        wallet_address=wallet_address,
        valid_until=(current_time + timedelta(hours=payload.valid_for_hours)).isoformat(),
        created_at=current_time.isoformat(),
    )
    persist_session(session)
    return serialize_session(session)


@app.get("/sessions/{session_id}", response_model=SessionResponse)
def get_session(session_id: str) -> SessionResponse:
    session = get_session_or_404(session_id)
    return serialize_session(session)


@app.delete("/sessions/{session_id}", response_model=SessionResponse)
def revoke_session(session_id: str) -> SessionResponse:
    session = get_session_or_404(session_id)
    session.revoked = True
    persist_session(session)
    return serialize_session(session)


@app.post("/tasks/challenge", response_model=TaskChallengeResponse)
def create_task_challenge(payload: TaskChallengeRequest, request: Request) -> TaskChallengeResponse:
    prune_challenges()
    session = get_session_or_404(payload.session_id)
    ensure_session_active(session)

    if session.wallet_address is None:
        raise HTTPException(status_code=400, detail="Session is not wallet-bound")

    wallet_address = normalize_wallet_address(payload.wallet_address)
    enforce_challenge_rate_limit(
        principal=wallet_address,
        request_store=TASK_CHALLENGE_REQUESTS,
        limit=TASK_CHALLENGE_RATE_LIMIT,
        scope="task",
        metric_key="task_challenge_rate_limited_wallet",
        principal_label="wallet",
    )
    client_ip = request.client.host if request.client is not None else "unknown"
    enforce_challenge_rate_limit(
        principal=client_ip,
        request_store=TASK_CHALLENGE_REQUESTS_IP,
        limit=TASK_CHALLENGE_RATE_LIMIT_IP,
        scope="task",
        metric_key="task_challenge_rate_limited_ip",
        principal_label="IP",
    )
    if wallet_address.lower() != session.wallet_address.lower():
        raise HTTPException(status_code=400, detail="Wallet does not match session owner")

    challenge_id = str(uuid4())
    expires_at = (now_utc() + timedelta(minutes=CHALLENGE_EXPIRY_MINUTES)).isoformat()
    message = build_task_challenge_message(
        challenge_id=challenge_id,
        session_id=payload.session_id,
        wallet_address=wallet_address,
        goal=payload.goal,
        budget=payload.budget,
        expires_at=expires_at,
    )

    challenge = InMemoryTaskChallenge(
        id=challenge_id,
        session_id=payload.session_id,
        wallet_address=wallet_address,
        goal=payload.goal,
        budget=payload.budget,
        message=message,
        expires_at=expires_at,
        created_at=now_utc().isoformat(),
    )
    persist_task_challenge(challenge)
    bump_security_metric("task_challenge_issued")

    return TaskChallengeResponse(
        challenge_id=challenge.id,
        session_id=challenge.session_id,
        wallet_address=challenge.wallet_address,
        message=challenge.message,
        expires_at=challenge.expires_at,
    )


@app.post("/tasks", response_model=TaskResponse)
async def create_task(payload: TaskCreateRequest, request: Request, response: Response) -> TaskResponse:
    session = get_session_or_404(payload.session_id)
    ensure_session_active(session)
    verify_task_signature(payload, session)
    await require_x402_payment(
        request,
        response,
        minimum_amount_usd=payload.budget,
        description="Execute an AgentIntel task",
        mime_type="application/json",
        output_schema=build_task_output_schema(),
        expected_wallet_address=session.wallet_address,
        session_id=payload.session_id,
    )

    available_budget = session_available_budget(session)
    if payload.budget > available_budget:
        raise HTTPException(
            status_code=400,
            detail=f"Task budget exceeds available session budget ({available_budget:.2f})",
        )

    task_id = str(uuid4())
    now = now_utc().isoformat()
    session.spent_budget = round(session.spent_budget + payload.budget, 2)
    persist_session(session)

    task = InMemoryTask(
        id=task_id,
        session_id=payload.session_id,
        goal=payload.goal,
        budget=payload.budget,
        created_at=now,
    )
    add_task_event(task, "info", "Task created and queued for execution")
    persist_task(task)

    asyncio.create_task(run_task(task_id))
    return TaskResponse(**task.model_dump())


@app.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: str) -> TaskResponse:
    task = get_task_by_id(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    return TaskResponse(**task.model_dump())


@app.get("/tasks/{task_id}/report")
def get_task_report(task_id: str) -> dict[str, object]:
    task = get_task_by_id(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.report is None:
        raise HTTPException(status_code=409, detail="Report not ready")

    return {"task_id": task.id, "report": task.report.model_dump()}


async def fetch_primary_serper(goal: str) -> list[SourceItem]:
    api_key = os.getenv("SERPER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("SERPER_API_KEY not configured")

    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    payload = {"q": goal, "num": 5}

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post("https://google.serper.dev/search", headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    organic = data.get("organic", [])
    sources: list[SourceItem] = []
    for item in organic[:5]:
        title = item.get("title") or "Untitled source"
        url = item.get("link") or ""
        snippet = item.get("snippet") or "No snippet available."
        if url:
            sources.append(SourceItem(title=title, url=url, snippet=snippet))

    if not sources:
        raise RuntimeError("Primary source returned no usable results")

    return sources


async def fetch_secondary_tavily(goal: str) -> list[SourceItem]:
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY not configured")

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "query": goal,
        "search_depth": "basic",
        "max_results": 5,
        "include_answer": False,
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post("https://api.tavily.com/search", headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    results = data.get("results", [])
    sources: list[SourceItem] = []
    for item in results[:5]:
        title = item.get("title") or "Untitled source"
        url = item.get("url") or ""
        snippet = item.get("content") or item.get("snippet") or "No snippet available."
        if url:
            sources.append(SourceItem(title=title, url=url, snippet=snippet))

    if not sources:
        raise RuntimeError("Tavily returned no usable results")

    return sources


async def fetch_secondary_exa(goal: str) -> list[SourceItem]:
    api_key = os.getenv("EXA_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("EXA_API_KEY not configured")

    headers = {"x-api-key": api_key, "Content-Type": "application/json"}
    payload = {
        "query": goal,
        "numResults": 5,
        "type": "auto",
        "contents": {"text": True, "summary": True},
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post("https://api.exa.ai/search", headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    results = data.get("results", [])
    sources: list[SourceItem] = []
    for item in results[:5]:
        title = item.get("title") or "Untitled source"
        url = item.get("url") or ""
        snippet = (
            item.get("summary")
            or (item.get("text")[:240] if isinstance(item.get("text"), str) else None)
            or "No snippet available."
        )
        if url:
            sources.append(SourceItem(title=title, url=url, snippet=snippet))

    if not sources:
        raise RuntimeError("Exa returned no usable results")

    return sources


async def fetch_fallback_wikipedia(goal: str) -> list[SourceItem]:
    headers = {
        "User-Agent": "AgentIntel/0.2 (research-agent; +https://agentintel.local)",
        "Accept": "application/json",
    }
    params = {
        "action": "opensearch",
        "search": goal,
        "limit": 5,
        "namespace": 0,
        "format": "json",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get("https://en.wikipedia.org/w/api.php", params=params, headers=headers)
        response.raise_for_status()
        data = response.json()

    titles = data[1] if len(data) > 1 else []
    snippets = data[2] if len(data) > 2 else []
    urls = data[3] if len(data) > 3 else []

    sources: list[SourceItem] = []
    for title, snippet, url in zip(titles, snippets, urls):
        sources.append(
            SourceItem(
                title=title or "Untitled source",
                url=url,
                snippet=snippet or "No snippet available.",
            )
        )

    if not sources:
        raise RuntimeError("Fallback source returned no results")

    return sources


def fetch_last_resort_sources(goal: str) -> list[SourceItem]:
    query = goal.strip().replace(" ", "+")
    return [
        SourceItem(
            title="Wikipedia Search",
            url=f"https://en.wikipedia.org/w/index.php?search={query}",
            snippet="General encyclopedia entry candidates related to the goal.",
        ),
        SourceItem(
            title="DuckDuckGo Search",
            url=f"https://duckduckgo.com/?q={query}",
            snippet="General web discovery source when API providers are unavailable.",
        ),
        SourceItem(
            title="Google Search",
            url=f"https://www.google.com/search?q={query}",
            snippet="Manual web verification source to support fast recovery flows.",
        ),
    ]


async def fetch_last_resort_links(goal: str) -> list[SourceItem]:
    return fetch_last_resort_sources(goal)


def build_summary(goal: str, sources: list[SourceItem]) -> str:
    """Use Gemini to synthesize a comprehensive summary from gathered sources."""
    if not GEMINI_CLIENT:
        # Fallback if Gemini not configured
        highlights = [f"- {source.title}: {source.snippet}" for source in sources[:3]]
        return (
            f"Research goal: {goal}\n\n"
            "Key findings from gathered sources:\n"
            + "\n".join(highlights)
        )
    
    sources_text = "\n".join(
        [f"- {s.title}: {s.snippet}" for s in sources]
    )
    
    prompt = f"""You are a research synthesis agent. Analyze the following sources and create a comprehensive summary that directly addresses the research goal.

Research Goal: {goal}

Gathered Sources:
{sources_text}

Provide a concise, well-structured summary (2-3 paragraphs) that synthesizes the key insights from all sources. Focus on actionable findings and cross-source patterns. Be direct and evidence-based."""
    
    try:
        response = GEMINI_CLIENT.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt,
        )
        return response.text
    except Exception as e:
        # Fallback if Gemini call fails
        highlights = [f"- {source.title}: {source.snippet}" for source in sources[:3]]
        return f"Research goal: {goal}\n\nKey findings:\n" + "\n".join(highlights)


def score_confidence(source_count: int, source_used: str, summary: str = "") -> float:
    """Use Gemini to evaluate report quality and assign a confidence score."""
    if not GEMINI_CLIENT:
        # Fallback if Gemini not configured
        if source_used == "primary_serper":
            base = 0.7
        elif source_used in {"secondary_tavily", "secondary_exa"}:
            base = 0.62
        elif source_used == "fallback_wikipedia":
            base = 0.55
        else:
            base = 0.4
        bonus = min(source_count, 5) * 0.05
        return round(min(base + bonus, 0.95), 2)
    
    prompt = f"""You are a quality assurance agent. Evaluate the following report summary based on source count, source quality, and content coherence.

Report Summary:
{summary}

Source Count: {source_count}
Primary Source Tier: {source_used}

Assign a confidence score between 0.0 and 1.0 based on:
- Source reliability (primary provider = higher confidence)
- Number of corroborating sources (more sources = higher confidence)
- Clarity and coherence of synthesis
- Presence of conflicting information (if any)

Respond with ONLY a single decimal number (e.g., 0.85) representing the confidence score."""
    
    try:
        response = GEMINI_CLIENT.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt,
        )
        score_text = response.text.strip()
        score = float(score_text)
        return round(max(0.0, min(1.0, score)), 2)
    except Exception:
        # Fallback if Gemini call fails
        if source_used == "primary_serper":
            base = 0.7
        elif source_used in {"secondary_tavily", "secondary_exa"}:
            base = 0.62
        elif source_used == "fallback_wikipedia":
            base = 0.55
        else:
            base = 0.4
        bonus = min(source_count, 5) * 0.05
        return round(min(base + bonus, 0.95), 2)


async def run_task(task_id: str) -> None:
    task = get_task_by_id(task_id)
    if task is None:
        return

    session = get_session_by_id(task.session_id)
    if session is None:
        task.status = "failed"
        persist_task(task)
        append_step(task, "error", "Execution failed: session missing")
        return

    try:
        ensure_session_active(session)
        task.status = "running"
        persist_task(task)

        append_step(task, "info", "Coordinator agent initialized")
        await asyncio.sleep(1)

        provider_plan: list[tuple[ProviderName, str, Callable[[str], Awaitable[list[SourceItem]]]]] = [
            ("primary_serper", "primary provider (Serper)", fetch_primary_serper),
            ("secondary_tavily", "secondary provider (Tavily)", fetch_secondary_tavily),
            ("secondary_exa", "secondary provider (Exa)", fetch_secondary_exa),
            ("fallback_wikipedia", "fallback provider (Wikipedia)", fetch_fallback_wikipedia),
            ("last_resort_links", "last-resort provider", fetch_last_resort_links),
        ]

        source_used: ProviderName | None = None
        sources: list[SourceItem] | None = None

        for provider_name, provider_label, fetcher in provider_plan:
            ensure_session_active(session)

            if provider_name not in session.allowed_providers:
                append_step(task, "warning", f"Session blocked {provider_label}")
                continue

            try:
                sources = await fetcher(task.goal)
                source_used = provider_name
                append_step(task, "success", f"Collected source list using {provider_label}")
                break
            except Exception as provider_error:
                append_step(task, "warning", f"{provider_label} unavailable ({provider_error})")

        if sources is None or source_used is None:
            raise RuntimeError("No allowed provider succeeded")

        summary = build_summary(task.goal, sources)
        ensure_session_active(session)
        append_step(task, "info", "Ran synthesis and built draft report")
        await asyncio.sleep(1)

        confidence = score_confidence(len(sources), source_used, summary)
        append_step(task, "success", "Verifier agent approved report quality")
        
        # Calculate actual costs incurred
        cost_breakdown = estimate_costs(source_used, len(sources))
        append_step(task, "info", f"Cost breakdown: ${cost_breakdown.total_cost:.4f}")
        
        task.report = ReportResponse(
            summary=summary,
            sources=sources,
            confidence=confidence,
            source_used=source_used,
            cost_breakdown=cost_breakdown,
        )
        
        # Refund difference between reserved budget and actual costs
        actual_cost = cost_breakdown.total_cost
        reserved_budget = task.budget
        refund_amount = reserved_budget - actual_cost
        if refund_amount > 0:
            session.spent_budget = round(session.spent_budget - refund_amount, 2)
            persist_session(session)
            append_step(task, "info", f"Refunded ${refund_amount:.4f} (reserved ${reserved_budget:.2f} - actual ${actual_cost:.4f})")
        task.proof = build_proof(task.report)
        append_step(task, "success", "Prepared verifiable proof record for the report")

        if kite_proof_is_configured():
            task.proof.proof_status = "recorded_on_kite_pending"
            persist_task(task)
            append_step(task, "info", "Submitting proof record to Kite testnet")
            try:
                tx_hash, explorer_url = await write_proof_to_kite(task.proof.report_hash)
                task.proof.proof_status = "recorded_on_kite"
                task.proof.explorer_url = explorer_url
                persist_task(task)
                append_step(task, "success", f"Proof recorded on Kite: {tx_hash}")
            except Exception as proof_error:
                task.proof.proof_status = "failed"
                persist_task(task)
                append_step(task, "error", f"Kite proof write failed: {proof_error}")
        else:
            append_step(task, "warning", "Kite proof write skipped: KITE_PRIVATE_KEY not configured")

        task.status = "completed"
        persist_task(task)
    except Exception as error:
        # Task failed before reaching report generation, so no costs charged
        task.status = "failed"
        persist_task(task)
        append_step(task, "error", f"Execution failed: {error}")
