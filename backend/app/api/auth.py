from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models import Entity, User
from app.db.session import get_db
from app.security import current_user, make_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


def user_out(db: Session, u: User) -> dict:
    e = db.get(Entity, u.entity_id)
    return {"id": u.id, "username": u.username, "role": u.role, "display_name": u.display_name,
            "entity_id": u.entity_id, "entity_name": e.name, "village": e.village}


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.username == body.username.strip().lower()).first()
    if not u or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "Invalid username or password")
    return {"token": make_token(u), "user": user_out(db, u)}


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return user_out(db, user)
