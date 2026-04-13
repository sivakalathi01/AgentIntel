"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { ConnectButton } from "@rainbow-me/rainbowkit";
import { useAccount, useSignMessage } from "wagmi";
import { WalletInfo } from "./wallet-info";

type TaskStatus = "queued" | "running" | "completed" | "failed";
type ProviderName =
  | "primary_serper"
  | "secondary_tavily"
  | "secondary_exa"
  | "fallback_wikipedia"
  | "last_resort_links";

type Session = {
  id: string;
  budget_limit: number;
  spent_budget: number;
  available_budget: number;
  allowed_providers: ProviderName[];
  wallet_address?: string | null;
  revoked: boolean;
  valid_until: string;
  created_at: string;
};

type SessionChallenge = {
  challenge_id: string;
  wallet_address: string;
  message: string;
  expires_at: string;
};

type TaskChallenge = {
  challenge_id: string;
  session_id: string;
  wallet_address: string;
  message: string;
  expires_at: string;
};

type ActivityEvent = {
  id: string;
  level: "info" | "warning" | "success" | "error";
  message: string;
  created_at: string;
};

type SourceItem = {
  title: string;
  url: string;
  snippet: string;
};

type CostBreakdown = {
  serper_cost: number;
  tavily_cost: number;
  exa_cost: number;
  gemini_cost: number;
  kite_cost: number;
  total_cost: number;
};

type Report = {
  summary: string;
  sources: SourceItem[];
  confidence: number;
  source_used: string;
  cost_breakdown?: CostBreakdown | null;
};

type SecurityMetrics = {
  counters: Record<string, number>;
  active: Record<string, number>;
  limits: {
    wallet: {
      session_per_minute: number;
      task_per_minute: number;
    };
    ip: {
      session_per_minute: number;
      task_per_minute: number;
    };
    challenge_expiry_minutes: number;
  };
};

type Proof = {
  report_hash: string;
  proof_status: "prepared" | "recorded_on_kite_pending" | "recorded_on_kite" | "failed";
  created_at: string;
  explorer_url: string | null;
};

type Task = {
  id: string;
  session_id: string;
  goal: string;
  budget: number;
  status: TaskStatus;
  steps: string[];
  events: ActivityEvent[];
  proof: Proof | null;
  report: Report | null;
};

type X402PaymentAccept = {
  scheme: string;
  network: string;
  amount: string;
  asset: string;
  payTo: string;
  resource: string;
  description: string;
  mimeType: string;
  maxTimeoutSeconds: number;
  merchantName?: string | null;
  outputSchema?: Record<string, unknown> | null;
  extra?: Record<string, unknown> | null;
};

type X402PaymentRequired = {
  x402Version: number;
  error: string;
  accepts: X402PaymentAccept[];
};

type KitePassStatus = {
  wallet_address: string;
  has_pass: boolean;
  source: string;
  checked_at: string;
  expires_at: string;
};

const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
const providerOptions: Array<{ value: ProviderName; label: string }> = [
  { value: "primary_serper", label: "Serper (primary paid)" },
  { value: "secondary_tavily", label: "Tavily (secondary paid)" },
  { value: "secondary_exa", label: "Exa (secondary paid)" },
  { value: "fallback_wikipedia", label: "Wikipedia fallback" },
  { value: "last_resort_links", label: "Last resort links" },
];

export default function Home() {
  const { address, isConnected } = useAccount();
  const { signMessageAsync } = useSignMessage();
  const [goal, setGoal] = useState("");
  const [budget, setBudget] = useState("5");
  const [sessionBudget, setSessionBudget] = useState("10");
  const [validForHours, setValidForHours] = useState("24");
  const [allowedProviders, setAllowedProviders] = useState<ProviderName[]>(
    providerOptions.map((option) => option.value),
  );
  const [loading, setLoading] = useState(false);
  const [sessionLoading, setSessionLoading] = useState(false);
  const [task, setTask] = useState<Task | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sessionSigningState, setSessionSigningState] = useState<string | null>(null);
  const [taskSigningState, setTaskSigningState] = useState<string | null>(null);
  const [securityMetrics, setSecurityMetrics] = useState<SecurityMetrics | null>(null);
  const [sessionPaymentRequired, setSessionPaymentRequired] = useState<X402PaymentRequired | null>(null);
  const [taskPaymentRequired, setTaskPaymentRequired] = useState<X402PaymentRequired | null>(null);
  const [paymentStatusMessage, setPaymentStatusMessage] = useState<string | null>(null);
  const [kitePassStatus, setKitePassStatus] = useState<KitePassStatus | null>(null);
  const [kitePassLoading, setKitePassLoading] = useState(false);

  const done = useMemo(
    () => task?.status === "completed" || task?.status === "failed",
    [task?.status],
  );

  function explainSigningError(raw: unknown): string {
    const message = raw instanceof Error ? raw.message : "Unknown error";
    const normalized = message.toLowerCase();
    if (message.toLowerCase().includes("rejected")) {
      return "Wallet signature request was rejected.";
    }
    if (message.toLowerCase().includes("mismatch")) {
      return "Connected wallet does not match the authorized wallet for this session.";
    }
    if (normalized.includes("payment-signature") || normalized.includes("x-payment")) {
      return "This endpoint now uses real x402. A compatible client must retry with PAYMENT-SIGNATURE or X-PAYMENT.";
    }
    return message;
  }

  function paymentBadgeClass(status: string): string {
    const value = status.toLowerCase();
    if (value === "confirmed" || value === "paid" || value === "succeeded" || value === "completed") {
      return "paymentBadge paymentBadgeSuccess";
    }
    if (value === "failed" || value === "cancelled" || value === "canceled") {
      return "paymentBadge paymentBadgeFailed";
    }
    return "paymentBadge paymentBadgePending";
  }

  async function fetchKitePassStatus(walletAddress: string): Promise<void> {
    try {
      const response = await fetch(`${backendUrl}/kite-pass/${walletAddress}`);
      if (response.status === 404) {
        setKitePassStatus(null);
        return;
      }
      if (!response.ok) {
        return;
      }
      const data: KitePassStatus = await response.json();
      setKitePassStatus(data);
    } catch {
      // Ignore transient failures — panel stays empty.
    }
  }

  async function handleCheckKitePass(): Promise<void> {
    if (!address) {
      return;
    }
    setKitePassLoading(true);
    try {
      const response = await fetch(`${backendUrl}/kite-pass/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ wallet_address: address }),
      });
      if (!response.ok) {
        setError(await readApiError(response, "Kite Pass check failed"));
        return;
      }
      const data: KitePassStatus = await response.json();
      setKitePassStatus(data);
    } catch (checkError) {
      setError(checkError instanceof Error ? checkError.message : "Kite Pass check failed");
    } finally {
      setKitePassLoading(false);
    }
  }

  async function readApiError(response: Response, fallback: string): Promise<string> {
    try {
      const payload = await response.json();
      if (typeof payload?.error === "string") {
        return `${fallback}: ${payload.error}`;
      }
      if (typeof payload?.detail === "string") {
        return `${fallback}: ${payload.detail}`;
      }
    } catch {
      // Ignore parse errors and use fallback below.
    }
    return `${fallback}: ${response.status}`;
  }

  async function refreshSecurityMetrics() {
    try {
      const response = await fetch(`${backendUrl}/metrics/security`);
      if (!response.ok) {
        return;
      }
      const latest: SecurityMetrics = await response.json();
      setSecurityMetrics(latest);
    } catch {
      // Optional panel; ignore transient failures.
    }
  }

  async function refreshSession(sessionId: string) {
    const response = await fetch(`${backendUrl}/sessions/${sessionId}`);
    if (!response.ok) {
      throw new Error(`Load session failed: ${response.status}`);
    }

    const latest: Session = await response.json();
    setSession(latest);
  }

  async function readX402PaymentRequired(response: Response): Promise<X402PaymentRequired | null> {
    try {
      const payload = await response.json();
      if (payload && payload.x402Version === 2 && Array.isArray(payload.accepts)) {
        return payload as X402PaymentRequired;
      }
    } catch {
      // Ignore parse errors.
    }
    return null;
  }

  function toggleProvider(provider: ProviderName) {
    setAllowedProviders((current) => {
      if (current.includes(provider)) {
        return current.filter((item) => item !== provider);
      }

      return [...current, provider];
    });
  }

  async function handleCreateSession(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSessionLoading(true);
    setSessionSigningState(null);
    setPaymentStatusMessage(null);
    setSessionPaymentRequired(null);

    try {
      let signedPayload: {
        wallet_address?: string;
        challenge_id?: string;
        signature?: string;
      } = {};

      if (isConnected && address) {
        setSessionSigningState("Requesting session challenge...");
        const challengeResponse = await fetch(`${backendUrl}/sessions/challenge`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ wallet_address: address }),
        });

        if (!challengeResponse.ok) {
          throw new Error(await readApiError(challengeResponse, "Create challenge failed"));
        }

        const challenge: SessionChallenge = await challengeResponse.json();
        setSessionSigningState("Awaiting wallet signature...");
        const signature = await signMessageAsync({ message: challenge.message });
        signedPayload = {
          wallet_address: challenge.wallet_address,
          challenge_id: challenge.challenge_id,
          signature,
        };
        setSessionSigningState("Submitting signed session...");
      }

      const response = await fetch(`${backendUrl}/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          budget_limit: Number(sessionBudget),
          valid_for_hours: Number(validForHours),
          allowed_providers: allowedProviders,
          ...signedPayload,
        }),
      });

      if (response.status === 402) {
        const paymentRequired = await readX402PaymentRequired(response);
        setSessionPaymentRequired(paymentRequired);
        setPaymentStatusMessage("Session creation now requires a real x402-compatible client or agent.");
        return;
      }

      if (!response.ok) {
        throw new Error(await readApiError(response, "Create session failed"));
      }

      const created: Session = await response.json();
      setSession(created);
      setTask(null);
      await refreshSecurityMetrics();
    } catch (sessionError) {
      setError(explainSigningError(sessionError));
    } finally {
      setSessionSigningState(null);
      setSessionLoading(false);
    }
  }

  async function handleRevokeSession() {
    if (!session) {
      return;
    }

    setError(null);
    setSessionLoading(true);
    try {
      const response = await fetch(`${backendUrl}/sessions/${session.id}`, { method: "DELETE" });
      if (!response.ok) {
        throw new Error(`Revoke session failed: ${response.status}`);
      }

      const revoked: Session = await response.json();
      setSession(revoked);
    } catch (sessionError) {
      setError(sessionError instanceof Error ? sessionError.message : "Unknown revoke error");
    } finally {
      setSessionLoading(false);
    }
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!session || session.revoked) {
      setError("Create an active session before submitting a task.");
      return;
    }

    setError(null);
    setTask(null);
    setLoading(true);
    setTaskSigningState(null);
    setPaymentStatusMessage(null);
    setTaskPaymentRequired(null);

    try {
      let signedPayload: {
        wallet_address?: string;
        challenge_id?: string;
        signature?: string;
      } = {};

      if (session.wallet_address) {
        if (!isConnected || !address) {
          throw new Error("Connect the authorized wallet before creating a task.");
        }

        if (address.toLowerCase() !== session.wallet_address.toLowerCase()) {
          throw new Error("Connected wallet does not match the session's authorized wallet.");
        }

        setTaskSigningState("Requesting task challenge...");
        const taskChallengeResponse = await fetch(`${backendUrl}/tasks/challenge`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: session.id,
            goal,
            budget: Number(budget),
            wallet_address: address,
          }),
        });

        if (!taskChallengeResponse.ok) {
          throw new Error(await readApiError(taskChallengeResponse, "Create task challenge failed"));
        }

        const taskChallenge: TaskChallenge = await taskChallengeResponse.json();
        setTaskSigningState("Awaiting wallet signature...");
        const signature = await signMessageAsync({ message: taskChallenge.message });
        signedPayload = {
          wallet_address: taskChallenge.wallet_address,
          challenge_id: taskChallenge.challenge_id,
          signature,
        };
        setTaskSigningState("Submitting signed task...");
      }

      const response = await fetch(`${backendUrl}/tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          goal,
          budget: Number(budget),
          session_id: session.id,
          ...signedPayload,
        }),
      });

      if (response.status === 402) {
        const paymentRequired = await readX402PaymentRequired(response);
        setTaskPaymentRequired(paymentRequired);
        setPaymentStatusMessage("Task execution now requires a real x402-compatible client or agent.");
        return;
      }

      if (!response.ok) {
        throw new Error(await readApiError(response, "Create task failed"));
      }

      const created: Task = await response.json();
      setTask(created);
      await refreshSession(session.id);
      await refreshSecurityMetrics();
    } catch (submitError) {
      setError(explainSigningError(submitError));
    } finally {
      setTaskSigningState(null);
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!task || done) {
      return;
    }

    const timer = setInterval(async () => {
      try {
        const response = await fetch(`${backendUrl}/tasks/${task.id}`);
        if (!response.ok) {
          return;
        }

        const latest: Task = await response.json();
        setTask(latest);
      } catch {
        // Keep polling on transient network failures.
      }
    }, 1500);

    return () => clearInterval(timer);
  }, [task, done]);

  useEffect(() => {
    if (!session || !done) {
      return;
    }

    void refreshSession(session.id);
  }, [done, session?.id]);

  useEffect(() => {
    void refreshSecurityMetrics();
    const timer = setInterval(() => {
      void refreshSecurityMetrics();
    }, 15000);

    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (isConnected && address) {
      void fetchKitePassStatus(address);
    } else {
      setKitePassStatus(null);
    }
  }, [isConnected, address]);

  return (
    <main>
      <h1>AgentIntel - Day 3</h1>
      <p className="meta">Create a scoped session, choose allowed providers, and run autonomous research within a revocable budget.</p>

      <section className="card walletSection">
        <h2>Wallet Connection</h2>
        <ConnectButton />
        <WalletInfo />
      </section>

      {(sessionSigningState || taskSigningState) && (
        <section className="card signingStatusPanel">
          <h2>Signature Status</h2>
          {sessionSigningState && <p><strong>Session:</strong> {sessionSigningState}</p>}
          {taskSigningState && <p><strong>Task:</strong> {taskSigningState}</p>}
        </section>
      )}

      {(sessionPaymentRequired || taskPaymentRequired || paymentStatusMessage) && (
        <section className="card paymentPanel">
          <div className="paymentHeader">
            <h2>Payment Status</h2>
          </div>

          {paymentStatusMessage && <p>{paymentStatusMessage}</p>}

          {sessionPaymentRequired && (
            <div className="paymentItem">
              <p><strong>Session Payment:</strong> <span className={paymentBadgeClass("pending")}>Payment Required</span></p>
              <p className="meta">{sessionPaymentRequired.error}</p>
              <p className="meta">Network: {sessionPaymentRequired.accepts[0]?.network}</p>
              <p className="meta">Pay To: {sessionPaymentRequired.accepts[0]?.payTo}</p>
              <p className="meta">Asset: {sessionPaymentRequired.accepts[0]?.asset}</p>
              <p className="meta">Amount (atomic units): {sessionPaymentRequired.accepts[0]?.amount}</p>
            </div>
          )}

          {taskPaymentRequired && (
            <div className="paymentItem">
              <p><strong>Task Payment:</strong> <span className={paymentBadgeClass("pending")}>Payment Required</span></p>
              <p className="meta">{taskPaymentRequired.error}</p>
              <p className="meta">Network: {taskPaymentRequired.accepts[0]?.network}</p>
              <p className="meta">Pay To: {taskPaymentRequired.accepts[0]?.payTo}</p>
              <p className="meta">Asset: {taskPaymentRequired.accepts[0]?.asset}</p>
              <p className="meta">Amount (atomic units): {taskPaymentRequired.accepts[0]?.amount}</p>
            </div>
          )}

          <p className="meta">
            The browser UI does not generate real x402 payment signatures. Use an x402-compatible agent, wallet, or
            client that can retry the request with PAYMENT-SIGNATURE or X-PAYMENT.
          </p>
        </section>
      )}

      {isConnected && address && (
        <section className="card kitePassPanel">
          <div className="kitePassHeader">
            <h2>Kite Pass</h2>
            <button type="button" onClick={() => void handleCheckKitePass()} disabled={kitePassLoading}>
              {kitePassLoading ? "Checking..." : "Check Pass"}
            </button>
          </div>
          {kitePassStatus ? (
            <>
              <p>
                <strong>Status:</strong>{" "}
                <span className={kitePassStatus.has_pass ? "paymentBadge paymentBadgeSuccess" : "paymentBadge paymentBadgeFailed"}>
                  {kitePassStatus.has_pass ? "Active" : "No Pass"}
                </span>
              </p>
              <p className="meta"><strong>Source:</strong> {kitePassStatus.source}</p>
              <p className="meta"><strong>Checked:</strong> {new Date(kitePassStatus.checked_at).toLocaleString()}</p>
              <p className="meta"><strong>Valid until:</strong> {new Date(kitePassStatus.expires_at).toLocaleString()}</p>
            </>
          ) : (
            <p className="meta">No pass data yet — click &quot;Check Pass&quot; to verify ownership.</p>
          )}
        </section>
      )}

      {securityMetrics && (
        <section className="card securityPanel">
          <div className="securityHeader">
            <h2>Security Limits</h2>
            <button type="button" onClick={() => void refreshSecurityMetrics()}>Refresh</button>
          </div>
          <p>
            <strong>Wallet Limits:</strong> {securityMetrics.limits.wallet.session_per_minute} session/min,
            {" "}{securityMetrics.limits.wallet.task_per_minute} task/min
          </p>
          <p>
            <strong>IP Limits:</strong> {securityMetrics.limits.ip.session_per_minute} session/min,
            {" "}{securityMetrics.limits.ip.task_per_minute} task/min
          </p>
          <p><strong>Challenge Expiry:</strong> {securityMetrics.limits.challenge_expiry_minutes} minutes</p>
          <p className="meta">
            Issued: session {securityMetrics.counters.session_challenge_issued}, task {securityMetrics.counters.task_challenge_issued}
            {" | "}
            Rate-limited: wallet {securityMetrics.counters.session_challenge_rate_limited_wallet + securityMetrics.counters.task_challenge_rate_limited_wallet},
            {" "}IP {securityMetrics.counters.session_challenge_rate_limited_ip + securityMetrics.counters.task_challenge_rate_limited_ip}
          </p>
        </section>
      )}

      <section className="card">
        <h2>Session Controls</h2>
        <form onSubmit={handleCreateSession}>
          <label htmlFor="sessionBudget">Session budget cap (USD)</label>
          <input
            id="sessionBudget"
            type="number"
            min="1"
            value={sessionBudget}
            onChange={(event) => setSessionBudget(event.target.value)}
            required
          />

          <label htmlFor="validForHours">Valid for hours</label>
          <input
            id="validForHours"
            type="number"
            min="1"
            max="168"
            value={validForHours}
            onChange={(event) => setValidForHours(event.target.value)}
            required
          />

          <label>Allowed providers</label>
          <div className="providerGrid">
            {providerOptions.map((provider) => (
              <label className="providerOption" key={provider.value}>
                <input
                  type="checkbox"
                  checked={allowedProviders.includes(provider.value)}
                  onChange={() => toggleProvider(provider.value)}
                />
                <span>{provider.label}</span>
              </label>
            ))}
          </div>

          <div className="buttonRow">
            <button type="submit" disabled={sessionLoading || allowedProviders.length === 0}>
              {sessionLoading ? "Saving..." : session ? "Replace Session" : "Create Session"}
            </button>
            {session && (
              <button
                type="button"
                className="dangerButton"
                onClick={handleRevokeSession}
                disabled={sessionLoading || session.revoked}
              >
                {session.revoked ? "Session Revoked" : "Revoke Session"}
              </button>
            )}
          </div>
        </form>

        {session && (
          <div className="sessionSummary">
            <p><strong>Session ID:</strong> {session.id}</p>
            <p><strong>Budget Limit:</strong> ${session.budget_limit.toFixed(2)}</p>
            <p><strong>Available Budget:</strong> ${session.available_budget.toFixed(2)}</p>
            <p><strong>Authorized Wallet:</strong> {session.wallet_address ?? "not signed"}</p>
            <p><strong>Status:</strong> {session.revoked ? "revoked" : "active"}</p>
            <p><strong>Valid Until:</strong> {new Date(session.valid_until).toLocaleString()}</p>
            <p><strong>Providers:</strong> {session.allowed_providers.join(", ")}</p>
          </div>
        )}
      </section>

      <form onSubmit={handleSubmit}>
        <label htmlFor="goal">Research goal</label>
        <textarea
          id="goal"
          placeholder="Example: Find top 5 competitors in AI accounting"
          value={goal}
          onChange={(event) => setGoal(event.target.value)}
          required
        />

        <label htmlFor="budget">Budget (USD)</label>
        <input
          id="budget"
          type="number"
          min="1"
          value={budget}
          onChange={(event) => setBudget(event.target.value)}
          required
        />

        <button type="submit" disabled={loading || Boolean(taskSigningState)}>
          {loading ? "Submitting..." : "Create Task"}
        </button>
      </form>

      {!session && <p className="meta">Create a session first to unlock task submission.</p>}
      {session?.revoked && <p style={{ color: "#a11111" }}>This session is revoked. Create a new one to continue.</p>}

      {error && <p style={{ color: "#a11111" }}>{error}</p>}

      {task && (
        <section className="card">
          <p><strong>Task ID:</strong> {task.id}</p>
          <p><strong>Goal:</strong> {task.goal}</p>
          <p><strong>Budget:</strong> ${task.budget.toFixed(2)}</p>
          <p className="status"><strong>Status:</strong> {task.status}</p>

          <strong>Steps</strong>
          <ul>
            {task.steps.map((step, index) => (
              <li key={`${step}-${index}`}>{step}</li>
            ))}
          </ul>

          {task.proof && (
            <div className="proofPanel">
              <h2>Proof Panel</h2>
              <p><strong>Proof Status:</strong> {task.proof.proof_status}</p>
              <p><strong>Report Hash:</strong> <span className="hashValue">{task.proof.report_hash}</span></p>
              <p><strong>Prepared At:</strong> {new Date(task.proof.created_at).toLocaleString()}</p>
              {task.proof.explorer_url ? (
                <p>
                  <a href={task.proof.explorer_url} target="_blank" rel="noreferrer">
                    View on Kite Explorer
                  </a>
                </p>
              ) : (
                <p className="meta">Explorer link will appear once Kite write is connected.</p>
              )}
            </div>
          )}

          {task.report && (
            <>
              <strong>Report</strong>
              <p><strong>Source Provider:</strong> {task.report.source_used}</p>
              <p><strong>Confidence:</strong> {task.report.confidence}</p>
              <p style={{ whiteSpace: "pre-wrap" }}>{task.report.summary}</p>

              {task.report.cost_breakdown && (
                <div className="costPanel">
                  <strong>Cost Breakdown (USD)</strong>
                  <p>Serper: ${task.report.cost_breakdown.serper_cost.toFixed(6)}</p>
                  <p>Tavily: ${task.report.cost_breakdown.tavily_cost.toFixed(6)}</p>
                  <p>Exa: ${task.report.cost_breakdown.exa_cost.toFixed(6)}</p>
                  <p>Gemini: ${task.report.cost_breakdown.gemini_cost.toFixed(6)}</p>
                  <p>Kite: ${task.report.cost_breakdown.kite_cost.toFixed(6)}</p>
                  <p><strong>Total:</strong> ${task.report.cost_breakdown.total_cost.toFixed(6)}</p>
                </div>
              )}

              <strong>Sources</strong>
              <ul>
                {task.report.sources.map((source) => (
                  <li key={source.url}>
                    <a href={source.url} target="_blank" rel="noreferrer">
                      {source.title}
                    </a>
                    <div className="meta">{source.snippet}</div>
                  </li>
                ))}
              </ul>
            </>
          )}

          {task.events.length > 0 && (
            <div className="timelinePanel">
              <h2>Activity Timeline</h2>
              <ul className="timelineList">
                {task.events.map((event) => (
                  <li key={event.id} className={`timelineItem timeline-${event.level}`}>
                    <div className="timelineTime">{new Date(event.created_at).toLocaleTimeString()}</div>
                    <div>
                      <div>{event.message}</div>
                      <div className="meta">{event.level}</div>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}
    </main>
  );
}
