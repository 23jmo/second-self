#!/bin/bash
# Deploy the Second Self backend to Google Cloud Run.
#
# Prerequisites:
#   1. gcloud CLI installed and authenticated (gcloud auth login)
#   2. A GCP project with Cloud Run and Artifact Registry enabled
#   3. Firebase project configured (same project)
#
# Usage:
#   ./deploy/deploy-backend.sh
#
# Environment variables (set these or pass inline):
#   GCP_PROJECT     — your GCP project ID
#   GCP_REGION      — Cloud Run region (default: us-central1)
#   SERVICE_NAME    — Cloud Run service name (default: secondself-backend)

set -euo pipefail

PROJECT="${GCP_PROJECT:?Set GCP_PROJECT to your GCP project ID}"
REGION="${GCP_REGION:-us-central1}"
SERVICE="${SERVICE_NAME:-secondself-backend}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== Deploying $SERVICE to Cloud Run ($PROJECT / $REGION) ==="

# Build and deploy in one step using Cloud Build
cd "$REPO_ROOT"
gcloud run deploy "$SERVICE" \
    --source . \
    --project "$PROJECT" \
    --region "$REGION" \
    --allow-unauthenticated \
    --port 8080 \
    --memory 1Gi \
    --timeout 300 \
    --set-env-vars "FIREBASE_PROJECT_ID=$PROJECT" \
    --min-instances 0 \
    --max-instances 3

# Get the service URL
URL=$(gcloud run services describe "$SERVICE" \
    --project "$PROJECT" \
    --region "$REGION" \
    --format "value(status.url)")

echo ""
echo "=== Deployed ==="
echo "Backend URL: $URL"
echo ""
echo "Next steps:"
echo "  1. Set secrets (run each line):"
echo "     gcloud run services update $SERVICE --region $REGION --set-env-vars ANTHROPIC_API_KEY=sk-..."
echo "     gcloud run services update $SERVICE --region $REGION --set-env-vars TAVILY_API_KEY=tvly-..."
echo "     gcloud run services update $SERVICE --region $REGION --set-env-vars GOOGLE_CLIENT_ID=..."
echo "     gcloud run services update $SERVICE --region $REGION --set-env-vars GOOGLE_CLIENT_SECRET=..."
echo ""
echo "  2. Deploy the Cloud Function:"
echo "     cd functions && firebase deploy --only functions"
echo "     Then set the backend URL:"
echo "     firebase functions:config:set backend.url=\"$URL\""
echo ""
echo "  3. Update ALLOWED_ORIGINS if your frontend has a production URL:"
echo "     gcloud run services update $SERVICE --region $REGION --set-env-vars ALLOWED_ORIGINS=https://yourdomain.com"
