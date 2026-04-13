function createAgentIntelDeck() {
  const presentation = SlidesApp.create('AgentIntel - Hackathon Presentation');

  const slides = [
    {
      title: 'AgentIntel',
      bullets: [
        'Autonomous Multi-Agent Research with Real On-Chain x402 Payments',
        'Kite AI Hackathon Submission',
        'Team: [Your Team Name]'
      ]
    },
    {
      title: 'Problem',
      bullets: [
        'AI agents can discover and reason, but payment execution is often unsafe or mocked.',
        'No scoped spending controls',
        'No verifiable payment trail',
        'No quality gate before returning results'
      ]
    },
    {
      title: 'Solution Overview',
      bullets: [
        'Multi-agent execution',
        'Real x402 payment settlement on Kite Testnet',
        'Passport-style session and delegation lifecycle',
        'Traceable report and payment metadata'
      ]
    },
    {
      title: 'Multi-Agent Architecture (Core Differentiator)',
      bullets: [
        'Coordinator Agent: planning, tool selection, paid execution, draft output',
        'Verifier Agent: source quality check, evidence validation, final approval',
        'Separation of execution and validation reduces risk'
      ]
    },
    {
      title: 'End-to-End Flow',
      bullets: [
        '1. User sets goal and budget',
        '2. Backend returns HTTP 402 x402 requirement',
        '3. Buyer/agent signs EIP-712 authorization',
        '4. Facilitator verify + settle on Kite Testnet',
        '5. Coordinator executes task',
        '6. Verifier validates and approves',
        '7. Final report returned with payment traceability'
      ]
    },
    {
      title: 'Real Payment Proof',
      bullets: [
        'Network: Kite Testnet (Chain ID 2368)',
        'Facilitator: Pieverse /v2 verify + settle',
        'Exact scheme: EIP-712 transferWithAuthorization',
        'Safeguards: canonical V2 payload, domain metadata, signature normalization'
      ]
    },
    {
      title: 'Kite Passport + Delegations',
      bullets: [
        'Implemented: /passport/sessions and /passport/delegations',
        'Dedicated delegation IDs: dlg_<uuid>',
        'Remote mode scaffolded with local fallback'
      ]
    },
    {
      title: 'Security and Control',
      bullets: [
        'Wallet-bound challenge flow',
        'Per-wallet and per-IP rate limiting',
        'Session budget scope and revocation',
        'Pass-aware policy (bypass/discount)',
        'Payment intent/event audit trail'
      ]
    },
    {
      title: 'Tech Stack',
      bullets: [
        'Backend: FastAPI, SQLAlchemy, PostgreSQL, web3.py',
        'Frontend: Next.js, TypeScript, RainbowKit, wagmi',
        'Agent Runtime: Gemini-backed orchestration',
        'Payments: x402 + Pieverse facilitator',
        'Chain: Kite AI Testnet'
      ]
    },
    {
      title: 'Live Demo Plan (2 Minutes)',
      bullets: [
        'Start backend and frontend',
        'Run x402 buyer script (budget=1)',
        'Show session creation after 402 challenge',
        'Show delegation/session endpoints',
        'Show final task report and trace metadata'
      ]
    },
    {
      title: 'Results Achieved',
      bullets: [
        'Real x402 settlement path validated',
        'Multi-agent workflow integrated and documented',
        'Passport-aligned model and APIs completed',
        'Critical tests passing for payment and delegation flows'
      ]
    },
    {
      title: 'Roadmap',
      bullets: [
        'Enable live Passport remote mode with issued credentials',
        'Expand verifier scoring and policy thresholds',
        'Add richer observability dashboards',
        'Prepare mainnet-ready configuration profile'
      ]
    }
  ];

  // Remove default first slide.
  const firstSlide = presentation.getSlides()[0];
  firstSlide.remove();

  slides.forEach((s) => {
    const slide = presentation.appendSlide(SlidesApp.PredefinedLayout.TITLE_AND_BODY);
    slide.getPlaceholder(SlidesApp.PlaceholderType.TITLE).asShape().getText().setText(s.title);

    const body = slide.getPlaceholder(SlidesApp.PlaceholderType.BODY).asShape().getText();
    body.clear();
    body.setText(s.bullets.map((b) => '• ' + b).join('\n'));
  });

  Logger.log('Created presentation: ' + presentation.getUrl());
}
