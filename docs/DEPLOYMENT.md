# Deployment Guide: Google Cloud Run + Vercel

This guide covers deploying AgentIntel backend to Google Cloud Run and frontend to Vercel.

## Prerequisites

- Google Cloud Project with billing enabled
- Vercel account connected to GitHub
- `gcloud` CLI installed and authenticated
- Git repository pushed to GitHub

## Backend Deployment (Google Cloud Run)

### Step 1: Set Up Google Cloud Project

```bash
# Set your project ID
export PROJECT_ID="your-gcp-project-id"
gcloud config set project $PROJECT_ID

# Enable required APIs
gcloud services enable run.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable containerregistry.googleapis.com
gcloud services enable secretmanager.googleapis.com
```

### Step 2: Create Secrets in Secret Manager

Store sensitive environment variables as Cloud Run secrets:

```bash
# KITE_PRIVATE_KEY
echo -n "52c80084d7aafe74ab5667d6a65351b8a3ee0a67c299ea0d14dc87b0facb5f77" | \
  gcloud secrets create kite-private-key --data-file=-

# KITE_RPC_URL
echo -n "https://rpc-testnet.gokite.ai" | \
  gcloud secrets create kite-rpc-url --data-file=-

# Other secrets (Serper, Tavily, EXA API keys, etc.)
echo -n "your-serper-key" | gcloud secrets create serper-api-key --data-file=-
echo -n "your-tavily-key" | gcloud secrets create tavily-api-key --data-file=-
echo -n "your-exa-key" | gcloud secrets create exa-api-key --data-file=-

# Google AI API key
echo -n "your-google-ai-key" | gcloud secrets create google-api-key --data-file=-

# Database URL (PostgreSQL connection string)
echo -n "postgresql://user:pass@cloud-sql-instance/kiteai" | \
  gcloud secrets create database-url --data-file=-
```

### Step 3: Update Dockerfile for Cloud Run

The existing `backend/Dockerfile` is already configured for Cloud Run (listens on port 8080).

Verify it includes:
```dockerfile
ENV PORT=8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

### Step 4: Update Backend Code for Environment Variables

Ensure `backend/app/main.py` reads from environment for production:

```python
# Already implemented - reads from os.getenv()
KITE_RPC_URL = os.getenv("KITE_RPC_URL", "https://rpc-testnet.gokite.ai")
KITE_PRIVATE_KEY = os.getenv("KITE_PRIVATE_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
```

### Step 5: Deploy with Cloud Build

Option A: Deploy via GitHub integration (Recommended)

```bash
# Connect GitHub repo to Cloud Build
gcloud builds connect --region=us-central1 --name agentintel

# Create build trigger
gcloud builds triggers create github \
  --repo-name KiteAI \
  --repo-owner DecentralizedAI \
  --branch-pattern="^main$" \
  --build-config=cloudbuild.yaml
```

Option B: Manual deployment

```bash
# Submit build
gcloud builds submit --config=cloudbuild.yaml

# Or manually deploy
gcloud run deploy agentintel-backend \
  --source backend/ \
  --platform managed \
  --region us-central1 \
  --memory 2Gi \
  --cpu 2 \
  --timeout 3600 \
  --set-env-vars \
    KITE_RPC_URL=https://rpc-testnet.gokite.ai,\
    X402_ENABLED=true,\
    X402_NETWORK=eip155:2368,\
    X402_ASSET=0x0309764915AFC7a2a7CDd1E64c58a57c1F1705E3,\
    X402_TOKEN_DECIMALS=6,\
    X402_EIP712_DOMAIN_NAME="USD Coin",\
    X402_EIP712_DOMAIN_VERSION=1,\
    X402_FACILITATOR_URL=https://facilitator.pieverse.io/v2 \
  --set-secrets \
    KITE_PRIVATE_KEY=kite-private-key:latest,\
    SERPER_API_KEY=serper-api-key:latest,\
    TAVILY_API_KEY=tavily-api-key:latest,\
    EXA_API_KEY=exa-api-key:latest,\
    GOOGLE_API_KEY=google-api-key:latest,\
    DATABASE_URL=database-url:latest \
  --allow-unauthenticated
```

### Step 6: Verify Deployment

```bash
# Get backend URL
gcloud run services describe agentintel-backend --region us-central1

# Test endpoint
curl https://agentintel-backend-<hash>.run.app/health

# View logs
gcloud run services logs read agentintel-backend --region us-central1 --limit 50
```

## Frontend Deployment (Vercel)

### Step 1: Connect GitHub to Vercel

1. Go to [vercel.com](https://vercel.com)
2. Click "Add New..." → "Project"
3. Select your GitHub repository
4. Click "Import"

### Step 2: Configure Environment Variables

In Vercel dashboard:

1. Go to Settings → Environment Variables
2. Add:
   ```
   NEXT_PUBLIC_BACKEND_URL=https://agentintel-backend-<hash>.run.app
   ```

3. Save and redeploy

### Step 3: Configure Build & Output Settings

Default settings should work:
- **Framework:** Next.js (auto-detected)
- **Build Command:** `npm run build`
- **Output Directory:** `.next`
- **Install Command:** `npm install`
- **Development Command:** `npm run dev`

### Step 4: Deploy

```bash
# Automatic deployment on push to main
git push origin main

# Or trigger manual deployment via Vercel dashboard
# Settings → Deployments → Redeploy
```

### Step 5: Verify Deployment

1. Visit your Vercel domain (e.g., `agentintel-frontend.vercel.app`)
2. Verify backend connectivity in browser console
3. Test session creation and payment flow

## Environment Configuration

### Backend Environment (.env on Cloud Run)

Use Cloud Run secrets management instead of `.env` file:

```yaml
# Set via Cloud Run secrets
KITE_RPC_URL=https://rpc-testnet.gokite.ai
KITE_CHAIN_ID=2368
KITE_EXPLORER_URL=https://testnet.kitescan.ai
KITE_PRIVATE_KEY=<secret>
KITE_PROOF_RECIPIENT=0xb62a08Bdd7ba0cb8cdDa1e3E410fa964d07b9C97

X402_ENABLED=true
X402_FACILITATOR_URL=https://facilitator.pieverse.io/v2
X402_NETWORK=eip155:2368
X402_ASSET=0x0309764915AFC7a2a7CDd1E64c58a57c1F1705E3
X402_PAY_TO=0xb62a08Bdd7ba0cb8cdDa1e3E410fa964d07b9C97
X402_TOKEN_DECIMALS=6
X402_EIP712_DOMAIN_NAME=USD Coin
X402_EIP712_DOMAIN_VERSION=1
X402_MERCHANT_NAME=AgentIntel

DATABASE_ENABLED=true
DATABASE_URL=<PostgreSQL connection string>

SERPER_API_KEY=<secret>
TAVILY_API_KEY=<secret>
EXA_API_KEY=<secret>
GOOGLE_API_KEY=<secret>
```

### Frontend Environment (Vercel)

```yaml
NEXT_PUBLIC_BACKEND_URL=https://agentintel-backend-<hash>.run.app
```

## Continuous Deployment

### Automated Updates on Git Push

1. **Backend**: Cloud Build trigger automatically builds and deploys on push to `main`
2. **Frontend**: Vercel automatically builds and deploys on push to `main`

### Manual Rollback

```bash
# Backend rollback
gcloud run deploy agentintel-backend \
  --region us-central1 \
  --image gcr.io/$PROJECT_ID/agentintel-backend:previous-tag

# Frontend rollback (via Vercel dashboard)
# Go to Deployments → Select previous version → Promote to Production
```

## Monitoring & Logging

### Cloud Run Logs
```bash
gcloud run services logs read agentintel-backend --region us-central1 --limit 100
```

### Vercel Logs
- Via dashboard: Deployments → Select deployment → Logs
- Or: `vercel logs <project-name>`

## Cost Optimization

### Cloud Run
- Use `--memory 1Gi` for lower traffic; scale to `2Gi` if needed
- Set `--cpu 1` (1 vCPU) as baseline
- Enable auto-scaling with `--min-instances 0` and `--max-instances 10`

### Vercel
- Free tier includes up to 100GB bandwidth/month
- Upgrade to Pro ($20/mo) for higher limits
- Use ISR (Incremental Static Regeneration) for static content caching

## Troubleshooting

### Backend won't start
- Check logs: `gcloud run services logs read agentintel-backend --region us-central1`
- Verify secrets: `gcloud secrets list`
- Verify environment variables match code expectations

### Frontend can't connect to backend
- Check `NEXT_PUBLIC_BACKEND_URL` in Vercel env vars
- Verify CORS is enabled in backend (FastAPI `allow_origins=["*"]`)
- Check browser console for network errors

### Payment flow fails
- Verify `X402_ASSET` and `X402_EIP712_DOMAIN_NAME` match
- Check Kite RPC connectivity
- Verify wallet has sufficient gas and USDC balance

## Security Checklist

- [ ] Secrets stored in Cloud Secret Manager (not in code)
- [ ] Cloud Run service not publicly accessible (if needed, add IAM restrictions)
- [ ] Database has strong password and network restrictions
- [ ] API keys rotated regularly
- [ ] Vercel preview deployments don't expose secrets
- [ ] CORS properly configured for frontend domain
