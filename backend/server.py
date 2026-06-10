"""
server.py — FastAPI + Pipecat voice server with Unison brain memory.

The voice pipeline runs here (STT/LLM/TTS via OpenAI).
A separate Vite+React frontend connects over WebSocket using the Pipecat JS client.

Quick start:
    cp .env.example .env          # fill in UNISON_TOKEN and OPENAI_API_KEY
    python -m venv venv && source venv/bin/activate
    pip install -r requirements.txt
    python server.py
"""

import os
import re
import sys
import uuid

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Query, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMContextFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.processors.frameworks.rtvi import (
    RTVIConfig,
    RTVIObserver,
    RTVIProcessor,
)
from pipecat.serializers.protobuf import ProtobufFrameSerializer
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.openai.tts import OpenAITTSService
from pipecat.services.openai.stt import OpenAISTTService
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

from unison_pipecat import UnisonClient, UnisonError, UnisonPipecatService


def _slug(value: str) -> str:
    """Slugify a value for use in a brain path segment (mirrors UnisonPipecatService._slug)."""
    s = re.sub(r"[^a-z0-9]+", "-", value.lower())
    return s.strip("-")

load_dotenv(override=True)

logger.remove(0)
logger.add(sys.stderr, level="DEBUG")

app = FastAPI(title="Pipecat + Unison Brain Voice Bot")

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SYSTEM_PROMPT = """You are a helpful voice assistant with persistent memory capabilities.
You remember information from past conversations and use it to provide personalized responses.
Keep your responses brief and conversational — one or two sentences at most.
Your output will be converted to audio so don't include special characters or markdown.
When greeting users, be natural and casual — use their name if you know it from past conversations.
Invite conversation naturally like 'hey, how's it going?' rather than formal introductions."""


async def run_bot(websocket_client, user_id: str, session_id: str) -> None:
    logger.info(f"Starting bot | user={user_id} session={session_id}")

    transport = FastAPIWebsocketTransport(
        websocket=websocket_client,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
            vad_audio_passthrough=True,
            serializer=ProtobufFrameSerializer(),
        ),
    )

    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY is not set")

    unison_token = os.getenv("UNISON_TOKEN")
    if not unison_token:
        raise ValueError("UNISON_TOKEN is not set")

    stt = OpenAISTTService(api_key=openai_api_key)

    llm = OpenAILLMService(
        api_key=openai_api_key,
        model="gpt-4o-mini",
    )

    tts = OpenAITTSService(
        api_key=openai_api_key,
        voice="alloy",
    )

    memory = UnisonPipecatService(
        token=unison_token,
        user_id=user_id,
        session_id=session_id,
        params=UnisonPipecatService.InputParams(
            mode="full",
            search_limit=10,
            search_threshold=0.0,
        ),
    )

    context = LLMContext(messages=[{"role": "system", "content": SYSTEM_PROMPT}])
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(context)

    rtvi = RTVIProcessor(config=RTVIConfig(config=[]))

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            rtvi,
            user_aggregator,
            memory,          # Unison memory: retrieves past context + writes session notes
            llm,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        observers=[RTVIObserver(rtvi)],
    )

    @rtvi.event_handler("on_client_ready")
    async def on_client_ready(rtvi):
        logger.info(f"Client ready | user={user_id}")
        await rtvi.set_bot_ready()
        greet_context = LLMContext(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": "Greet me casually and naturally, like you're starting a friendly conversation.",
                },
            ]
        )
        await task.queue_frames([LLMContextFrame(context=greet_context)])

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info(f"Client connected | user={user_id}")

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info(f"Client disconnected | user={user_id}")
        await task.cancel()

    runner = PipelineRunner(handle_sigint=False)
    await runner.run(task)


@app.post("/connect")
async def connect(
    request: Request,
    userId: str = Query(default=None),
    sessionId: str = Query(default=None),
):
    user_id = userId or f"user-{uuid.uuid4().hex[:12]}"
    session_id = sessionId or f"session-{uuid.uuid4().hex[:8]}"

    ws_host = os.getenv("WS_HOST", request.headers.get("host", "localhost:8001"))
    ws_protocol = "wss" if os.getenv("USE_SSL", "false").lower() == "true" else "ws"

    return JSONResponse(
        {
            "wsUrl": f"{ws_protocol}://{ws_host}/ws?userId={user_id}&sessionId={session_id}",
        }
    )


@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    userId: str = Query(default=None),
    sessionId: str = Query(default=None),
):
    await websocket.accept()

    user_id = userId or f"user-{uuid.uuid4().hex[:12]}"
    session_id = sessionId or f"session-{uuid.uuid4().hex[:8]}"

    logger.info(f"WebSocket connection | user={user_id} session={session_id}")

    try:
        await run_bot(websocket, user_id, session_id)
    except Exception as exc:
        logger.error(f"Bot error | user={user_id}: {exc}")
    finally:
        logger.info(f"WebSocket closed | user={user_id}")


@app.get("/api/memories")
async def list_memories(userId: str = Query(...), query: str = Query(default=None)):
    """Search or list memories for a given userId from the Unison brain."""
    unison_token = os.getenv("UNISON_TOKEN")
    if not unison_token:
        return JSONResponse({"error": "UNISON_TOKEN not configured"}, status_code=500)

    client = UnisonClient(token=unison_token)
    memories = []

    try:
        if query:
            hits = client.search(query, limit=50)
            memories = [
                {
                    "id": hit.get("doc", {}).get("id", f"hit-{i}"),
                    "memory": hit.get("highlight") or hit.get("doc", {}).get("tldr") or hit.get("doc", {}).get("title") or "",
                    "path": hit.get("doc", {}).get("path", ""),
                    "score": hit.get("score", 0),
                    "created_at": hit.get("doc", {}).get("updatedAt") or "",
                    "type": "search_result",
                }
                for i, hit in enumerate(hits)
            ]
        else:
            prefix = f"/private/notes/user-{_slug(userId)}-"
            docs = client._check(
                requests.get(
                    client._url("/brain/list"),
                    headers=client._headers(),
                    params={"prefix": prefix, "limit": 100},
                    timeout=10,
                )
            ).get("documents", [])
            memories = [
                {
                    "id": doc.get("id", f"doc-{i}"),
                    "memory": doc.get("tldr") or doc.get("title") or doc.get("path", ""),
                    "path": doc.get("path", ""),
                    "created_at": doc.get("updatedAt") or "",
                    "type": "session_note",
                }
                for i, doc in enumerate(docs)
            ]
    except UnisonError as exc:
        return JSONResponse({"error": str(exc)}, status_code=exc.status)
    except Exception as exc:
        logger.error(f"list_memories error: {exc}")
        return JSONResponse({"error": str(exc)}, status_code=500)

    return JSONResponse({"memories": memories})


@app.get("/api/profile")
async def get_profile(userId: str = Query(...)):
    """Return the user's persistent profile document as static/dynamic facts.

    The Unison profile document lives at /private/notes/user-{userId}-profile.md.
    Its body is free-form Markdown; we surface the full text as a dynamic fact
    so the frontend can display it — or an empty profile when none exists yet.
    """
    unison_token = os.getenv("UNISON_TOKEN")
    if not unison_token:
        return JSONResponse({"error": "UNISON_TOKEN not configured"}, status_code=500)

    client = UnisonClient(token=unison_token)
    profile_path = f"/private/notes/user-{_slug(userId)}-profile.md"

    try:
        doc = client.get_doc(profile_path)
    except UnisonError as exc:
        return JSONResponse({"error": str(exc)}, status_code=exc.status)
    except Exception as exc:
        logger.error(f"get_profile error: {exc}")
        return JSONResponse({"error": str(exc)}, status_code=500)

    if not doc or not doc.get("bodyMd"):
        return JSONResponse({"profile": {"static": [], "dynamic": []}})

    body: str = doc["bodyMd"]
    # Split into non-empty lines for rendering as individual fact chips.
    # Lines starting with "# " or "## " are headers — treat them as static
    # (stable facts); plain bullet / paragraph lines are dynamic (session-derived).
    static_facts: list[str] = []
    dynamic_facts: list[str] = []
    for line in body.splitlines():
        stripped = line.strip().lstrip("- ").strip()
        if not stripped:
            continue
        if line.startswith("#"):
            static_facts.append(stripped.lstrip("# ").strip())
        else:
            dynamic_facts.append(stripped)

    return JSONResponse({
        "profile": {
            "static": static_facts,
            "dynamic": dynamic_facts[:20],
        }
    })


@app.get("/api/documents")
async def list_documents(
    userId: str = Query(...),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=100),
):
    """List session-note documents for the given user.

    Returns the most-recent `limit` session-note documents written by
    UnisonPipecatService for this user, ordered newest-first.
    """
    unison_token = os.getenv("UNISON_TOKEN")
    if not unison_token:
        return JSONResponse({"error": "UNISON_TOKEN not configured"}, status_code=500)

    client = UnisonClient(token=unison_token)
    sessions_prefix = f"/private/notes/user-{_slug(userId)}-"

    try:
        raw = client._check(
            requests.get(
                client._url("/brain/list"),
                headers=client._headers(),
                params={"prefix": sessions_prefix, "limit": limit * page},
                timeout=10,
            )
        )
    except UnisonError as exc:
        return JSONResponse({"error": str(exc)}, status_code=exc.status)
    except Exception as exc:
        logger.error(f"list_documents error: {exc}")
        return JSONResponse({"error": str(exc)}, status_code=500)

    all_docs = raw.get("documents", [])
    # Sort newest-first by updatedAt / createdAt
    all_docs.sort(key=lambda d: d.get("updatedAt") or d.get("createdAt") or "", reverse=True)
    page_docs = all_docs[(page - 1) * limit: page * limit]

    documents = [
        {
            "id": doc.get("id", f"doc-{i}"),
            "title": doc.get("title") or doc.get("path", "").split("/")[-1],
            "summary": doc.get("tldr") or "",
            "createdAt": doc.get("createdAt") or doc.get("updatedAt") or "",
            "path": doc.get("path", ""),
        }
        for i, doc in enumerate(page_docs)
    ]

    return JSONResponse({"documents": documents})


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "provider": "unison",
        "version": "1.0.0",
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8001"))
    host = os.getenv("HOST", "0.0.0.0")

    logger.info(f"Starting server on {host}:{port}")
    uvicorn.run(app, host=host, port=port)
