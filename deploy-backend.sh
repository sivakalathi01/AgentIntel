#!/bin/bash
# Deploy backend to Google Cloud Run
# Usage: ./deploy-backend.sh <project-id> [region]

set -e

PROJECT_ID=${1:-}
REGION=${2:-us-central1}
SERVICE_NAME="agentintel-backend"

if [ -z "$PROJECT_ID" ]; then
  echo "Usage: $0 <project-id> [region]"
  echo "Example: $0 my-gcp-project us-central1"
  exit 1
fi

echo "Deploying backend to Cloud Run..."
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Service: $SERVICE_NAME"

# Set project
gcloud config set project $PROJECT_ID

# Build and push
echo "Building Docker image..."
gcloud builds submit \
  --config=cloudbuild.yaml \
  --region=$REGION

# Get image name (latest)
IMAGE="gcr.io/$PROJECT_ID/$SERVICE_NAME:latest"

# Deploy to Cloud Run
echo "Deploying to Cloud Run..."
gcloud run deploy $SERVICE_NAME \
  --image $IMAGE \
  --platform managed \
  --region $REGION \
  --memory 2Gi \
  --cpu 2 \
  --timeout 3600 \
  --allow-unauthenticated \
  --set-env-vars \
    KITE_RPC_URL=https://rpc-testnet.gokite.ai,\
    KITE_CHAIN_ID=2368,\
    KITE_EXPLORER_URL=https://testnet.kitescan.ai,\
    X402_ENABLED=true,\
    X402_NETWORK=eip155:2368,\
    X402_ASSET=0x0309764915AFC7a2a7CDd1E64c58a57c1F1705E3,\
    X402_PAY_TO=0xb62a08Bdd7ba0cb8cdDa1e3E410fa964d07b9C97,\
    X402_MERCHANT_NAME=AgentIntel,\
    X402_TOKEN_DECIMALS=6,\
    X402_EIP712_DOMAIN_NAME="USD Coin",\
    X402_EIP712_DOMAIN_VERSION=1,\
    X402_FACILITATOR_URL=https://facilitator.pieverse.io/v2,\
    X402_MAX_TIMEOUT_SECONDS=300,\
    DATABASE_ENABLED=false \
  --set-secrets \
    KITE_PRIVATE_KEY=kite-private-key:latest \
  --min-instances 0 \
  --max-instances 10

# Get service URL
SERVICE_URL=$(gcloud run services describe $SERVICE_NAME --region $REGION --format='value(status.url)')

echo ""
echo "✅ Backend deployed successfully!"
echo "Service URL: $SERVICE_URL"
echo ""
echo "Next step: Update Vercel environment variable NEXT_PUBLIC_BACKEND_URL=$SERVICE_URL"
