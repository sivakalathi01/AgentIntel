# Google Cloud Deployment Setup Guide for Windows

## Step 1: Install Google Cloud SDK

1. Download the installer: https://cloud.google.com/sdk/docs/install
2. Run the installer (choose Typical installation)
3. Restart PowerShell or your terminal after installation
4. Verify installation:
   ```powershell
   gcloud --version
   ```

## Step 2: Authenticate with Google Cloud

```powershell
gcloud auth login
# This opens a browser for authentication
# After authentication, close the browser window
```

## Step 3: Set Your Project ID

Replace `YOUR-PROJECT-ID` with your actual GCP project ID:

```powershell
$PROJECT_ID = "YOUR-PROJECT-ID"
gcloud config set project $PROJECT_ID
```

To find your project ID:
1. Go to https://console.cloud.google.com
2. Click the project dropdown (top-left)
3. Copy the Project ID

## Step 4: Enable Required APIs

```powershell
gcloud services enable run.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable containerregistry.googleapis.com
gcloud services enable secretmanager.googleapis.com
```

## Step 5: Create Secrets for Backend

### Create KITE_PRIVATE_KEY secret
```powershell
echo "52c80084d7aafe74ab5667d6a65351b8a3ee0a67c299ea0d14dc87b0facb5f77" | `
  gcloud secrets create kite-private-key --data-file=-
```

### Create other API keys (if needed)
```powershell
# SERPER_API_KEY
echo "YOUR-SERPER-KEY" | gcloud secrets create serper-api-key --data-file=-

# TAVILY_API_KEY
echo "YOUR-TAVILY-KEY" | gcloud secrets create tavily-api-key --data-file=-

# EXA_API_KEY
echo "YOUR-EXA-KEY" | gcloud secrets create exa-api-key --data-file=-

# GOOGLE_API_KEY
echo "YOUR-GOOGLE-API-KEY" | gcloud secrets create google-api-key --data-file=-
```

## Step 6: Deploy Backend to Cloud Run

```powershell
cd c:\Work\DecentralizedAI\KiteAI
.\deploy-backend.bat $PROJECT_ID europe-west1
```

Or manually:

```powershell
$PROJECT_ID = "YOUR-PROJECT-ID"
$REGION = "europe-west1"

# Build and push to Container Registry
gcloud builds submit --region=$REGION

# Deploy to Cloud Run
gcloud run deploy agentintel-backend `
  --image gcr.io/$PROJECT_ID/agentintel-backend:latest `
  --platform managed `
  --region $REGION `
  --memory 2Gi `
  --cpu 2 `
  --timeout 3600 `
  --allow-unauthenticated `
  --set-env-vars `
    "KITE_RPC_URL=https://rpc-testnet.gokite.ai,KITE_CHAIN_ID=2368,KITE_EXPLORER_URL=https://testnet.kitescan.ai,X402_ENABLED=true,X402_NETWORK=eip155:2368,X402_ASSET=0x0309764915AFC7a2a7CDd1E64c58a57c1F1705E3,X402_PAY_TO=0xb62a08Bdd7ba0cb8cdDa1e3E410fa964d07b9C97,X402_MERCHANT_NAME=AgentIntel,X402_TOKEN_DECIMALS=6,X402_EIP712_DOMAIN_NAME=USD Coin,X402_EIP712_DOMAIN_VERSION=1,X402_FACILITATOR_URL=https://facilitator.pieverse.io/v2,X402_MAX_TIMEOUT_SECONDS=300,DATABASE_ENABLED=false" `
  --set-secrets "KITE_PRIVATE_KEY=kite-private-key:latest" `
  --min-instances 0 `
  --max-instances 10
```

## Step 7: Get Your Backend URL

```powershell
$PROJECT_ID = "YOUR-PROJECT-ID"
$REGION = "europe-west1"

gcloud run services describe agentintel-backend --region $REGION --format="value(status.url)"
```

This will output your backend URL like: `https://agentintel-backend-xxx.run.app`

## Step 8: Test the Backend

```powershell
$BACKEND_URL = "YOUR-BACKEND-URL"

curl "$BACKEND_URL/health"
# Should return 200 OK
```

## Next Steps

Once deployment is successful, use this URL for the frontend deployment on Vercel:
- Environment variable: `NEXT_PUBLIC_BACKEND_URL=<YOUR-BACKEND-URL>`

## Troubleshooting

### gcloud not found after installation
- Restart PowerShell completely
- Or add to PATH manually: `C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin`

### Authentication fails
- Run: `gcloud auth application-default login`
- Or go to https://console.cloud.google.com and create a service account

### Build fails
- Check logs: `gcloud builds log <BUILD_ID> --region=europe-west1`
- Verify requirements.txt has all dependencies

### Deployment fails
- Check logs: `gcloud run services logs read agentintel-backend --region=europe-west1 --limit=50`
- Verify secrets exist: `gcloud secrets list`
- Verify API keys are valid

## Cost Estimate

- Cloud Run: ~$0.25-1/mo for light usage (free tier: 2M requests/mo)
- Container Registry: ~$0.10/mo for small image (free tier: 0.5GB)
- Secrets Manager: ~$0.06/secret/mo (first 6 secrets free)

**Total: ~$1-2/month** for light production workload
