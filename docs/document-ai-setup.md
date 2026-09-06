# Google Cloud Document AI — Setup

LitFlow's OCR engine is Google Cloud Document AI. The worker sends one page
image per API call and writes the same `page_NNN.txt` / `page_NNN.html`
fragments the rest of the pipeline expects.

Reference: <https://docs.cloud.google.com/document-ai/docs/setup>

## 1. Enable the API

```bash
gcloud services enable documentai.googleapis.com --project=YOUR_PROJECT_ID
```

## 2. Create an OCR processor

```bash
gcloud documentai processors create \
  --project=YOUR_PROJECT_ID \
  --location=us \
  --display-name=litflow-ocr \
  --type=OCR_PROCESSOR
```

Note the returned processor id (the last path segment of `name`). Location is
`us` or `eu` — it must match `DOCAI_LOCATION`.

List existing processors:

```bash
gcloud documentai processors list --project=YOUR_PROJECT_ID --location=us
```

## 3. Service account + key

```bash
gcloud iam service-accounts create litflow-worker \
  --project=YOUR_PROJECT_ID --display-name="LitFlow worker"

gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:litflow-worker@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/documentai.apiUser"

gcloud iam service-accounts keys create ./secrets/gcp-sa.json \
  --iam-account=litflow-worker@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

`./secrets/` is gitignored and mounted read-only into the worker container at
`/secrets` (see `docker-compose.yml`).

For local dev without a key file, `gcloud auth application-default login` also
works — leave `GOOGLE_APPLICATION_CREDENTIALS` unset in that case.

## 4. Environment

Set in `.env` (see `.env.example`):

| Var | Value |
|---|---|
| `GOOGLE_APPLICATION_CREDENTIALS` | `/secrets/gcp-sa.json` |
| `DOCAI_PROJECT_ID` | your GCP project id |
| `DOCAI_LOCATION` | `us` or `eu` |
| `DOCAI_PROCESSOR_ID` | processor id from step 2 |

## Notes

- One synchronous `process_document` call per page. The 15-page online limit
  does not apply because each call carries a single page.
- Language hints (`bn` / `ar` / `en`) are passed through `OcrConfig.Hints`;
  Document AI still auto-detects script.
- Billing is per page processed — see Document AI pricing.
