from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db():
    with SessionLocal() as db:
        yield db


@contextmanager
def session_scope() -> Session:
    """Transactional scope for code running outside a request (graph nodes, seed)."""
    with SessionLocal() as db:
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise


def ensure_schema() -> None:
    """Tiny forward-only migration so existing databases gain new columns without a reset."""
    from sqlalchemy import text
    with engine.begin() as c:
        c.execute(text("ALTER TABLE entities ADD COLUMN IF NOT EXISTS owner_id INTEGER"))
        c.execute(text("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS level VARCHAR(10) DEFAULT 'info'"))
        c.execute(text("ALTER TABLE deals ADD COLUMN IF NOT EXISTS seller_decision VARCHAR(10) DEFAULT 'pending'"))
        c.execute(text("ALTER TABLE deals ADD COLUMN IF NOT EXISTS buyer_decision VARCHAR(10) DEFAULT 'pending'"))
        c.execute(text("ALTER TABLE deals ADD COLUMN IF NOT EXISTS rejected_by INTEGER"))
        c.execute(text("ALTER TABLE deals ALTER COLUMN deal_type TYPE VARCHAR(40)"))
        c.execute(text("ALTER TABLE deals ADD COLUMN IF NOT EXISTS decline_reason VARCHAR(300) DEFAULT ''"))
        c.execute(text("ALTER TABLE deals ADD COLUMN IF NOT EXISTS origin VARCHAR(10) DEFAULT 'pipeline'"))
        c.execute(text("ALTER TABLE deals ADD COLUMN IF NOT EXISTS event_id INTEGER"))
