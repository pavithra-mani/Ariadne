import os
from pathlib import Path

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
    gemini_model: str = "gemini-3.5-flash-lite"   # fast, generous free-tier limits (checked live)
    gemini_rpm: int = 20                           # client-side requests/minute ceiling
    llm_budget_per_request: int = 40               # max LLM calls for one user request incl. child incidents
    llm_max_tool_steps: int = 4
    disease_fallback: str = ""                     # "gemini": use Gemini vision until a trained model is dropped in

    allow_demo_reset: bool = False  # enables POST /api/system/reset-demo (docker-compose sets it)

    # Recovery pipeline
    max_searches: int = 5
    vehicle_capacity_kg: int = 400
    max_vehicles: int = 3
    road_factor: float = 1.35
    avg_speed_kmh: float = 40.0
    service_minutes: int = 10

    @property
    def psycopg_url(self) -> str:
        return self.database_url.replace("+psycopg", "")


settings = Settings()
