# Unison × Pipecat

Persistent memory for [Pipecat](https://pipecat.ai) voice AI agents, powered by the [Unison brain](https://unisonlabs.ai).

Unison gives your Pipecat agent long-term memory that persists across sessions — the agent recalls what users told it last week, knows their preferences, and builds up a knowledge graph over time.

## What it does

- Retrieves relevant memories from the Unison brain before each LLM call
- Injects them into the system prompt so the LLM has full context
- Writes a session note to the brain after each user turn so knowledge accumulates
- Ships a React frontend that shows the live memory panel in real time

## Quick start

```bash
bun i && cd backend && python -m venv venv && source venv/bin/activate && pip install -r requirements.txt
```

Create `backend/.env`:

```
UNISON_TOKEN=usk_live_...
OPENAI_API_KEY=sk-...
```

Create `.env`:

```
VITE_UNISON_TOKEN=usk_live_...
VITE_BACKEND_URL=http://localhost:8001
```

Then run:

```bash
# Terminal 1
cd backend && source venv/bin/activate && python server.py

# Terminal 2
bun run dev
```

## Pipecat processor

```python
from unison_pipecat import UnisonPipecatService

memory = UnisonPipecatService(
    token=os.getenv("UNISON_TOKEN"),
    user_id="user_123",
    session_id="session_abc",
    params=UnisonPipecatService.InputParams(
        mode="full",
        search_limit=10,
    ),
)

pipeline = Pipeline([
    transport.input(),
    stt,
    user_aggregator,
    memory,          # between user aggregator and LLM
    llm,
    tts,
    transport.output(),
    assistant_aggregator,
])
```

### Parameters

| Parameter | Default | Description |
|---|---|---|
| `token` | `$UNISON_TOKEN` | Unison API token (`usk_live_...`) |
| `user_id` | `"default"` | User identifier — namespaces brain documents |
| `session_id` | `"default"` | Session identifier — per-session note paths |
| `base_url` | `$UNISON_API_URL` | Override the Unison API base URL |
| `params.mode` | `"full"` | `profile` / `query` / `full` |
| `params.search_limit` | `10` | Number of search hits to retrieve (1-50) |
| `params.search_threshold` | `0.0` | Minimum relevance score to include |
| `params.memory_tag` | `"pipecat"` | Tag applied to written brain documents |

### Modes

- **`query`** — semantic + keyword search for the current user message
- **`profile`** — reads a maintained profile document at `/private/users/{user_id}/profile.md`
- **`full`** — both (default, recommended)

## Memory storage

Session notes: `/private/users/<user_id>/sessions/<session_id>.md`

Profile (manually maintained): `/private/users/<user_id>/profile.md`

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `UNISON_TOKEN` | Yes | Unison API token (`usk_live_...`) |
| `UNISON_API_URL` | No | Override API base URL (default: `https://api.unisonlabs.ai`) |
| `OPENAI_API_KEY` | Yes (backend) | OpenAI API key for STT/LLM/TTS |
| `VITE_UNISON_TOKEN` | No | Frontend token for the in-browser memories panel |
| `VITE_BACKEND_URL` | No | Override backend URL (default: `http://localhost:8001`) |

## Getting a UNISON_TOKEN

```bash
# Provision a machine token
curl -X POST https://api.unisonlabs.ai/v1/auth/provision \
  -H "Content-Type: application/json" \
  -d '{"email": "agent@example.com"}'

# Verify with OTP from email (makes the token permanent)
curl -X POST https://api.unisonlabs.ai/v1/auth/verify \
  -H "Content-Type: application/json" \
  -d '{"email": "agent@example.com", "code": "123456"}'
```

Or with the Unison CLI:

```bash
npx @unisonlabs/cli login
```

## Links

- [Unison docs](https://unisonlabs.ai)
- [Pipecat docs](https://docs.pipecat.ai)
- [@unisonlabs/sdk on npm](https://www.npmjs.com/package/@unisonlabs/sdk)
