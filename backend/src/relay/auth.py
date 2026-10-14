import secrets
from datetime import timedelta

from fastapi import HTTPException, Request, Response
from sqlalchemy import case, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from relay.models import AuthSession, AuthThrottle, User
from relay.schemas import Credentials
from relay.security import cookie_name, digest, hash_password, hasher, verify_password


def throttle(request: Request, username: str, *, registration=False):
    """Persist limits independently, including when authentication rolls back."""
    engine = request.app.state.engine
    host = request.client.host if request.client else "unknown"
    scopes = (
        [(f"signup:{host}", 10, 3600)]
        if registration
        else [
            (f"login-ip:{host}", 30, 600),
            (f"login-user:{host}:{username}", 5, 600),
        ]
    )
    denied = False
    with engine.begin() as connection:
        for scope, limit, seconds in scopes:
            now = func.clock_timestamp()
            expired = AuthThrottle.window_started < now - timedelta(seconds=seconds)
            statement = insert(AuthThrottle).values(
                scope_hash=digest(scope), window_started=now, attempts=1
            )
            statement = statement.on_conflict_do_update(
                index_elements=[AuthThrottle.scope_hash],
                set_={
                    "window_started": case(
                        (expired, now), else_=AuthThrottle.window_started
                    ),
                    "attempts": case((expired, 1), else_=AuthThrottle.attempts + 1),
                },
            ).returning(AuthThrottle.attempts)
            denied = connection.scalar(statement) > limit or denied
    if denied:
        raise HTTPException(
            429,
            "Too many authentication attempts; try later",
            headers={"Retry-After": "600"},
        )


def issue_session(session: Session, user: User, request: Request, response: Response):
    now = session.scalar(select(func.now()))
    session.execute(
        delete(AuthSession).where(
            AuthSession.user_id == user.id, AuthSession.expires_at <= now
        )
    )
    existing = session.scalars(
        select(AuthSession.token_hash)
        .where(AuthSession.user_id == user.id)
        .order_by(AuthSession.created_at.desc(), AuthSession.token_hash)
    ).all()
    if len(existing) >= 5:
        session.execute(
            delete(AuthSession).where(AuthSession.token_hash.in_(existing[4:]))
        )
    old_token = request.cookies.get(cookie_name(request))
    if old_token:
        session.execute(
            delete(AuthSession).where(AuthSession.token_hash == digest(old_token))
        )
    token = secrets.token_urlsafe(32)
    session.add(
        AuthSession(
            token_hash=digest(token),
            user_id=user.id,
            expires_at=now + timedelta(hours=12),
        )
    )
    session.flush()
    response.set_cookie(
        cookie_name(request),
        token,
        max_age=43200,
        path="/",
        httponly=True,
        secure=not request.app.state.security.allow_http_cookie,
        samesite="lax",
    )


def register(session: Session, body: Credentials, request: Request, response: Response):
    throttle(request, body.username, registration=True)
    user = User(
        username=body.username,
        password_hash=hash_password(body.password.get_secret_value()),
    )
    session.add(user)
    try:
        session.flush()
    except IntegrityError:
        raise HTTPException(409, "Username already exists") from None
    issue_session(session, user, request, response)
    return user


def login(session: Session, body: Credentials, request: Request, response: Response):
    throttle(request, body.username)
    user = session.scalar(
        select(User).where(User.username == body.username).with_for_update()
    )
    encoded = user.password_hash if user is not None and user.enabled else None
    if not verify_password(body.password.get_secret_value(), encoded):
        raise HTTPException(401, "Invalid username or password")
    if hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password.get_secret_value())
    issue_session(session, user, request, response)
    return user
