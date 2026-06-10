"""
unison_pipecat.py — Pipecat processor with persistent memory via the Unison brain.

Drop-in replacement for supermemory-pipecat:

    from unison_pipecat import UnisonPipecatService

    memory = UnisonPipecatService(
        token=os.getenv("UNISON_TOKEN"),
        user_id="user_123",
        params=UnisonPipecatService.InputParams(mode="full", search_limit=10),
    )

The processor sits between the user context aggregator and the LLM in your
Pipecat pipeline:

    pipeline = Pipeline([
        transport.input(),
        user_aggregator,
        memory,      # <-- inject here
        llm,
        tts,
        transport.output(),
        assistant_aggregator,
    ])

On every LLMContextFrame the processor:

  1. Searches the Unison brain for relevant memories (mode "query" or "full").
  2. Reads the user's persistent profile document (mode "profile" or "full").
  3. Injects the retrieved context into the system message inside the context.
  4. Passes the augmented LLMContextFrame downstream to the LLM.
  5. Writes a concise session note to the user's private brain namespace after
     each turn so memories accumulate across sessions.

Auth: reads UNISON_TOKEN (a usk_... key) from env or the token= constructor
argument.  UNISON_API_URL overrides the default https://api.unisonlabs.ai.
"""

from __future__ import annotations

import os
import textwrap
from copy import deepcopy
from dataclasses import dataclass
from typing import Literal

import requests
from loguru import logger
from pipecat.frames.frames import Frame, LLMContextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


# ---------------------------------------------------------------------------
# Minimal Unison REST client (no extra deps beyond `requests`)
# ---------------------------------------------------------------------------

class UnisonError(Exception):
    """Raised on non-2xx responses from the Unison API."""

    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(f"[{status}] {code}: {message}")
        self.code = code
        self.status = status


class UnisonClient:
    """Thin synchronous REST client for the Unison brain API."""

    DEFAULT_BASE_URL = "https://api.unisonlabs.ai"

    def __init__(self, token: str, base_url: str | None = None) -> None:
        self._token = token
        self._base = (base_url or os.getenv("UNISON_API_URL") or self.DEFAULT_BASE_URL).rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _url(self, path: str) -> str:
        return f"{self._base}/v1{path}"

    def _check(self, resp: requests.Response) -> dict:
        if resp.ok:
            try:
                return resp.json()
            except Exception:
                return {}
        try:
            body = resp.json()
            err = body.get("error", {})
            if isinstance(err, str):
                code, msg = "api_error", err
            else:
                code = err.get("code", "api_error")
                msg = err.get("message", resp.text)
        except Exception:
            code, msg = "api_error", resp.text
        raise UnisonError(code, msg, resp.status_code)

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Search the brain with hybrid keyword+semantic search."""
        params: dict[str, object] = {"q": query, "k": min(max(limit, 1), 50)}
        resp = requests.get(
            self._url("/brain/search"),
            headers=self._headers(),
            params=params,
            timeout=15,
        )
        data = self._check(resp)
        return data.get("results", [])

    def get_doc(self, path: str) -> dict | None:
        """Read a single document by path. Returns None if not found (404)."""
        resp = requests.get(
            self._url("/brain/doc"),
            headers=self._headers(),
            params={"path": path},
            timeout=10,
        )
        if resp.status_code == 404:
            return None
        return self._check(resp)

    def write_doc(
        self,
        path: str,
        body_md: str,
        title: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Create or overwrite a document."""
        payload: dict[str, object] = {"path": path, "bodyMd": body_md}
        if title:
            payload["title"] = title
        if tags:
            payload["tags"] = tags
        resp = requests.put(
            self._url("/brain/doc"),
            headers=self._headers(),
            json=payload,
            timeout=15,
        )
        return self._check(resp)

    def whoami(self) -> dict:
        """Return the authenticated user/tenant information."""
        resp = requests.get(self._url("/auth/whoami"), headers=self._headers(), timeout=5)
        return self._check(resp)

    def status(self) -> dict:
        """Return brain health/stats."""
        resp = requests.get(self._url("/brain/status"), headers=self._headers(), timeout=5)
        return self._check(resp)


# ---------------------------------------------------------------------------
# Pipecat processor
# ---------------------------------------------------------------------------

class UnisonPipecatService(FrameProcessor):
    """
    Pipecat frame processor that gives the agent long-term memory via Unison.

    Intercepts LLMContextFrame objects flowing from the user aggregator to the
    LLM, augments the system message with relevant memories retrieved from the
    Unison brain, then passes the enriched frame downstream.  After each turn
    it writes a session note so knowledge accumulates across sessions.
    """

    @dataclass
    class InputParams:
        mode: Literal["profile", "query", "full"] = "full"
        """
        profile — retrieve only the user's persistent profile document.
        query   — run a semantic search for relevant memories.
        full    — do both (default).
        """

        search_limit: int = 10
        """Number of search hits to retrieve (1–50)."""

        search_threshold: float = 0.0
        """Minimum relevance score for a search hit (0.0 = include everything)."""

        memory_tag: str = "pipecat"
        """Tag applied to session note documents written by this processor."""

        profile_path_template: str = "/private/notes/user-{user_id}-profile.md"
        """
        Path template for the per-user profile document.
        {user_id} is substituted at runtime (slugified).
        Flat layout satisfies the brain FS contract (one slug segment).
        """

        notes_path_template: str = "/private/notes/user-{user_id}-{session_id}.md"
        """
        Path template for per-session notes written after each turn.
        {user_id} and {session_id} are substituted at runtime (slugified).
        Flat layout satisfies the brain FS contract (one slug segment).
        """

    def __init__(
        self,
        token: str | None = None,
        user_id: str = "default",
        session_id: str = "default",
        base_url: str | None = None,
        params: InputParams | None = None,
    ) -> None:
        super().__init__()
        resolved_token = token or os.getenv("UNISON_TOKEN")
        if not resolved_token:
            raise ValueError(
                "UnisonPipecatService requires a Unison API token. "
                "Set UNISON_TOKEN env var or pass token= to the constructor."
            )
        self._client = UnisonClient(token=resolved_token, base_url=base_url)
        self._user_id = user_id
        self._session_id = session_id
        self._params = params or self.InputParams()
        # Buffer the latest user message for the post-turn write
        self._last_user_message: str | None = None

    # ── path helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _slug(value: str) -> str:
        """
        Slugify a value for use in a brain path segment.
        Lowercases, collapses non-alphanumeric runs to single dashes, trims ends.
        """
        import re
        s = re.sub(r"[^a-z0-9]+", "-", value.lower())
        return s.strip("-")

    def _profile_path(self) -> str:
        return self._params.profile_path_template.format(
            user_id=self._slug(self._user_id),
            session_id=self._slug(self._session_id),
        )

    def _notes_path(self) -> str:
        return self._params.notes_path_template.format(
            user_id=self._slug(self._user_id),
            session_id=self._slug(self._session_id),
        )

    # ── memory retrieval ───────────────────────────────────────────────────

    def _retrieve_context(self, user_text: str) -> str:
        """
        Pull relevant context from the Unison brain based on the current user
        message.  Returns a formatted Markdown string for system-prompt injection,
        or an empty string when nothing useful was found.
        """
        sections: list[str] = []

        if self._params.mode in ("query", "full"):
            try:
                hits = self._client.search(user_text, limit=self._params.search_limit)
                relevant = [
                    h for h in hits
                    if (h.get("score") or 0.0) >= self._params.search_threshold
                ]
                if relevant:
                    lines = ["## Relevant memories from past conversations"]
                    for hit in relevant:
                        doc = hit.get("doc", {})
                        highlight = hit.get("highlight") or ""
                        title = doc.get("title") or doc.get("path") or "memory"
                        snippet = highlight or doc.get("tldr") or ""
                        entry = f"- **{title}**"
                        if snippet:
                            entry += f": {snippet}"
                        lines.append(entry)
                    sections.append("\n".join(lines))
            except UnisonError as exc:
                logger.warning(f"Unison search failed (continuing without): {exc}")

        if self._params.mode in ("profile", "full"):
            try:
                doc = self._client.get_doc(self._profile_path())
                if doc and doc.get("bodyMd"):
                    sections.append(f"## User profile\n{doc['bodyMd']}")
            except UnisonError as exc:
                logger.warning(f"Unison profile fetch failed: {exc}")

        if not sections:
            return ""
        return "\n\n".join(sections)

    # ── memory write ────────────────────────────────────────────────────────

    def _save_turn(self, user_text: str) -> None:
        """
        Append the latest user turn to the per-session notes document in the
        user's private brain namespace.
        """
        notes_path = self._notes_path()
        try:
            existing = self._client.get_doc(notes_path)
            existing_body: str = (existing or {}).get("bodyMd") or ""
        except UnisonError:
            existing_body = ""

        entry = f"- {user_text}"
        if existing_body:
            updated_body = f"{existing_body.rstrip()}\n{entry}"
        else:
            updated_body = textwrap.dedent(f"""\
                # Session notes: {self._session_id}

                User: {self._user_id}

                ## Conversation excerpts

                {entry}
            """)

        try:
            self._client.write_doc(
                path=notes_path,
                body_md=updated_body,
                title=f"Session {self._session_id}",
                tags=[self._params.memory_tag, f"user:{self._user_id}"],
            )
            logger.debug(f"Unison: wrote session note → {notes_path}")
        except UnisonError as exc:
            logger.warning(f"Unison: failed to write session note: {exc}")

    # ── frame processing ────────────────────────────────────────────────────

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:  # noqa: D401
        if not isinstance(frame, LLMContextFrame):
            await self.push_frame(frame, direction)
            return

        context = frame.context

        # Extract the latest user message text for retrieval + session write
        messages = context.get_messages()
        user_text: str | None = None
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "user":
                content = msg.get("content")
                if isinstance(content, str) and content.strip():
                    user_text = content.strip()
                    break
                if isinstance(content, list):
                    # Multi-part content (text + images)
                    text_parts = [
                        p["text"] for p in content
                        if isinstance(p, dict) and p.get("type") == "text" and p.get("text")
                    ]
                    if text_parts:
                        user_text = " ".join(text_parts).strip()
                        break

        if not user_text:
            await self.push_frame(frame, direction)
            return

        # Retrieve context from Unison and inject into the system message
        memory_block = self._retrieve_context(user_text)
        if memory_block:
            augmented_context = deepcopy(context)
            msgs = augmented_context.get_messages()
            system_idx = next(
                (i for i, m in enumerate(msgs) if isinstance(m, dict) and m.get("role") == "system"),
                None,
            )
            injection = f"\n\n---\n[Memory context from Unison brain]\n\n{memory_block}\n---"
            if system_idx is not None:
                existing = msgs[system_idx].get("content") or ""
                msgs[system_idx] = {**msgs[system_idx], "content": existing + injection}
            else:
                msgs.insert(0, {"role": "system", "content": injection.strip()})
            augmented_context.set_messages(msgs)
            frame = LLMContextFrame(context=augmented_context)

        # Save the user turn to the brain (runs synchronously; move to
        # asyncio.to_thread if your pipeline is latency-critical)
        try:
            self._save_turn(user_text)
        except Exception as exc:
            logger.warning(f"Unison memory save error: {exc}")

        await self.push_frame(frame, direction)
