# SIT-Web

Flask Application Factory + Vite React TypeScript.

## Requirements

- Python 3.14.7 (see `.python-version`)
- Node.js 24 LTS and npm
- Docker Compose for containers (optional)

## Local setup

This workspace already has Python 3.14.7 in `.tools/python`, a virtual environment
in `.venv`, and Linux Node.js in `.tools/node`. In WSL, enable the local Node.js
installation from the repository root before running npm:

```bash
export PATH="$PWD/.tools/node/bin:$PATH"
source .venv/bin/activate
```

These local tools are ignored by Git. For a fresh clone, install the requirements
above and follow the setup below.

From the repository root:

```bash
python3.14 -m venv .venv
source .venv/bin/activate
python --version  # Must be 3.14.7
pip install -r backend/requirements.txt
cp .env.example .env
cd frontend
npm ci
```

With uv, use `uv venv --python 3.14.7 .venv` instead to select the exact version.
On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.
Use a separate virtual environment for Windows and WSL.

## Development

Start both servers from the repository root in Linux/WSL:

```bash
./dev_run
```

The script uses `.venv` and prefers `.tools/node` when available. Press `Ctrl+C`
to stop both servers, including reload processes. Ports 5000 and 5173 must be
available; if either server exits, the other is stopped automatically.

To start the servers separately:

Backend (from the repository root):

```bash
source .venv/bin/activate
cd backend
flask --app wsgi run --debug
```

Frontend (another terminal):

```bash
cd frontend
npm run dev
```

Open http://localhost:5173. Vite forwards `/api` to http://localhost:5000.
The homepage fetches members from Flask and shows connection status, member counts,
loading, empty, and error states. Refresh retrieves the latest API data.

- `GET /api/users` returns three demo members from `backend/app/services/users.py` (no database yet).
- `GET /api/auth/session` returns `{"authenticated": false}` (no login implementation yet).

`app/config.py` holds configuration; `app/extensions.py` initializes future Flask
extensions. Register extensions with `init_app` to keep app instances independent.
Place domain logic in `services`, persistence in `models`, and helpers in `utils`.

## Verification

```bash
cd backend
../.venv/bin/python -m unittest discover -s tests -v
cd ../frontend
npm run lint
npm run build
```

## Production

For HTTPS on `sit-web.sytes.net` and automatic certificate renewal, see
[HTTPS setup](docs/https.md). A VM-level Nginx terminates TLS in front of the
existing frontend container; certificates persist independently of releases.

For release-tag builds and SSH deployment to a GCP VM, see
[GitHub Actions deployment](docs/deployment.md). The entry workflow is
`.github/workflows/release.yml`; frontend build, backend build, and deployment
each have their own reusable workflow. Push a `release/*` Git tag to trigger it.

From `backend/`, with the virtual environment activated:

```bash
gunicorn --workers 2 --bind 0.0.0.0:8000 wsgi:app
```

Gunicorn runs on Linux/WSL. Export `SECRET_KEY` in the production environment;
Gunicorn does not automatically load `.env` like the Flask development CLI does.

Alternatively, from the repository root, set a random `SECRET_KEY` in `.env`:

```bash
docker compose up --build -d
```

Open http://localhost:8080. The frontend image builds React and serves it with
Nginx. Nginx forwards `/api/` to the backend service on port 8000 and supports SPA
fallback. The frontend Dockerfile uses the repository root as its build context.

## Discord guild data

Set `DISCORD_BOT_TOKEN` in the root `.env` (loaded by `./dev_run`) or export it
before starting Gunicorn. The token stays on the backend. The bot must belong to
guild `510386488639488001`; enable **Server Members Intent** in the Discord
Developer Portal → Bot → Privileged Gateway Intents for member listing.
See [Discord's guild API documentation](https://docs.discord.com/developers/resources/guild#list-guild-members).

- `GET /api/discord/members`: all guild members, fetched in pages of up to 1,000.
- `GET /api/discord/roles`: guild roles.

Responses contain `members` or `roles` (Discord's objects), `cached` (boolean),
and `fetched_at` / `expires_at` (Unix timestamps in seconds). These read endpoints
are currently public, like `/api/users`; the Bot token is never returned.

Each resource is cached for 86,400 seconds after a successful complete fetch.
The next request after expiry refreshes it; there is no scheduled background fetch.
JSON files in the repository's `storage/cache/` preserve the cache through restarts:
`discord-510386488639488001-members.json` and
`discord-510386488639488001-roles.json`. Each contains the data and expiry timestamp.
Per-resource file locks serialize concurrent refreshes on Linux/WSL; atomic file
replacement prevents partial writes. Invalid JSON is fetched again on the next request.
Docker Compose mounts a named `storage` volume at `/app/storage`, with JSON files
under `/app/storage/cache`. This Docker volume is separate from the local development
`./storage` directory and survives container recreation. `STORAGE_PATH` overrides
the storage root; tests can override the cache directory using `DISCORD_CACHE_PATH`.
The Docker image grants its non-root app user write access to storage.
Separate hosts need a shared cache service. Existing SQLite caches are no longer
read; the first request creates JSON files. Storage is excluded from Git and builds.

Errors return a safe JSON `error` and HTTP 502 (upstream failure) or 503
(missing configuration, rate limit, or unavailable cache). Failed fetches never
return a partial member list. Failures use a short 60-second retry backoff;
Discord HTTP 429 responses use its `retry_after` value and return a `Retry-After`
header. Browsers receive `Cache-Control: no-store`; caching happens server-side.

## Local SQL management

`app.sql` provides a dependency-free SQLite manager for backend Python code.
Use `current_app.extensions["sql"]` inside Flask, or instantiate
`SQLManager(path)` independently. The database is created lazily at
`storage/database/sit.sqlite3` relative to the repository root. Docker uses
`/app/storage/database/sit.sqlite3` in the existing `storage` volume.
`STORAGE_PATH` changes the storage root; Flask's `SQL_DATABASE_PATH` configuration
can override the database filename. Discord's JSON cache remains separate.

```python
from flask import current_app
from app.sql import Column

db = current_app.extensions["sql"]
db.create_table("members", [
    Column("id", "INTEGER", primary_key=True),
    Column("name", nullable=False, unique=True),
    Column("note"),
])
member_id = db.insert("members", {"name": "SIT", "note": None})
rows = db.select("members", {"id": member_id}, columns=["id", "name"],
                 order_by="id", limit=20, offset=0)
db.update("members", {"note": "管理員"}, {"id": member_id})
db.delete("members", {"id": member_id})

print(db.list_tables())
print(db.table_exists("members"))
print(db.table_status("members"))  # existence, count, columns, indexes, FKs, DDL
print(db.database_status())  # quick_check, FK violations, size, journal mode

with db.transaction() as tx:
    tx.insert("members", {"name": "Alice"})
    tx.insert("members", {"name": "Bob"})
    # All operations commit together, or roll back if an exception escapes.

rows = db.query("SELECT * FROM members WHERE name LIKE ?", ("A%",))
result = db.execute("UPDATE members SET note = ? WHERE id = ?", ("更新", 1))
# result contains rowcount and lastrowid; insert() returns lastrowid,
# update()/delete() return affected row counts, select()/query() return dict rows.
```

CRUD filters combine equality conditions with AND; `None` uses `IS NULL`.
Values are parameterized and identifiers restricted to letters, digits and
underscores (not starting with a digit). Empty update/delete filters require
explicit `all_rows=True`. `query`/`execute` accept trusted application SQL only:
use bound parameters for user values, and use `transaction()` rather than manual
BEGIN/COMMIT statements. SQLite exceptions propagate to the caller; all connections
are closed after each operation/transaction. Foreign-key enforcement is enabled on
every connection, with a 10-second lock timeout. Do not share a transaction session
between threads. Health checks and row counts may take time on large databases.
`create_table` does not migrate an existing schema; use explicit trusted DDL for
migrations. No database management HTTP endpoint is exposed.

## Discord account login

In the Discord Developer Portal → your application → OAuth2, copy the Client ID
and Client Secret into the root `.env` as `DISCORD_CLIENT_ID` and
`DISCORD_CLIENT_SECRET`. If `DISCORD_CLIENT_ID` is empty, the backend uses
`DISCORD_BOT_CLIENT_ID` (the same application ID). `DISCORD_BOT_TOKEN` is not an
OAuth Client Secret; obtain the secret from the OAuth2 page.
Register the exact redirect URL, also set as `DISCORD_REDIRECT_URI`:

- Local: `http://localhost:5173/api/auth/discord/callback`
- Production: `https://sit-web.sytes.net/api/auth/discord/callback`

Set `SESSION_COOKIE_SECURE=true` for HTTPS production and `false` for local HTTP.
Restart `./dev_run` after editing environment variables. Docker Compose forwards
these variables to the backend; recreate the backend container after changes.
Use the same hostname throughout login (do not mix localhost and 127.0.0.1).

`GET /api/auth/discord/login` starts the authorization-code flow with `identify`
and `guilds.members.read`. The callback verifies a single-use, 10-minute OAuth
state and checks the user's membership in guild `510386488639488001` directly
with Discord, bypassing the daily JSON cache. Nonmembers and users still pending
membership screening cannot log in. OAuth tokens are used only during verification
and are not persisted or sent to the browser. See
[Discord OAuth2 documentation](https://docs.discord.com/developers/topics/oauth2).

Successful logins create an 8-hour server-side session in the local SQL database;
the signed HttpOnly, SameSite=Lax cookie holds a random session identifier.
`GET /api/auth/session` returns the login status and a logout CSRF token.
`POST /api/auth/logout` requires that token in `X-CSRF-Token` and invalidates the
server-side session. Membership is checked at each login, not continuously during
an existing session. Future protected endpoints must validate the server-side
session before serving protected data; existing public endpoints remain public.

### Member profiles

After successful Discord membership verification, the callback creates the `member`
table if needed and upserts the user's profile in the same transaction as the login
session. The database is `storage/database/sit.sqlite3` (or `SQL_DATABASE_PATH`).

| Column | Meaning |
| --- | --- |
| `user_id` | Discord user ID, TEXT primary key |
| `username` | Discord account username at the latest login |
| `display_name` | Guild nickname, global display name, or username |
| `created_at` | First successful site login, Unix timestamp in seconds |
| `last_login_at` | Latest successful site login, Unix timestamp in seconds |

Repeated logins update the profile without adding duplicates or changing
`created_at`. Rejected logins do not create member records. Logout and session
expiry retain profiles; these records are historical profiles, not proof of current
guild membership. OAuth tokens, email, presence, and roles are not stored here.
Existing signed-in users receive a profile on their next successful OAuth login.

### Profile page

The signed-in header dropdown includes **個人資料** and **登出**.
`react-router-dom` routes `/profile` to the personal profile page without a full
page reload. `GET /api/auth/profile` validates the server-side session and returns
only that user's `member` fields; user IDs in query parameters cannot select other
profiles. Anonymous/expired sessions receive 401, and a missing profile receives
404 with a prompt to sign in again. Logging out returns to the homepage.

Member profiles also store `global_name`, `nickname`, `avatar_url`, and
`guild_joined_at` (Discord's ISO timestamp). Successful login upgrades old member
tables by adding nullable columns, preserving existing profiles and creation times.
Guild avatars take precedence over global avatars, then Discord default avatars.
The header session response reads the avatar from the saved member profile, just
like the profile page. No extra OAuth scopes or email collection are required.
Existing users should sign out and sign in again to populate these new fields.
