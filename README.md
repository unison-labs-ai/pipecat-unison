<div align="center">

<img src="https://raw.githubusercontent.com/unison-labs-ai/unison-brain/main/assets/brain.svg" width="140" />

# pipecat-unison

**Your voice agent forgets the caller the second they hang up. Give it a memory.**

A [Unison brain](https://unisonlabs.ai) integration for [Pipecat](https://github.com/pipecat-ai/pipecat) voice agents.

[![CI](https://github.com/unison-labs-ai/pipecat-unison/actions/workflows/ci.yml/badge.svg)](https://github.com/unison-labs-ai/pipecat-unison/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)
[![Stars](https://img.shields.io/github/stars/unison-labs-ai/pipecat-unison?style=social)](https://github.com/unison-labs-ai/pipecat-unison)

[Install](#install) · [Usage](#usage) · [API](#api) · [License](#license)

</div>

---

### With Unison vs. without

| Without Unison | With Unison |
|---|---|
| Caller says their allergy on call #1. Agent asks again on call #2. | `UnisonPipecatService` retrieves the allergy from the brain before the LLM speaks. |
| Every session starts from zero — no preferences, no history. | Relevant memories are injected into the system prompt on every turn. |
| Session data lives only in the audio log — inaccessible to the agent. | A session note is written to the brain after each user turn; knowledge compounds. |
| Memory is per-session, per-agent, per-tool. | One brain. All your agents read the same source of truth. |

---

**Powered by the [Unison brain](https://github.com/unison-labs-ai/unison-brain#the-hard-part--what-every-memory-system-gets-wrong) — not a flat vector store.** Temporal facts that know *what changed when*, entity resolution that knows *who's who*, and one source of truth shared across every agent and teammate — voice, Claude Code, Cursor, Codex, your backend.

### Why Unison, not a vector store bolted onto your voice agent (or mem0)?

| Other memory | Unison |
|---|---|
| Stores *what the caller said* as a flat log / vector dump | Resolves *who and what they meant* and *when it changed* — a temporal knowledge graph |
| A silo — scoped to this one agent | One brain every agent **and teammate** reads from and writes back to |
| Greets a returning caller with a fact that's no longer true | Bitemporal supersession stops surfacing the version that's no longer true |
| "Trust our benchmark" | An [open, reproducible benchmark](https://github.com/unison-labs-ai/Unison-evals) scoring every system — including ours |

---

## Install

**Prerequisites:** [Bun](https://bun.sh) and Python ≥ 3.10.

```bash
# Frontend deps
bun install

# Backend deps
cd backend && python -m venv venv && source venv/bin/activate && pip install -r requirements.txt && cd ..
```

Configure:

```bash
cp backend/.env.example backend/.env   # fill in UNISON_TOKEN + OPENAI_API_KEY
cp .env.example .env                   # fill in VITE_UNISON_TOKEN (optional)
```

`backend/.env`:

```
UNISON_TOKEN=usk_live_...
OPENAI_API_KEY=sk-...
```

`.env` (optional — enables the in-browser memory panel):

```
VITE_UNISON_TOKEN=usk_live_...
VITE_BACKEND_URL=http://localhost:8001
```

---

## Usage

```bash
# Terminal 1 — voice backend
cd backend && source venv/bin/activate && python server.py

# Terminal 2 — React frontend
bun run dev
```

Open `http://localhost:5173`, click the circle to start a voice session.

---

## API

Drop `UnisonPipecatService` between the user aggregator and the LLM:

```python
import os
from unison_pipecat import UnisonPipecatService
from pipecat.pipeline.pipeline import Pipeline

memory = UnisonPipecatService(
    token=os.getenv("UNISON_TOKEN"),       # or omit — reads env automatically
    base_url=os.getenv("UNISON_API_URL"),  # optional; defaults to https://brain.unisonlabs.ai
    user_id="user_123",
    session_id="session_abc",
    params=UnisonPipecatService.InputParams(
        mode="full",        # "profile" | "query" | "full"
        search_limit=10,
    ),
)

pipeline = Pipeline([
    transport.input(),
    stt,
    user_aggregator,
    memory,   # <-- inject here, between aggregator and LLM
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
| `params.search_limit` | `10` | Number of search hits to retrieve (1–50) |
| `params.search_threshold` | `0.0` | Minimum relevance score to include |
| `params.memory_tag` | `"pipecat"` | Tag applied to written brain documents |

### Modes

- **`query`** — semantic + keyword search for the current user message
- **`profile`** — reads a maintained profile document at `/private/notes/user-{user_id}-profile.md`
- **`full`** — both (default, recommended)

### Verify connectivity

```python
from unison_pipecat import UnisonClient
import os

client = UnisonClient(token=os.environ["UNISON_TOKEN"])
print(client.whoami())   # {"user": {...}, "workspace": {...}, "scopes": ["brain:read","brain:write"]}
print(client.status())   # {"docCount": N, ...}
```

### Get a token

```bash
# Provision a machine key
curl -X POST https://brain.unisonlabs.ai/v1/auth/provision \
  -H "Content-Type: application/json" \
  -d '{"email": "agent@example.com"}'
# returns: {"apiKey":"usk_live_..."}

# Verify with OTP from email (makes the token permanent)
curl -X POST https://brain.unisonlabs.ai/v1/auth/verify \
  -H "Content-Type: application/json" \
  -d '{"email": "agent@example.com", "code": "123456"}'
```

Or with the Unison CLI:

```bash
npx @unisonlabs/cli login
```

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `UNISON_TOKEN` | Yes | Unison API token (`usk_live_...`) |
| `UNISON_API_URL` | No | Override API base URL (default: `https://brain.unisonlabs.ai`) |
| `OPENAI_API_KEY` | Yes (backend) | OpenAI key for STT / LLM / TTS |
| `VITE_UNISON_TOKEN` | No | Frontend token for the in-browser memory panel |
| `VITE_BACKEND_URL` | No | Override backend URL (default: `http://localhost:8001`) |

---

## Star history

<div align="center">
<a href="https://star-history.com/#unison-labs-ai/pipecat-unison&Date">
<img src="https://api.star-history.com/svg?repos=unison-labs-ai/pipecat-unison&type=Date" width="600" />
</a>
<p>⭐ If Unison memory helps your voice agent, star this repo!</p>
</div>

---

## License

MIT — see [LICENSE](./LICENSE).

---

## Part of the Unison Labs constellation

**One brain, every agent.** Every repo below reads from _and writes to_ the same [Unison brain](https://unisonlabs.ai) — no per-tool memory silos.

| Repo | What it does |
|---|---|
| [unison-brain](https://github.com/unison-labs-ai/unison-brain) | CLI · SDK · MCP server — the core |
| [claude-unison](https://github.com/unison-labs-ai/claude-unison) | Memory for Claude Code |
| [cursor-unison](https://github.com/unison-labs-ai/cursor-unison) | Memory for Cursor |
| [codex-unison](https://github.com/unison-labs-ai/codex-unison) | Memory for OpenAI Codex CLI |
| [opencode-unison](https://github.com/unison-labs-ai/opencode-unison) | Memory for OpenCode |
| [openclaw-unison](https://github.com/unison-labs-ai/openclaw-unison) | Memory for OpenClaw |
| **[pipecat-unison](https://github.com/unison-labs-ai/pipecat-unison)** | **Memory for Pipecat voice agents ← you are here** |
| [python-sdk](https://github.com/unison-labs-ai/python-sdk) | Python SDK for the brain |
| [install-mcp](https://github.com/unison-labs-ai/install-mcp) | One-command MCP installer |
| [code-chunk](https://github.com/unison-labs-ai/code-chunk) | AST-aware code chunking |
| [unison-fs](https://github.com/unison-labs-ai/unison-fs) | Mount the brain as a filesystem |
| [backchannel](https://github.com/unison-labs-ai/backchannel) | Async messaging between agents |
| [Unison-evals](https://github.com/unison-labs-ai/Unison-evals) | Open memory benchmark suite |
