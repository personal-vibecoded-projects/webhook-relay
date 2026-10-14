import re
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from relay.models import AuthSession, User
from relay.security import cookie_name, digest


def get_session(request: Request):
    engine = request.app.state.engine
    if engine is None:
        raise HTTPException(503, "Workspace database is not configured")
    try:
        with Session(engine, expire_on_commit=False) as session, session.begin():
            yield session
    except SQLAlchemyError:
        # Never serialize driver diagnostics, SQL values, or connection details.
        raise HTTPException(503, "Database operation failed") from None


# Commit/rollback before a response (including session cookies) can be sent.
DB = Annotated[Session, Depends(get_session, scope="function")]


def current_user(request: Request, session: DB) -> User:
    token = request.cookies.get(cookie_name(request), "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise HTTPException(401, "Sign in to continue")
    user = session.scalar(
        select(User)
        .join(AuthSession, AuthSession.user_id == User.id)
        .where(
            AuthSession.token_hash == digest(token),
            AuthSession.expires_at > func.clock_timestamp(),
            User.enabled.is_(True),
        )
    )
    if user is None:
        raise HTTPException(401, "Session expired; sign in again")
    return user


Actor = Annotated[User, Depends(current_user)]
