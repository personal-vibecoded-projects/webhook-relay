# Workspace access

This increment connects the dashboard to a persistent, authenticated workspace API.
Registration uses unique case-insensitive usernames and Argon2id password hashes.
Invitations target existing registered users; they appear in the recipient's
account without an email service or bearer link.

## Start the demo

```sh
python3 scripts/init_dev_secrets.py
docker compose up --wait db
docker compose run --build --rm migrate
docker compose up --build --wait
```

Open http://localhost:5173. Create two accounts in separate browser profiles or
an incognito window. Create a workspace in one account, invite the other as a
viewer, and accept from that account. The viewer can see members and leave, but
cannot rename the workspace, manage roles, or view its audit feed. Transfer
ownership from the first account and refresh the second to see its new controls.

The migration creates the restricted `relay_app` database role. The API uses
`.secrets/runtime_password`; migrations use `.secrets/postgres_password`.
The role can operate on application tables but cannot create tables, modify
`alembic_version`, or update/delete audit events. Schema upgrades and runtime
role grants are explicit; application startup never migrates the database.

## Authorization

| Action | Owner | Admin | Member | Viewer |
| --- | --- | --- | --- | --- |
| Read workspace and member list | Yes | Yes | Yes | Yes |
| Rename workspace | Yes | Yes | No | No |
| Invite/manage members and viewers | Yes | Yes | No | No |
| Invite/manage administrators | Yes | No | No | No |
| Read audit and invitation history | Yes | Yes | No | No |
| Transfer ownership | Yes | No | No | No |
| Leave workspace | Transfer first | Yes | Yes | Yes |

Nonmembers receive 404 for workspace resources. Lists are scoped to the current
user or workspace and use bounded keyset pagination. Write requests must have an
Origin matching `RELAY_PUBLIC_ORIGIN`; missing, null, and foreign origins are
rejected. API data responses are marked `Cache-Control: no-store`.

Sessions use a random HttpOnly cookie, SameSite=Lax, with a twelve-hour expiry.
HTTPS uses a `__Host-` cookie with no Domain attribute and root Path. API request
bodies are capped at 16 KiB before parsing, including chunked requests.
Only the SHA-256 digest of its high-entropy token is stored in PostgreSQL. Passwords
use a separate slow Argon2id hash. Login rotates the browser session, logout
revokes it, and disabled users/expired sessions cannot access workspace data.
There are at most five sessions per account. Authentication attempt limits are
stored atomically in PostgreSQL and survive failed login transactions; expensive
hash operations also have a per-process concurrency limit.

Cookies are Secure by default. The Compose development setting permits HTTP
cookies only for a loopback origin. A hosted deployment must configure its HTTPS
origin and leave `RELAY_ALLOW_HTTP_COOKIE` unset. Do not expose the development
Vite server or PostgreSQL outside the local Compose environment.

## Transaction and migration guarantees

Active workspace ownership references an actual member through a deferred
composite foreign key. Workspace creation, membership changes, invitation
resolution, and their audit writes commit together. API database dependencies
finish their transaction before sending the response and its cookie.

Membership/invitation/ownership writes acquire the workspace row lock. Invitation
acceptance rechecks the issuing user's current permissions after taking that
lock. A repeated acceptance creates no duplicate membership or audit event.
Expired, revoked, or no-longer-authorized invitations cannot grant access.
An owner must transfer ownership before leaving or being removed.

Migration `0002_workspace_access` preserves preexisting workspace rows as
`unclaimed`, without inventing an owner. These rows are hidden from the public
workspace API; an administrator must assign a real owner/membership through a
reviewed data migration before activating them. Downgrading drops authentication,
membership, invitation, and audit data; use it only in disposable test databases.

## Check

```sh
docker compose run --build --rm database-tests
```

The PostgreSQL suite covers authentication, cookie flags, revocation, expiry,
origin checks, tenant isolation, the role matrix, invitation lifecycle,
ownership invariants, concurrent acceptance/transfers, runtime SQL privileges,
pagination, and upgrade/downgrade preservation.

For browser verification against the running Compose stack:

```sh
cd frontend
npm ci
npx playwright install chromium
E2E_BASE_URL=http://localhost:5173 RUN_AUTH_E2E=1 npm test
```

The browser test uses generated accounts and exercises registration, workspace
creation, invitation acceptance, viewer restrictions, ownership transfer, logout,
and login. Authentication traces are disabled to keep credentials and cookies
out of saved trace artifacts.
