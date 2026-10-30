"""Chanakya's voice-only FastAPI entry point."""

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.tracers.langchain import wait_for_all_tracers

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from agent.graph import Agent
from agent.models import provider_settings
from agent.prompts.prompts import voice_assistant_system_prompt
from backend.twilio_routes import configure_telephony
from backend.twilio_routes import router as telephony_router

voice_agent_instance = None


def llm_key_name():
    """The API key the voice agent needs: OpenRouter, or Groq while OpenRouter is unavailable."""
    return "GROQ_API_KEY" if provider_settings().llm_provider == "groq" else "OPENROUTER_API_KEY"


def missing_configuration(provider="llm_batch"):
    required = [llm_key_name(), "SARVAM_API_KEY"]
    # Decisions retrieval is an OpenRouter-only API.
    if provider == "decisions" and "OPENROUTER_API_KEY" not in required:
        required.append("OPENROUTER_API_KEY")
    if provider == "jev" or os.getenv("VOICE_INTERRUPTION_ENABLED", "false").lower() in {"true", "1", "yes"}:
        required.append("TYPESAFE_API_KEY")
    return [name for name in required if not os.getenv(name, "").strip()]


def create_voice_agent():
    """The planning BrainAgent when PLANNER_ENABLED is on, otherwise the original retrieval agent."""
    settings = provider_settings()
    if settings.planner_enabled:
        from agent.brain_agent import BrainAgent
        from chanakya.brain.contracts.llm import default_llm
        from chanakya.brain.forest.forest import default_forest
        from chanakya.brain.planner_nrpa import NRPAPlanner
        from chanakya.brain.value.network import configured_leaf_value

        planner = NRPAPlanner(forest=default_forest(), leaf_value=configured_leaf_value(settings.planner_value))
        return BrainAgent(llm=default_llm(settings), planner=planner,
                          actions_enabled=settings.actions_enabled)
    return Agent(name="Chanakya-Voice", system_prompt=voice_assistant_system_prompt)


@asynccontextmanager
async def lifespan(app):
    global voice_agent_instance
    if os.getenv(llm_key_name(), "").strip():
        voice_agent_instance = create_voice_agent()
    try:
        configure_telephony(app, voice_agent_instance, os.getenv("SARVAM_API_KEY", ""))
        if getattr(app.state, "telephony", None) and voice_agent_instance is None:
            raise ValueError(f"{llm_key_name()} is required for phone calling")
        yield
    finally:
        try:
            if getattr(app.state, "telephony", None):
                await app.state.telephony.aclose()
            if voice_agent_instance is not None:
                await voice_agent_instance.aclose()
                voice_agent_instance = None
        finally:
            await asyncio.to_thread(wait_for_all_tracers)


app = FastAPI(title="Chanakya Voice API", lifespan=lifespan)
app.include_router(telephony_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "HEAD"],
    allow_headers=["*"],
)


@app.get("/api/health")
@app.head("/api/health")
async def health():
    missing = missing_configuration()
    return {
        "status": "ok",
        "name": "Chanakya Voice API",
        "configured": not missing,
        "missing": missing,
        "agent": voice_agent_instance is not None,
        "telephony": getattr(app.state, "telephony", None) is not None,
    }


@app.websocket("/api/voice/ws")
async def voice_websocket_endpoint(
    websocket: WebSocket,
    retrieval_provider: Literal["decisions", "jev", "llm_batch"] = "llm_batch",
):
    missing = missing_configuration(retrieval_provider)
    if missing or voice_agent_instance is None:
        await websocket.accept()
        await websocket.send_json({
            "type": "voice_error",
            "message": "Voice is not configured yet. Add the provider keys to the server's .env file and restart the backend.",
        })
        await websocket.close(code=1013)
        return
    from backend.voice_pipeline import voice_pipeline
    await voice_pipeline(websocket, voice_agent_instance, retrieval_provider)


# Chanakya mission, action and hand-off APIs (task B5); mounted only when MISSIONS_ENABLED is true.
if os.getenv("MISSIONS_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}:
    from chanakya.actions.api import router as actions_router
    from chanakya.humans.api import router as handoffs_router
    from chanakya.missions.api import router as missions_router

    app.include_router(missions_router)
    app.include_router(actions_router)
    app.include_router(handoffs_router)
    from chanakya.missions.demo_api import router as demo_router

    app.include_router(demo_router)
    from chanakya.brain.calls_api import router as calls_router

    app.include_router(calls_router)

# Chanakya coach mode API (task B11); mounted only when COACH_ENABLED is true.
if os.getenv("COACH_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}:
    from chanakya.humans.coach_api import router as coach_router

    app.include_router(coach_router)
