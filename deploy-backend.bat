@echo off
REM Deploy backend to Google Cloud Run (Windows)
REM Usage: deploy-backend.bat <project-id> [region]

setlocal enabledelayedexpansion

set PROJECT_ID=%1
set REGION=%2
if "%REGION%"=="" set REGION=us-central1
set SERVICE_NAME=agentintel-backend

if "%PROJECT_ID%"=="" (
    echo Usage: %0 ^<project-id^> [region]
    echo Example: %0 my-gcp-project us-central1
    exit /b 1
)

echo Deploying backend to Cloud Run...
echo Project: %PROJECT_ID%
echo Region: %REGION%
echo Service: %SERVICE_NAME%

REM Set project
gcloud config set project %PROJECT_ID%

REM Build and push
echo Building Docker image...
gcloud builds submit --config=cloudbuild.yaml --region=%REGION%

REM Deploy to Cloud Run
echo Deploying to Cloud Run...
gcloud run deploy %SERVICE_NAME% ^
  --image gcr.io/%PROJECT_ID%/%SERVICE_NAME%:latest ^
  --platform managed ^
  --region %REGION% ^
  --memory 2Gi ^
  --cpu 2 ^
  --timeout 3600 ^
  --allow-unauthenticated ^
  --set-env-vars ^
    KITE_RPC_URL=https://rpc-testnet.gokite.ai,^
    KITE_CHAIN_ID=2368,^
    KITE_EXPLORER_URL=https://testnet.kitescan.ai,^
    X402_ENABLED=true,^
    X402_NETWORK=eip155:2368,^
    X402_ASSET=0x0309764915AFC7a2a7CDd1E64c58a57c1F1705E3,^
    X402_PAY_TO=0xb62a08Bdd7ba0cb8cdDa1e3E410fa964d07b9C97,^
    X402_MERCHANT_NAME=AgentIntel,^
    X402_TOKEN_DECIMALS=6,^
    X402_EIP712_DOMAIN_NAME=USD Coin,^
    X402_EIP712_DOMAIN_VERSION=1,^
    X402_FACILITATOR_URL=https://facilitator.pieverse.io/v2,^
    X402_MAX_TIMEOUT_SECONDS=300,^
    DATABASE_ENABLED=false ^
  --set-secrets ^
    KITE_PRIVATE_KEY=kite-private-key:latest ^
  --min-instances 0 ^
  --max-instances 10

echo.
echo Deployment in progress...
echo Check Cloud Run console for details: https://console.cloud.google.com/run
