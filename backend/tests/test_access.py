import os
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from http.cookies import SimpleCookie
from queue import Queue
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from relay import access
from relay.database import migration_engine
from relay.main import create_app
from relay.models import (
    AuditEvent,
    AuthSession,
    Invitation,
    Membership,
    User,
    Workspace,
)
from relay.provision import grant_runtime_access
from relay.schemas import WorkspaceRename
from relay.security import COOKIE, SecuritySettings

pytestmark = [
    pytest.mark.database,
    pytest.mark.skipif(
        os.environ.get("RUN_DATABASE_TESTS") != "1", reason="Requires PostgreSQL"
    ),
]
ORIGIN = "https://relay.example"


@pytest.fixture
def clients(database):
    app = create_app(database, SecuritySettings(public_origin=ORIGIN))
    opened = []

    def make(username):
        client = TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN})
        client.__enter__()
        opened.append(client)
        password = secrets.token_urlsafe(24)
        result = client.post(
            "/api/auth/register", json={"username": username, "password": password}
        )
        assert result.status_code == 201
        return client, result.json(), password

    yield make
    for client in reversed(opened):
        client.__exit__(None, None, None)


def workspace(client, slug="demo-team"):
    response = client.post("/api/workspaces", json={"slug": slug, "name": "Demo team"})
    assert response.status_code == 201
    return response.json()["id"]


def join(owner, target, workspace_id, role="member"):
    response = owner.post(
        f"/api/workspaces/{workspace_id}/invitations",
        json={"username": target[1]["username"], "role": role},
    )
    assert response.status_code == 201
    invite_id = response.json()["id"]
    assert target[0].post(f"/api/invitations/{invite_id}/accept").status_code == 200
    return invite_id


def test_registration_uses_private_secure_cookie_and_redacted_storage(
    clients, database
):
    client, user, _ = clients("owner")
    assert set(user) == {"id", "username"}
    assert client.get("/api/auth/me").json() == user
    with Session(database) as session:
        row = session.get(User, UUID(user["id"]))
        is_argon2 = row.password_hash.startswith("$argon2id$")
        assert is_argon2
        hashes_have_expected_length = all(
            len(s.token_hash) == 64 for s in session.scalars(select(AuthSession))
        )
        assert hashes_have_expected_length
    response = client.get("/api/auth/me")
    assert response.headers["cache-control"] == "no-store"


def test_session_cookie_flags_and_logout_revocation(clients, database):
    client, user, password = clients("owner")
    response = client.post(
        "/api/auth/login", json={"username": user["username"], "password": password}
    )
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    http_only, secure, same_site, path = (
        cookie[COOKIE][k] for k in ("httponly", "secure", "samesite", "path")
    )
    assert http_only and secure
    assert same_site == "lax" and path == "/"
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(AuthSession)) == 0


@pytest.mark.parametrize("origin", [None, "https://evil.example", "null"])
def test_mutations_reject_missing_or_cross_site_origin(clients, origin):
    client, _, _ = clients("owner")
    client.headers.pop("origin")
    headers = {"Origin": origin} if origin else {}
    assert (
        client.post(
            "/api/workspaces",
            json={"slug": "demo-team", "name": "Team"},
            headers=headers,
        ).status_code
        == 403
    )
    assert client.get("/api/workspaces").json()["items"] == []


def test_expired_and_disabled_sessions_cannot_access_workspaces(clients, database):
    client, user, password = clients("owner")
    workspace(client)
    with database.begin() as connection:
        connection.execute(
            update(AuthSession).values(expires_at=func.now() - timedelta(seconds=1))
        )
    assert client.get("/api/workspaces").status_code == 401
    assert (
        client.post(
            "/api/auth/login", json={"username": user["username"], "password": password}
        ).status_code
        == 200
    )
    with database.begin() as connection:
        connection.execute(
            update(User).where(User.id == UUID(user["id"])).values(enabled=False)
        )
    assert client.get("/api/workspaces").status_code == 401


def test_failed_login_limits_survive_failed_requests(clients):
    client, user, _ = clients("owner")
    wrong = secrets.token_urlsafe(24)
    for _ in range(5):
        assert (
            client.post(
                "/api/auth/login",
                json={"username": user["username"], "password": wrong},
            ).status_code
            == 401
        )
    response = client.post(
        "/api/auth/login", json={"username": user["username"], "password": wrong}
    )
    assert response.status_code == 429
    assert response.headers["retry-after"] == "600"


def test_validation_never_echoes_password_input(clients):
    client, _, _ = clients("owner")
    response = client.post(
        "/api/auth/register",
        json={"username": "other", "password": secrets.token_urlsafe(2)},
    )
    assert response.status_code == 422
    errors = response.json()["detail"]
    assert all(set(item) == {"loc", "msg", "type"} for item in errors)


def test_nonmembers_cannot_probe_real_workspace_resources(clients):
    owner = clients("owner")[0]
    outsider = clients("outsider")[0]
    identifier = workspace(owner)
    assert owner.get(f"/api/workspaces/{identifier}").status_code == 200
    for suffix in ("", "/members", "/invitations", "/audit"):
        assert outsider.get(f"/api/workspaces/{identifier}{suffix}").status_code == 404
    assert outsider.get("/api/workspaces").json()["items"] == []
    assert (
        outsider.patch(
            f"/api/workspaces/{identifier}", json={"name": "Stolen"}
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "role,allowed", [("admin", True), ("member", False), ("viewer", False)]
)
def test_role_matrix_for_workspace_management(clients, role, allowed):
    owner = clients("owner")[0]
    target = clients("target")
    identifier = workspace(owner)
    join(owner, target, identifier, role)
    assert target[0].get(f"/api/workspaces/{identifier}/members").status_code == 200
    assert target[0].patch(
        f"/api/workspaces/{identifier}", json={"name": "Updated"}
    ).status_code == (200 if allowed else 403)
    assert target[0].get(f"/api/workspaces/{identifier}/audit").status_code == (
        200 if allowed else 403
    )


def test_admin_cannot_promote_remove_admin_or_transfer_ownership(clients):
    owner = clients("owner")[0]
    admin, member = clients("admin"), clients("member")
    identifier = workspace(owner)
    join(owner, admin, identifier, "admin")
    join(owner, member, identifier)
    assert (
        admin[0]
        .patch(
            f"/api/workspaces/{identifier}/members/{member[1]['id']}",
            json={"role": "admin"},
        )
        .status_code
        == 403
    )
    assert (
        admin[0]
        .delete(f"/api/workspaces/{identifier}/members/{admin[1]['id']}")
        .status_code
        == 204
    )
    # A removed manager is no longer authorized, even with an existing session.
    assert admin[0].get(f"/api/workspaces/{identifier}").status_code == 404


def test_owner_cannot_be_removed_or_demoted(clients):
    client, user, _ = clients("owner")
    identifier = workspace(client)
    assert (
        client.delete(f"/api/workspaces/{identifier}/members/{user['id']}").status_code
        == 409
    )
    assert (
        client.patch(
            f"/api/workspaces/{identifier}/members/{user['id']}",
            json={"role": "viewer"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/workspaces/{identifier}/ownership", json={"user_id": str(uuid4())}
        ).status_code
        == 409
    )


def test_invitation_is_targeted_expiring_revocable_and_idempotent(clients, database):
    owner, target, outsider = (
        clients("owner")[0],
        clients("target"),
        clients("outsider")[0],
    )
    identifier = workspace(owner)
    body = {"username": "target", "role": "viewer"}
    first = owner.post(f"/api/workspaces/{identifier}/invitations", json=body).json()[
        "id"
    ]
    assert (
        owner.post(f"/api/workspaces/{identifier}/invitations", json=body).json()["id"]
        == first
    )
    assert outsider.post(f"/api/invitations/{first}/accept").status_code == 404
    assert target[0].post(f"/api/invitations/{first}/accept").status_code == 200
    assert target[0].post(f"/api/invitations/{first}/accept").status_code == 200
    events = owner.get(f"/api/workspaces/{identifier}/audit").json()["items"]
    assert sum(event["action"] == "invitation.accepted" for event in events) == 1
    with Session(database) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Membership)
                .where(Membership.workspace_id == UUID(identifier))
            )
            == 2
        )


@pytest.mark.parametrize(
    "invalidate", ["expire", "revoke", "disable_inviter", "remove_inviter"]
)
def test_invalidated_invitation_cannot_grant_access(clients, database, invalidate):
    owner, admin, target = clients("owner")[0], clients("admin"), clients("target")
    identifier = workspace(owner)
    join(owner, admin, identifier, "admin")
    invite = (
        admin[0]
        .post(f"/api/workspaces/{identifier}/invitations", json={"username": "target"})
        .json()["id"]
    )
    if invalidate == "revoke":
        assert (
            owner.delete(
                f"/api/workspaces/{identifier}/invitations/{invite}"
            ).status_code
            == 204
        )
    elif invalidate == "remove_inviter":
        assert (
            owner.delete(
                f"/api/workspaces/{identifier}/members/{admin[1]['id']}"
            ).status_code
            == 204
        )
    else:
        with database.begin() as connection:
            if invalidate == "expire":
                connection.execute(
                    update(Invitation)
                    .where(Invitation.id == UUID(invite))
                    .values(expires_at=func.now() - timedelta(seconds=1))
                )
            else:
                connection.execute(
                    update(User)
                    .where(User.id == UUID(admin[1]["id"]))
                    .values(enabled=False)
                )
    assert target[0].post(f"/api/invitations/{invite}/accept").status_code == 410
    assert target[0].get(f"/api/workspaces/{identifier}").status_code == 404


def test_ownership_transfer_is_atomic_and_reduces_previous_owner(clients):
    owner, viewer = clients("owner"), clients("viewer")
    identifier = workspace(owner[0])
    join(owner[0], viewer, identifier, "viewer")
    result = owner[0].post(
        f"/api/workspaces/{identifier}/ownership", json={"user_id": viewer[1]["id"]}
    )
    assert result.status_code == 200
    assert result.json()["role"] == "admin"
    assert viewer[0].get(f"/api/workspaces/{identifier}").json()["role"] == "owner"
    assert (
        owner[0]
        .post(
            f"/api/workspaces/{identifier}/ownership", json={"user_id": owner[1]["id"]}
        )
        .status_code
        == 403
    )
    assert (
        owner[0]
        .delete(f"/api/workspaces/{identifier}/members/{viewer[1]['id']}")
        .status_code
        == 409
    )


def test_keyset_pagination_is_scoped_and_has_no_repeats(clients):
    owner, outsider = clients("owner")[0], clients("outsider")[0]
    for i in range(3):
        workspace(owner, f"team-{i}")
    page = owner.get("/api/workspaces?limit=2").json()
    rest = owner.get(
        "/api/workspaces", params={"limit": 2, "cursor": page["next_cursor"]}
    ).json()
    assert len(page["items"]) == 2 and len(rest["items"]) == 1
    assert len({item["id"] for item in page["items"] + rest["items"]}) == 3
    assert (
        outsider.get("/api/workspaces", params={"cursor": page["next_cursor"]}).json()[
            "items"
        ]
        == []
    )
    assert owner.get("/api/workspaces?cursor=not-valid!").status_code == 422
    assert owner.get("/api/workspaces?limit=101").status_code == 422


def test_database_rejects_active_workspace_without_owner_membership(database):
    with Session(database) as session:
        user = User(
            username="owner", password_hash="disabled-test-placeholder", enabled=False
        )
        session.add(user)
        session.flush()
        session.add(
            Workspace(slug="orphaned-team", name="Orphaned", owner_user_id=user.id)
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_runtime_role_cannot_change_schema_or_audit_history(database):
    grant_runtime_access(database, os.environ["RELAY_RUNTIME_PASSWORD_FILE"])
    from pathlib import Path

    runtime = migration_engine(
        database.url.set(
            username="relay_app",
            password=Path(os.environ["RELAY_RUNTIME_PASSWORD_FILE"])
            .read_text()
            .rstrip("\r\n"),
        )
    )
    try:
        with runtime.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM workspaces")) == 0
        for statement in (
            "CREATE TABLE forbidden (id integer)",
            "DELETE FROM audit_events",
            "UPDATE alembic_version SET version_num = 'tampered'",
        ):
            with pytest.raises(ProgrammingError):
                with runtime.begin() as connection:
                    connection.execute(text(statement))
    finally:
        runtime.dispose()


def test_concurrent_acceptance_creates_one_membership_and_audit_event(
    clients, database
):
    owner, target = clients("owner")[0], clients("target")
    identifier = workspace(owner)
    invite = owner.post(
        f"/api/workspaces/{identifier}/invitations", json={"username": "target"}
    ).json()["id"]
    barrier = Barrier(2)

    def accept_once():
        with Session(database) as session, session.begin():
            actor = session.get(User, UUID(target[1]["id"]))
            barrier.wait(timeout=10)
            return access.accept_invitation(session, actor, UUID(invite)).role

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: accept_once(), range(2)))
    assert results == ["member", "member"]
    with Session(database) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "invitation.accepted")
            )
            == 1
        )


def test_concurrent_ownership_transfers_have_only_one_winner(clients, database):
    owner, first, second = clients("owner"), clients("first"), clients("second")
    identifier = workspace(owner[0])
    join(owner[0], first, identifier)
    join(owner[0], second, identifier)
    barrier = Barrier(2)

    def transfer_to(target):
        try:
            with Session(database) as session, session.begin():
                actor = session.get(User, UUID(owner[1]["id"]))
                barrier.wait(timeout=10)
                access.transfer_owner(
                    session, actor, UUID(identifier), UUID(target[1]["id"])
                )
                return 200
        except HTTPException as error:
            return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(transfer_to, [first, second]))
    assert sorted(outcomes) == [200, 403]
    with Session(database) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "workspace.ownership_transferred")
            )
            == 1
        )


def test_role_is_rechecked_after_a_waiting_workspace_lock(clients, database):
    owner, admin = clients("owner"), clients("admin")
    identifier = UUID(workspace(owner[0]))
    join(owner[0], admin, str(identifier), "admin")
    worker_pid = Queue()

    def waiting_write():
        try:
            with Session(database) as session, session.begin():
                actor = session.get(User, UUID(admin[1]["id"]))
                worker_pid.put(session.scalar(select(func.pg_backend_pid())))
                access.rename_workspace(
                    session,
                    actor,
                    identifier,
                    WorkspaceRename(name="Unauthorized change"),
                )
            return 200
        except HTTPException as error:
            return error.status_code

    with Session(database) as controlling:
        controlling.begin()
        controlling.scalar(
            select(Workspace).where(Workspace.id == identifier).with_for_update()
        )
        membership = controlling.get(Membership, (identifier, UUID(admin[1]["id"])))
        membership.role = "viewer"
        controlling.flush()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(waiting_write)
            try:
                pid = worker_pid.get(timeout=10)
                blocked = False
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    with database.connect().execution_options(
                        isolation_level="AUTOCOMMIT"
                    ) as connection:
                        blocked = connection.scalar(
                            text(
                                "SELECT wait_event_type = 'Lock' "
                                "FROM pg_stat_activity WHERE pid = :pid"
                            ),
                            {"pid": pid},
                        )
                    if blocked:
                        break
                    time.sleep(0.02)
                controlling.commit()
                outcome = future.result(timeout=10)
            finally:
                controlling.rollback()
        assert blocked
        assert outcome == 403
    assert owner[0].get(f"/api/workspaces/{identifier}").json()["name"] == "Demo team"
