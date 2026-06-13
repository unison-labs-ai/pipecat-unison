# Security Policy

## Reporting a vulnerability

Please report security issues privately — **do not open a public GitHub issue.**

Email **security@unisonlabs.ai** with:

- a description of the issue and its impact,
- steps to reproduce (a proof-of-concept if you have one),
- any suggested remediation.

We aim to acknowledge within 3 business days and to keep you updated as we
investigate. We'll credit reporters who want it once a fix ships.

## Scope

This repository is a **demo integration** (Pipecat voice pipeline + Unison brain
memory). It holds no secrets and is not a security boundary — all authentication,
authorization, and workspace isolation are enforced **server-side** by the Unison
brain API. Reports about this client are most useful when they concern:

- credential handling (`UNISON_TOKEN` / `VITE_UNISON_TOKEN` env vars),
- accidental exposure of `usk_...` tokens in logs, error messages, or source files,
- dependency or supply-chain risks in `requirements.txt` or `package.json`.

Server-side or account issues should also go to the same address.

## Handling of credentials

The Unison token (`usk_...`) is read from the `UNISON_TOKEN` environment variable
(backend) or `VITE_UNISON_TOKEN` (frontend). It is:

- never written to any file by this codebase,
- never logged or included in error responses,
- transmitted only to the configured Unison API host as an `Authorization: Bearer` header.

The `.env` file is git-ignored. Never commit a real token to source control.
