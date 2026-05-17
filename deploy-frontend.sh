#!/bin/bash
# Deploy frontend to Vercel
# Usage: ./deploy-frontend.sh [project-name] [backend-url]

set -e

PROJECT_NAME=${1:-}
BACKEND_URL=${2:-}

if [ -z "$PROJECT_NAME" ]; then
  echo "Usage: $0 <project-name> [backend-url]"
  echo "Example: $0 agentintel-frontend https://agentintel-backend-abc.run.app"
  exit 1
fi

echo "Deploying frontend to Vercel..."
echo "Project: $PROJECT_NAME"

cd frontend

# Install Vercel CLI if not present
if ! command -v vercel &> /dev/null; then
  echo "Installing Vercel CLI..."
  npm install -g vercel
fi

# Set environment variable if provided
if [ -n "$BACKEND_URL" ]; then
  echo "Setting backend URL: $BACKEND_URL"
  vercel env add NEXT_PUBLIC_BACKEND_URL --value "$BACKEND_URL"
fi

# Deploy
echo "Deploying to Vercel..."
vercel deploy --prod

echo ""
echo "✅ Frontend deployed to Vercel!"
echo "Check your Vercel dashboard for deployment details."
