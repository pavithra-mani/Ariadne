from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, chat, data, deals, knowledge, ops
from app.db.models import Base
from app.db.session import engine, ensure_schema
from app.graph.runtime import close_graph, init_graph


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    ensure_schema()
    init_graph()
    yield
    close_graph()


app = FastAPI(title="Ariadne", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(auth.router)
app.include_router(data.router)
app.include_router(ops.router)
app.include_router(knowledge.router)
app.include_router(chat.router)
app.include_router(deals.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
