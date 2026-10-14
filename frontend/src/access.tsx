import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  api,
  ApiError,
  json,
  messageFor,
  pagePath,
  type AuditEvent,
  type AssignableRole,
  type Invitation,
  type Member,
  type Page,
  type User,
  type Workspace,
} from "./api";

export function AccessPanel() {
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState("");
  const [mode, setMode] = useState<"login" | "register">("login");
  const [busy, setBusy] = useState(false);
  const expire = useCallback(() => setUser(null), []);
  useEffect(() => {
    const controller = new AbortController();
    void api<User>("/auth/me", { signal: controller.signal })
      .then(setUser)
      .catch((error) => {
        if (
          !controller.signal.aborted &&
          !(error instanceof ApiError && error.status === 401)
        )
          setError(messageFor(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setChecking(false);
      });
    return () => controller.abort();
  }, []);

  async function authenticate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy(true);
    setError("");
    try {
      const account = await api<User>(
        `/auth/${mode}`,
        json("POST", {
          username: data.get("username"),
          password: data.get("password"),
        }),
      );
      form.reset();
      setUser(account);
    } catch (error) {
      setError(messageFor(error));
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    setBusy(true);
    setError("");
    try {
      await api("/auth/logout", json("POST"));
      setUser(null);
    } catch (error) {
      setError(messageFor(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="access-panel" aria-labelledby="access-title">
      <div className="access-heading">
        <div>
          <span className="eyebrow">WORKSPACE ACCESS</span>
          <h2 id="access-title">Your team, your workspace.</h2>
        </div>
        {user ? (
          <div className="account-bar">
            <span>
              Signed in as <strong>{user.username}</strong>
            </span>
            <button disabled={busy} onClick={() => void logout()}>
              Sign out
            </button>
          </div>
        ) : null}
      </div>
      {error ? (
        <p className="error-message" role="alert">
          {error}
        </p>
      ) : null}
      {checking ? (
        <p>Checking your session…</p>
      ) : user ? (
        <WorkspaceAccess key={user.id} user={user} onExpired={expire} />
      ) : (
        <div className="auth-layout">
          <div>
            <h3>
              {mode === "login" ? "Welcome back." : "Start a new account."}
            </h3>
            <p>
              Create a workspace, invite your team, and manage access together.
            </p>
          </div>
          <form
            onSubmit={(event) => void authenticate(event)}
            className="access-form"
          >
            <label>
              Username
              <input
                name="username"
                autoComplete="username"
                required
                minLength={3}
                maxLength={32}
                pattern="[a-zA-Z][a-zA-Z0-9_-]{2,31}"
              />
            </label>
            <label>
              Password
              <input
                name="password"
                type="password"
                autoComplete={
                  mode === "login" ? "current-password" : "new-password"
                }
                required
                minLength={12}
                maxLength={128}
              />
            </label>
            <small>Use 12–128 characters for your password.</small>
            <div className="form-actions">
              <button className="primary" disabled={busy}>
                {busy
                  ? "Please wait…"
                  : mode === "login"
                    ? "Sign in"
                    : "Create account"}
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  setMode(mode === "login" ? "register" : "login");
                  setError("");
                }}
              >
                {mode === "login" ? "New account" : "I have an account"}
              </button>
            </div>
          </form>
        </div>
      )}
    </section>
  );
}

function WorkspaceAccess({
  user,
  onExpired,
}: {
  user: User;
  onExpired: () => void;
}) {
  const [workspaces, setWorkspaces] = useState<Page<Workspace>>({
    items: [],
    next_cursor: null,
  });
  const [invitations, setInvitations] = useState<Page<Invitation>>({
    items: [],
    next_cursor: null,
  });
  const [selected, setSelected] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    void Promise.all([
      api<Page<Workspace>>("/workspaces", { signal: controller.signal }),
      api<Page<Invitation>>("/invitations", { signal: controller.signal }),
    ])
      .then(([ws, invites]) => {
        setWorkspaces(ws);
        setInvitations(invites);
        setSelected((current) =>
          ws.items.some((item) => item.id === current)
            ? current
            : (ws.items[0]?.id ?? null),
        );
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          if (error instanceof ApiError && error.status === 401) onExpired();
          else setError(messageFor(error));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [revision, onExpired]);

  async function perform(task: () => Promise<unknown>, refresh = true) {
    setBusy(true);
    setError("");
    try {
      await task();
      if (refresh) setRevision((value) => value + 1);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) onExpired();
      else setError(messageFor(error));
    } finally {
      setBusy(false);
    }
  }
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    await perform(async () => {
      const workspace = await api<Workspace>(
        "/workspaces",
        json("POST", { name: data.get("name"), slug: data.get("slug") }),
      );
      form.reset();
      setSelected(workspace.id);
    });
  }
  const current = workspaces.items.find(
    (workspace) => workspace.id === selected,
  );
  return (
    <div>
      {error ? (
        <p className="error-message" role="alert">
          {error}
        </p>
      ) : null}
      <div className="workspace-grid">
        <div>
          <h3>Workspaces</h3>
          {loading ? (
            <p>Refreshing workspaces…</p>
          ) : workspaces.items.length === 0 ? (
            <p>No workspaces yet. Create your first one below.</p>
          ) : null}
          <div className="workspace-cards">
            {workspaces.items.map((workspace) => (
              <button
                key={workspace.id}
                className={
                  selected === workspace.id
                    ? "workspace-card selected"
                    : "workspace-card"
                }
                onClick={() => setSelected(workspace.id)}
                aria-pressed={selected === workspace.id}
              >
                <strong>{workspace.name}</strong>
                <span>
                  {workspace.slug} · {workspace.role}
                </span>
              </button>
            ))}
          </div>
          {workspaces.next_cursor ? (
            <button
              disabled={busy}
              onClick={() =>
                void perform(async () => {
                  const page = await api<Page<Workspace>>(
                    pagePath("/workspaces", workspaces.next_cursor),
                  );
                  setWorkspaces((current) => ({
                    items: [...current.items, ...page.items],
                    next_cursor: page.next_cursor,
                  }));
                }, false)
              }
            >
              More workspaces
            </button>
          ) : null}
          <form
            className="access-form compact"
            onSubmit={(event) => void create(event)}
          >
            <h4>Create workspace</h4>
            <label>
              Workspace name
              <input name="name" required maxLength={120} />
            </label>
            <label>
              Workspace slug
              <input
                name="slug"
                required
                minLength={3}
                maxLength={63}
                pattern="[a-z][a-z0-9]*(-[a-z0-9]+)*"
                placeholder="my-team"
              />
            </label>
            <button className="primary" disabled={busy || loading}>
              Create workspace
            </button>
          </form>
        </div>
        <div>
          <h3>Invitations for you</h3>
          {!loading && invitations.items.length === 0 ? (
            <p>No pending invitations.</p>
          ) : null}
          {invitations.items.map((invitation) => (
            <div className="invitation-card" key={invitation.id}>
              <strong>{invitation.workspace_name}</strong>
              <span>
                {invitation.role} · expires{" "}
                {new Date(invitation.expires_at).toLocaleDateString()}
              </span>
              <button
                disabled={busy}
                onClick={() =>
                  void perform(async () => {
                    const workspace = await api<Workspace>(
                      `/invitations/${invitation.id}/accept`,
                      json("POST"),
                    );
                    setSelected(workspace.id);
                  })
                }
              >
                Accept invitation to {invitation.workspace_name}
              </button>
            </div>
          ))}
          {invitations.next_cursor ? (
            <button
              disabled={busy}
              onClick={() =>
                void perform(async () => {
                  const page = await api<Page<Invitation>>(
                    pagePath("/invitations", invitations.next_cursor),
                  );
                  setInvitations((current) => ({
                    items: [...current.items, ...page.items],
                    next_cursor: page.next_cursor,
                  }));
                }, false)
              }
            >
              More invitations
            </button>
          ) : null}
          <button
            disabled={busy || loading}
            onClick={() => setRevision((value) => value + 1)}
          >
            Refresh workspace access
          </button>
        </div>
      </div>
      {current && !loading ? (
        <WorkspaceDetails
          key={current.id}
          workspace={current}
          user={user}
          revision={revision}
          onChanged={() => setRevision((value) => value + 1)}
          onExpired={onExpired}
        />
      ) : null}
    </div>
  );
}

function ConfirmButton({
  children,
  onConfirm,
  disabled,
}: {
  children: ReactNode;
  onConfirm: () => void;
  disabled: boolean;
}) {
  const [confirming, setConfirming] = useState(false);
  return confirming ? (
    <span className="confirm-action">
      <button
        disabled={disabled}
        onClick={() => {
          setConfirming(false);
          onConfirm();
        }}
      >
        Confirm {children}
      </button>
      <button disabled={disabled} onClick={() => setConfirming(false)}>
        Cancel
      </button>
    </span>
  ) : (
    <button disabled={disabled} onClick={() => setConfirming(true)}>
      {children}
    </button>
  );
}

function WorkspaceDetails({
  workspace,
  user,
  revision,
  onChanged,
  onExpired,
}: {
  workspace: Workspace;
  user: User;
  revision: number;
  onChanged: () => void;
  onExpired: () => void;
}) {
  const [members, setMembers] = useState<Page<Member>>({
    items: [],
    next_cursor: null,
  });
  const [invitations, setInvitations] = useState<Page<Invitation>>({
    items: [],
    next_cursor: null,
  });
  const [events, setEvents] = useState<Page<AuditEvent>>({
    items: [],
    next_cursor: null,
  });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const management = workspace.role === "owner" || workspace.role === "admin";
  const path = `/workspaces/${workspace.id}`;
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    const empty = { items: [], next_cursor: null };
    void Promise.all([
      api<Page<Member>>(`${path}/members`, { signal: controller.signal }),
      management
        ? api<Page<Invitation>>(`${path}/invitations`, {
            signal: controller.signal,
          })
        : Promise.resolve(empty),
      management
        ? api<Page<AuditEvent>>(`${path}/audit`, { signal: controller.signal })
        : Promise.resolve(empty),
    ])
      .then(([m, i, a]) => {
        setMembers(m);
        setInvitations(i);
        setEvents(a);
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          if (error instanceof ApiError && error.status === 401) onExpired();
          else setError(messageFor(error));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [path, management, revision, onExpired]);

  async function mutate(task: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await task();
      onChanged();
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) onExpired();
      else setError(messageFor(error));
    } finally {
      setBusy(false);
    }
  }
  async function submitInvite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    await mutate(async () => {
      await api(
        `${path}/invitations`,
        json("POST", {
          username: data.get("username"),
          role: data.get("role"),
        }),
      );
      form.reset();
    });
  }
  const roles: AssignableRole[] =
    workspace.role === "owner"
      ? ["viewer", "member", "admin"]
      : ["viewer", "member"];
  return (
    <section
      className="workspace-details"
      aria-label={`${workspace.name} access`}
    >
      <div className="access-heading">
        <h3>{workspace.name}</h3>
        <span className="role-badge">{workspace.role}</span>
      </div>
      {error ? (
        <p className="error-message" role="alert">
          {error}
        </p>
      ) : null}
      {loading ? (
        <p>Loading workspace details…</p>
      ) : (
        <>
          {management ? (
            <form
              className="inline-form"
              onSubmit={(event) => {
                event.preventDefault();
                const name = new FormData(event.currentTarget).get("name");
                void mutate(() => api(path, json("PATCH", { name })));
              }}
            >
              <label>
                Rename workspace
                <input
                  name="name"
                  defaultValue={workspace.name}
                  required
                  maxLength={120}
                />
              </label>
              <button disabled={busy}>Save name</button>
            </form>
          ) : null}
          <h4>Members</h4>
          <ul className="member-list">
            {members.items.map((member) => (
              <li key={member.id}>
                <span>
                  <strong>{member.username}</strong>
                  <small>{member.role}</small>
                </span>
                <div className="member-actions">
                  {management &&
                  member.role !== "owner" &&
                  (workspace.role === "owner" || member.role !== "admin") ? (
                    <select
                      aria-label={`Role for ${member.username}`}
                      value={member.role}
                      disabled={busy}
                      onChange={(event) =>
                        void mutate(() =>
                          api(
                            `${path}/members/${member.id}`,
                            json("PATCH", { role: event.target.value }),
                          ),
                        )
                      }
                    >
                      {roles.map((role) => (
                        <option key={role}>{role}</option>
                      ))}
                    </select>
                  ) : null}
                  {member.role !== "owner" &&
                  (member.id === user.id ||
                    (management &&
                      (workspace.role === "owner" ||
                        member.role !== "admin"))) ? (
                    <ConfirmButton
                      disabled={busy}
                      onConfirm={() =>
                        void mutate(() =>
                          api(`${path}/members/${member.id}`, json("DELETE")),
                        )
                      }
                    >
                      {member.id === user.id
                        ? "Leave workspace"
                        : `Remove ${member.username}`}
                    </ConfirmButton>
                  ) : null}
                  {workspace.role === "owner" && member.id !== user.id ? (
                    <ConfirmButton
                      disabled={busy}
                      onConfirm={() =>
                        void mutate(() =>
                          api(
                            `${path}/ownership`,
                            json("POST", { user_id: member.id }),
                          ),
                        )
                      }
                    >
                      Transfer ownership to {member.username}
                    </ConfirmButton>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
          {members.next_cursor ? (
            <button
              disabled={busy}
              onClick={() =>
                void api<Page<Member>>(
                  pagePath(`${path}/members`, members.next_cursor),
                )
                  .then((page) =>
                    setMembers((current) => ({
                      items: [...current.items, ...page.items],
                      next_cursor: page.next_cursor,
                    })),
                  )
                  .catch((error) => setError(messageFor(error)))
              }
            >
              More members
            </button>
          ) : null}
          {management ? (
            <>
              <form
                className="inline-form"
                onSubmit={(event) => void submitInvite(event)}
              >
                <label>
                  Invite by username
                  <input
                    name="username"
                    required
                    minLength={3}
                    maxLength={32}
                  />
                </label>
                <label>
                  Invitation role
                  <select name="role" defaultValue="member">
                    {roles.map((role) => (
                      <option key={role}>{role}</option>
                    ))}
                  </select>
                </label>
                <button disabled={busy}>Send invitation</button>
              </form>
              <p className="hint">
                Invitations appear in the recipient’s account. They must
                register first.
              </p>
              <h4>Invitation history</h4>
              <ul className="invitation-list">
                {invitations.items.map((invitation) => (
                  <li key={invitation.id}>
                    <span>
                      {invitation.username} · {invitation.role} ·{" "}
                      {invitation.status}
                    </span>
                    {invitation.status === "pending" &&
                    (workspace.role === "owner" ||
                      invitation.role !== "admin") ? (
                      <ConfirmButton
                        disabled={busy}
                        onConfirm={() =>
                          void mutate(() =>
                            api(
                              `${path}/invitations/${invitation.id}`,
                              json("DELETE"),
                            ),
                          )
                        }
                      >
                        Revoke invitation for {invitation.username}
                      </ConfirmButton>
                    ) : null}
                  </li>
                ))}
              </ul>
              {invitations.next_cursor ? (
                <button
                  disabled={busy}
                  onClick={() =>
                    void api<Page<Invitation>>(
                      pagePath(`${path}/invitations`, invitations.next_cursor),
                    )
                      .then((page) =>
                        setInvitations((current) => ({
                          items: [...current.items, ...page.items],
                          next_cursor: page.next_cursor,
                        })),
                      )
                      .catch((error) => setError(messageFor(error)))
                  }
                >
                  More invitation history
                </button>
              ) : null}
              <h4>Activity</h4>
              <ol className="audit-list">
                {events.items.map((event) => (
                  <li key={event.id}>
                    <span>
                      {event.action.replaceAll(".", " · ").replaceAll("_", " ")}
                    </span>
                    <time dateTime={event.created_at}>
                      {new Date(event.created_at).toLocaleString()}
                    </time>
                  </li>
                ))}
              </ol>
              {events.next_cursor ? (
                <button
                  disabled={busy}
                  onClick={() =>
                    void api<Page<AuditEvent>>(
                      pagePath(`${path}/audit`, events.next_cursor),
                    )
                      .then((page) =>
                        setEvents((current) => ({
                          items: [...current.items, ...page.items],
                          next_cursor: page.next_cursor,
                        })),
                      )
                      .catch((error) => setError(messageFor(error)))
                  }
                >
                  Older activity
                </button>
              ) : null}
            </>
          ) : (
            <p className="hint">
              You can view your team. Workspace managers handle membership and
              invitations.
            </p>
          )}
        </>
      )}
    </section>
  );
}
