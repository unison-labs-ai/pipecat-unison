# Contributing to pipecat-unison

Thanks for helping improve this Pipecat + Unison memory integration.

## Repo layout

```
backend/
  unison_pipecat.py   — UnisonPipecatService frame processor + UnisonClient
  server.py           — FastAPI + Pipecat voice pipeline server
  requirements.txt    — Python deps
src/
  app.tsx             — React voice UI + live Unison memory panel
  client.tsx          — app entry point
package.json          — frontend deps (Bun)
biome.json            — Biome lint/format config
tsconfig.json
vite.config.ts
```

## Development

Prerequisites: [Bun](https://bun.sh) (frontend) and Python ≥ 3.10 (backend).

```bash
# Frontend
bun install
bun run dev          # Vite dev server at http://localhost:5173

# Backend (in a separate terminal)
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in UNISON_TOKEN + OPENAI_API_KEY
python server.py       # FastAPI on http://localhost:8001
```

## Before opening a PR

1. `bun run build` must pass (runs `tsc --noEmit` + Vite build).
2. `bun run lint` must pass (Biome lint + format check).
3. Keep changes scoped — one logical change per PR.
4. Update the relevant `.env.example` if you add a new env variable.

## Conventions

- TypeScript + React 19 + Vite for the frontend; Biome for formatting.
- Python 3.10+ for the backend; no extra HTTP client beyond `requests`.
- `UNISON_TOKEN` and `VITE_UNISON_TOKEN` are the canonical env var names.
- Never hard-code a `usk_` token or any API key in source files.
- The `.env` files are git-ignored; `.env.example` files contain only placeholders.
- The `UnisonClient` auth header is `Authorization: Bearer <usk_...>`.

## Reporting bugs / proposing features

Use the issue templates. For security issues, see [`SECURITY.md`](./SECURITY.md) —
do **not** open a public issue.
