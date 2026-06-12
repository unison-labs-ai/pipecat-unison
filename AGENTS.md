# AGENTS.md

Guidance for AI agents. Two jobs — jump to yours:

- **Use this integration** — you're an agent setting up Pipecat + Unison memory →
  [Use pipecat-unison](#use-pipecat-unison)
- **Contribute to this repo** — you're changing the code →
  [Working in this repo](#working-in-this-repo)

Follows the [AGENTS.md](https://agents.md/) convention. Human contributors: see
[`CONTRIBUTING.md`](./CONTRIBUTING.md).

---

## Use pipecat-unison

`pipecat-unison` gives a [Pipecat](https://pipecat.ai) voice agent long-term memory
via the [Unison brain](https://unisonlabs.ai). On every user turn the processor
retrieves relevant memories, injects them into the system prompt, then saves a
session note so knowledge compounds across conversations.

### 1. Get a Unison token

Provision a machine key (the human must do this — the key is tied to their account):

```bash
curl -X POST https://brain.unisonlabs.ai/v1/auth/provision \
  -H "Content-Type: application/json" \
  -d '{"email": "agent@example.com"}'
# returns: {"apiKey":"usk_live_..."}
```

Export it:

```bash
export UNISON_TOKEN=usk_live_...
```

To override the API host (e.g. a self-hosted brain):

```bash
export UNISON_API_URL=http://localhost:4001
```

### 2. Install

```bash
# Frontend (Bun)
bun install

# Backend (Python ≥ 3.10)
cd backend && python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure

Copy the env templates and fill in real values:

```bash
cp .env.example .env                  # frontend: VITE_UNISON_TOKEN
cp backend/.env.example backend/.env  # backend: UNISON_TOKEN + OPENAI_API_KEY
```

### 4. Use the processor in your pipeline

```python
from unison_pipecat import UnisonPipecatService

memory = UnisonPipecatService(
    token=os.getenv("UNISON_TOKEN"),       # or omit — reads UNISON_TOKEN from env
    base_url=os.getenv("UNISON_API_URL"),  # optional; defaults to https://brain.unisonlabs.ai
    user_id="user_123",
    session_id="session_abc",
    params=UnisonPipecatService.InputParams(
        mode="full",        # profile | query | full
        search_limit=10,
    ),
)

pipeline = Pipeline([
    transport.input(),
    stt,
    user_aggregator,
    memory,   # between user aggregator and LLM
    llm,
    tts,
    transport.output(),
    assistant_aggregator,
])
```

### 5. Verify the brain connection

```bash
curl -s http://localhost:4001/v1/auth/whoami \
  -H "Authorization: Bearer $UNISON_TOKEN"
```

Or from Python:

```python
from unison_pipecat import UnisonClient
import os

client = UnisonClient(token=os.environ["UNISON_TOKEN"])
print(client.whoami())   # {"user": {...}, "tenant": {...}, "scopes": [...]}
print(client.status())   # {"docCount": N, ...}
```

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `UNISON_TOKEN` | Yes | Machine key (`usk_live_...`) |
| `UNISON_API_URL` | No | Override API host (default: `https://brain.unisonlabs.ai`) |
| `OPENAI_API_KEY` | Yes (backend) | OpenAI key for STT / LLM / TTS |
| `VITE_UNISON_TOKEN` | No | Frontend token for the in-browser memory panel |
| `VITE_BACKEND_URL` | No | Override backend URL (default: `http://localhost:8001`) |

---

## Working in this repo

### Repo layout

```
backend/
  unison_pipecat.py   — UnisonPipecatService + UnisonClient (Python)
  server.py           — FastAPI + Pipecat voice server
  requirements.txt
src/
  app.tsx             — React voice UI + Unison memory panel
  client.tsx          — app entry point
package.json          — frontend deps (Bun)
biome.json            — lint/format config
tsconfig.json
vite.config.ts
```

### Build, lint, test

```bash
bun install
bun run build    # tsc --noEmit + vite build
bun run lint     # Biome (lint + format check)
```

CI runs `bun install && bun run build`. All must pass before pushing.

### Conventions

- TypeScript + React 19 + Vite on the frontend. Biome formatting.
- Python 3.10+ on the backend. No extra HTTP client beyond `requests`.
- `UnisonClient` (Python) and the frontend `checkWhoami` call both use
  `Authorization: Bearer <usk_...>`. Never hard-code a token.
- `UNISON_TOKEN` / `VITE_UNISON_TOKEN` are the canonical env var names.
  Never rename them without updating `.env.example` and README.
- The `.env` file is git-ignored; `.env.example` contains only placeholder values.

### PRs

One logical change per PR. Run `bun run build` and `bun run lint` before pushing.
Never push directly to `main` — open a PR. Security issues: see
[`SECURITY.md`](./SECURITY.md).
