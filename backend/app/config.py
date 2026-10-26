import os
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND = Path(__file__).resolve().parents[1]  # .../backend locally, /app in Docker
# In Docker data/ is mounted at /app/data; locally it sits next to backend/. ARIADNE_DATA_DIR overrides.
DATA_DIR = Path(os.environ["ARIADNE_DATA_DIR"]) if os.environ.get("ARIADNE_DATA_DIR") else (
    BACKEND / "data" if (BACKEND / "data").exists() else BACKEND.parent / "data")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=[str(BACKEND.parent / ".env"), str(BACKEND / ".env")], extra="ignore"
    )

    database_url: str = "postgresql+psycopg://ariadne:ariadne@localhost:5433/ariadne"
    chroma_path: str = str(DATA_DIR / "chroma")
    upload_dir: str = str(DATA_DIR / "uploads")
    jwt_secret: str = "dev-secret-change-me-ariadne-0123456789"
    jwt_hours: int = 12

    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    langsmith_api_key: str = ""

    # Gemini drives the agentic reasoning (triage, tool-using advisor, RAG grading, recovery planning)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash-lite"   # measured 2026-10-26: ~1.0 s/call (3.5-flash-lite: 18-24 s then 504)
    gemini_fallback_model: str = "gemini-2.5-flash"  # used when the primary errors or times out (~1.5 s/call)
    gemini_rpm: int = 20                           # client-side requests/minute ceiling
    llm_budget_per_request: int = 40               # max LLM calls for one user request incl. child incidents
    llm_max_tool_steps: int = 4
    llm_timeout_s: int = 15                        # hard cap per LLM request; on timeout the rule-based path takes over
    disease_fallback: str = ""                     # "gemini": use Gemini vision until a trained model is dropped in

    run_mode: str = "async"          # async: graph runs/guardian run in background threads; inline: synchronously (tests)
    guardian_workers: int = 4        # incidents the guardian runs in parallel
    guardian_mode: str = "auto"       # auto: LLM agent, rules when the LLM is unavailable | agent: LLM only | rules: deterministic pipeline | optimizer: exact CP-SAT, no LLM (baseline)
    agent_max_steps: int = 20        # tool calls one agent episode may make
    agent_max_offers: int = 8        # offers one episode may send

    allow_demo_reset: bool = False  # enables POST /api/system/reset-demo (docker-compose sets it)

    # Recovery pipeline
    max_searches: int = 5
    vehicle_capacity_kg: int = 400
    max_vehicles: int = 10          # trucks a single route plan may use
    routing_provider: str = "haversine"  # haversine (x road_factor) | osrm (real road distances; falls back to haversine on any failure)
    osrm_url: str = "https://router.project-osrm.org"
    memory_enabled: bool = True      # ablation switch: False = the agent/optimiser ignore deal history (acceptance = prior)
    agent_log_regret: bool = False   # evaluation: after each episode also solve the exact optimum and log the cost gap (adds ~4 s)
    agent_tools: str = "full"        # full | no_optimizer (ablation: LLM agent without the optimiser/score tools)
    road_factor: float = 1.35
    avg_speed_kmh: float = 40.0
    service_minutes: int = 10

    @field_validator("groq_api_key", "gemini_api_key", "langsmith_api_key", mode="before")
    @classmethod
    def _strip_secret(cls, v):
        return v.strip() if isinstance(v, str) else v  # a key line holding only whitespace must not count as a key

    @property
    def psycopg_url(self) -> str:
        return self.database_url.replace("+psycopg", "")


settings = Settings()
