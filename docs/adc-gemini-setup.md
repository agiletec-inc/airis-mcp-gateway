# Google Cloud ADC + Gemini / Vertex AI Setup

This guide covers configuring Application Default Credentials (ADC) for Google
Cloud and verifying access to the Gemini / Vertex AI Model API, including the fix
for a common quota-project permission error.

## Overview

Google's `setup_adc.sh` helper authenticates ADC, sets the active project and
quota project, enables the Vertex AI API, and runs a live `generateContent` test
against `gemini-2.5-flash`. A frequent failure during this flow is a
`PERMISSION_DENIED` error on the quota-project step; the cause and fix are
documented below.

## Problem

- gcloud's `billing/quota_project` property points at a stale project that the
  active account has no access to. gcloud sends this value as the
  `x-goog-user-project` header on its own API calls, so any command that needs a
  quota project — including `gcloud auth application-default set-quota-project` —
  is rejected with `PERMISSION_DENIED`.
- The ADC `quota_project_id` is unset, so client libraries have no quota/billing
  project.

## Fix

Repoint both gcloud's quota project and the ADC quota project to the active
project. Fix `billing/quota_project` **first** — while it points at an
inaccessible project, even `set-quota-project` fails.

```bash
PROJECT_ID="<your-project-id>"

gcloud config set billing/quota_project "$PROJECT_ID"
gcloud auth application-default set-quota-project "$PROJECT_ID"
```

## Full setup (fresh machine)

```bash
PROJECT_ID="<your-project-id>"

# Authenticate ADC (opens a browser)
gcloud auth application-default login

# Configure project + quota project
gcloud config set project "$PROJECT_ID"
gcloud config set billing/quota_project "$PROJECT_ID"
gcloud auth application-default set-quota-project "$PROJECT_ID"

# Enable Vertex AI
gcloud services enable aiplatform.googleapis.com
```

## Verify access (no browser re-auth)

Once ADC is valid, you can verify the Model API without logging in again:

```bash
PROJECT_ID="<your-project-id>"
TOKEN=$(gcloud auth print-access-token)

curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  "https://aiplatform.googleapis.com/v1/projects/$PROJECT_ID/locations/global/publishers/google/models/gemini-2.5-flash:generateContent" \
  -d '{"contents":[{"role":"user","parts":[{"text":"Reply ONLY with the word SUCCESS"}]}]}'
```

A response containing `SUCCESS` confirms end-to-end access.

## Expected final state

```text
account               <your-account>
core/project          <your-project-id>
billing/quota_project <your-project-id>
ADC quota_project_id  <your-project-id>
```

- ADC credentials: `~/.config/gcloud/application_default_credentials.json`
- Vertex AI API (`aiplatform.googleapis.com`): enabled

Check the current values with:

```bash
gcloud config list
gcloud config get-value billing/quota_project
```

## Troubleshooting

`PERMISSION_DENIED: Permission denied to enable service [...]` that references an
unexpected project almost always means `billing/quota_project` is set to a
project you can't use. Inspect and clear or repoint it:

```bash
gcloud config get-value billing/quota_project
gcloud config unset billing/quota_project   # or set it to your project
```

## Revert

To remove the gcloud quota-project override:

```bash
gcloud config unset billing/quota_project
```
