import logging
import asyncio
import json
from typing import Literal, TypedDict
from dotenv import load_dotenv
from livekit.agents import JobContext, WorkerOptions, cli
from livekit.agents.voice import Agent, AgentSession
from langgraph.graph import END, StateGraph
from livekit.plugins import deepgram, groq, sarvam, silero, google 

load_dotenv()

logger = logging.getLogger("local-agent")
logger.setLevel(logging.INFO)


class OrchestrationState(TypedDict):
    selected_lang: str
    task_mode: str
    route: str
    instructions: str


SUPPORTED_MODES = {"general", "sales", "support", "technical"}


def _supervisor_node(state: OrchestrationState) -> OrchestrationState:
    selected_lang = state["selected_lang"]
    task_mode = state["task_mode"].lower().strip()

    if task_mode not in SUPPORTED_MODES:
        task_mode = "general"

    route = f"{task_mode}_{'hi' if selected_lang == 'hi' else 'en'}"
    return {
        **state,
        "task_mode": task_mode,
        "route": route,
    }


def _general_hi_node(state: OrchestrationState) -> OrchestrationState:
    return {
        **state,
        "instructions": (
            "You are a helpful general-purpose voice assistant. "
            "Respond primarily in Hindi. Keep responses short and concise. "
            "Never use emojis."
        ),
    }


def _general_en_node(state: OrchestrationState) -> OrchestrationState:
    return {
        **state,
        "instructions": (
            "You are a helpful general-purpose voice assistant. "
            "Respond in English. Keep responses short and concise. "
            "Never use emojis."
        ),
    }


def _sales_hi_node(state: OrchestrationState) -> OrchestrationState:
    return {
        **state,
        "instructions": (
            "You are a Hindi sales assistant. Understand user needs first, "
            "then recommend suitable options with clear benefits and price clarity. "
            "Keep responses short and concise. Never use emojis."
        ),
    }


def _sales_en_node(state: OrchestrationState) -> OrchestrationState:
    return {
        **state,
        "instructions": (
            "You are an English sales assistant. Understand user needs first, "
            "then recommend suitable options with clear benefits and price clarity. "
            "Keep responses short and concise. Never use emojis."
        ),
    }


def _support_hi_node(state: OrchestrationState) -> OrchestrationState:
    return {
        **state,
        "instructions": (
            "You are a Hindi customer support assistant. Diagnose the problem step-by-step, "
            "ask only necessary follow-up questions, and provide actionable fixes. "
            "Keep responses short and concise. Never use emojis."
        ),
    }


def _support_en_node(state: OrchestrationState) -> OrchestrationState:
    return {
        **state,
        "instructions": (
            "You are an English customer support assistant. Diagnose the problem step-by-step, "
            "ask only necessary follow-up questions, and provide actionable fixes. "
            "Keep responses short and concise. Never use emojis."
        ),
    }


def _technical_hi_node(state: OrchestrationState) -> OrchestrationState:
    return {
        **state,
        "instructions": (
            "You are a Hindi technical assistant. Explain technical concepts accurately, "
            "provide practical implementation steps, and call out assumptions. "
            "Keep responses short and concise. Never use emojis."
        ),
    }


def _technical_en_node(state: OrchestrationState) -> OrchestrationState:
    return {
        **state,
        "instructions": (
            "You are an English technical assistant. Explain technical concepts accurately, "
            "provide practical implementation steps, and call out assumptions. "
            "Keep responses short and concise. Never use emojis."
        ),
    }


def _route_from_supervisor(state: OrchestrationState) -> str:
    return state["route"]


def build_orchestrator():
    graph = StateGraph(OrchestrationState)
    graph.add_node("supervisor", _supervisor_node)

    graph.add_node("general_hi", _general_hi_node)
    graph.add_node("general_en", _general_en_node)
    graph.add_node("sales_hi", _sales_hi_node)
    graph.add_node("sales_en", _sales_en_node)
    graph.add_node("support_hi", _support_hi_node)
    graph.add_node("support_en", _support_en_node)
    graph.add_node("technical_hi", _technical_hi_node)
    graph.add_node("technical_en", _technical_en_node)

    graph.set_entry_point("supervisor")

    graph.add_conditional_edges(
        "supervisor",
        _route_from_supervisor,
        {
            "general_hi": "general_hi",
            "general_en": "general_en",
            "sales_hi": "sales_hi",
            "sales_en": "sales_en",
            "support_hi": "support_hi",
            "support_en": "support_en",
            "technical_hi": "technical_hi",
            "technical_en": "technical_en",
        },
    )

    for node_name in [
        "general_hi",
        "general_en",
        "sales_hi",
        "sales_en",
        "support_hi",
        "support_en",
        "technical_hi",
        "technical_en",
    ]:
        graph.add_edge(node_name, END)

    return graph.compile()


ORCHESTRATOR = build_orchestrator()


def get_orchestrated_instructions(selected_lang: str, task_mode: str) -> tuple[str, str]:
    result = ORCHESTRATOR.invoke(
        {
            "selected_lang": selected_lang,
            "task_mode": task_mode,
            "route": "",
            "instructions": "",
        }
    )
    route = result.get("route", "general_en")
    instructions = result.get("instructions", "You are a helpful assistant. Respond briefly.")
    return route, instructions

class LocalAgent(Agent):
    # Modified __init__ to accept configured STT and TTS
    def __init__(self, stt_instance, tts_instance, instructions, orchestration_route) -> None:
        llm = groq.LLM(model="llama-3.3-70b-versatile")
        vad_inst = silero.VAD.load()

        super().__init__(
            instructions=instructions,
            stt=stt_instance,
            llm=llm,
            tts=tts_instance,
            vad=vad_inst
        )

        logger.info(f"LangGraph selected route: {orchestration_route}")
        
        # ... (Metrics wrappers remain the same) ...
        def llm_metrics_wrapper(metrics):
            asyncio.create_task(self.on_llm_metrics_collected(metrics))
        llm.on("metrics_collected", llm_metrics_wrapper)
        
        # Note: You might need to check if stt/tts support metric events before binding
        if hasattr(stt_instance, "on"):
            stt_instance.on("metrics_collected", lambda m: asyncio.create_task(self.on_stt_metrics_collected(m)))
            stt_instance.on("eou_metrics_collected", lambda m: asyncio.create_task(self.on_eou_metrics_collected(m)))
        
        if hasattr(tts_instance, "on"):
            tts_instance.on("metrics_collected", lambda m: asyncio.create_task(self.on_tts_metrics_collected(m)))
            
        vad_inst.on("metrics_collected", lambda m: asyncio.create_task(self.on_vad_event(m)))

    async def on_llm_metrics_collected(self, metrics):
        logger.info(f"LLM Metrics: {metrics}")
    async def on_stt_metrics_collected(self, metrics):
        logger.info(f"STT Metrics: {metrics}")
    async def on_eou_metrics_collected(self, metrics):
        logger.info(f"EOU Metrics: {metrics}")
    async def on_tts_metrics_collected(self, metrics):
        logger.info(f"TTS Metrics: {metrics}")
    async def on_vad_event(self, event):
        pass

async def entrypoint(ctx: JobContext):
    await ctx.connect()
    
    # 1. Wait for a participant to join to read their preferences
    participant = await ctx.wait_for_participant()
    
    # 2. Default Values
    selected_lang = "hi"
    selected_voice = "sarvam"
    selected_mode = "general"
    
    # 3. Read Metadata passed from Frontend
    if participant.metadata:
        try:
            meta = json.loads(participant.metadata)
            selected_lang = meta.get("language", "hi")
            selected_voice = meta.get("voice", "sarvam")
            selected_mode = meta.get("mode", "general")
            logger.info(
                f"User selected -> Lang: {selected_lang}, Voice: {selected_voice}, Mode: {selected_mode}"
            )
        except Exception as e:
            logger.error(f"Failed to parse metadata: {e}")

    # 4. Configure STT based on Language
    # If Hindi -> 'hi', if English -> 'en'
    stt_lang = "hi" if selected_lang == "hi" else "en"
    
    stt = deepgram.STT(
        model="nova-2",
        language=stt_lang
    )

    # 5. Configure TTS based on Voice Selection
    tts = None
    if selected_voice == "sarvam":
        tts = sarvam.TTS(
            target_language_code="hi-IN",  
            speaker="vidya",
            pitch= 0,
            pace= 1,
            loudness= 1,
            speech_sample_rate= 24000,
            enable_preprocessing= "true",
            model= "bulbul:v2"
        )
    elif selected_voice == "gemini":
        tts = google.beta.GeminiTTS(
   model="models/gemini-2.5-flash-preview-tts",
   voice_name="Zephyr",
   instructions="Speak.",
  )
    else:
        # Fallback
        tts = sarvam.TTS(target_language_code="hi-IN", speaker="vidya")

    # 6. Orchestrate instructions with LangGraph supervisor + specialized agents
    orchestration_route, instructions = get_orchestrated_instructions(
        selected_lang=selected_lang,
        task_mode=selected_mode,
    )

    # 7. Start the Agent with dynamic config
    session = AgentSession()
    
    # Pass our dynamically created instances to the class
    agent = LocalAgent(
        stt_instance=stt,
        tts_instance=tts,
        instructions=instructions,
        orchestration_route=orchestration_route,
    )
    
    await session.start(
        agent=agent,
        room=ctx.room
    )

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, job_memory_warn_mb=1500))
