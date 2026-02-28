# lognous-probe-poc

This repository contains a proof‑of‑concept Python service that polls an OpenObserve instance for error events, retrieves contextual logs and related information from a Qdrant vector database, sends a crafted prompt to an AI tool (OpenAI / Anthropic / Deepseek) to analyse the failure, and then notifies developers via Slack, Discord or email.

---

## Getting Started

### Requirements
* Docker & Docker Compose
* API key for one of the supported AI providers
* Optional: Slack webhook URL, Discord webhook URL or SMTP credentials for notification delivery

### Configuration
Copy `docker-compose.yml` and adjust the `log-probe-app` environment section:

```yaml
    environment:
      - Tool=DEEPSEEK        # or OPENAI, ANTHROPIC
      - API_KEY=your_key
      - OPENOBSERVE_URL=http://openobserve:5080
      - QDRANT_URL=http://qdrant:6333
      # notification targets (set at least one)
      - SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
      - DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
      - EMAIL_TO=devteam@example.com
      - SMTP_SERVER=smtp.example.com
      - SMTP_PORT=587
      - SMTP_USER=smtp-user
      - SMTP_PASS=smtp-password
```

Any environment variables left blank will be ignored by the probe.

### Build & Run

```bash
docker-compose build
docker-compose up
```

The `log-probe-app` service will start and poll OpenObserve every 5 seconds.

## How It Works
1. **Error detection** – the app queries the OpenObserve HTTP API for recent logs tagged with `error`.
2. **Context retrieval** – for each new error it fetches up to 5 log entries before and after.
3. **Enrichment** – a simple text-based query is sent to the Qdrant vector database to fetch related documents.
4. **AI analysis** – the service constructs a prompt containing the error, context and Qdrant hits, then posts it to the chosen AI provider. A good prompt is one that clearly describes the problem and asks the model to propose likely causes and fixes.
5. **Notification** – the resulting analysis is forwarded to any configured notification channels (Slack/Discord/email).
