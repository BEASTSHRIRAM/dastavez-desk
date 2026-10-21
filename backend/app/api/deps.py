from collections.abc import Callable, Iterator

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app import db
from app.repositories.cases import TenantRepo
from app.repositories.catalog import PartyRepo, TemplateRepo
from app.services.auth import Principal, read_token


def get_session() -> Iterator[Session]:
    # looked up at call time so tests and settings reloads see the current SessionLocal
    with db.SessionLocal() as session:
        yield session


def principal(authorization: str | None = Header(default=None)) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in to continue.")
    p = read_token(authorization[7:].strip())
    if p is None:
        raise HTTPException(401, "Your session has expired. Sign in again.")
    return p


def require(minimum: str) -> Callable[[Principal], Principal]:
    def check(p: Principal = Depends(principal)) -> Principal:
        if not p.can(minimum):
            raise HTTPException(403, "Your role does not allow this action.")
        return p
    return check


def repo(p: Principal = Depends(principal), session: Session = Depends(get_session)) -> TenantRepo:
    return TenantRepo(session, p.tenant_id)


def parties(p: Principal = Depends(principal), session: Session = Depends(get_session)) -> PartyRepo:
    return PartyRepo(session, p.tenant_id)


def templates(p: Principal = Depends(principal), session: Session = Depends(get_session)) -> TemplateRepo:
    return TemplateRepo(session, p.tenant_id)
