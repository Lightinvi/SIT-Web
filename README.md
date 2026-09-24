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
