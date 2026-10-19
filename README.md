# lootly

A small self-hosted shopping list app with realtime sync.
Add an item on your phone, see it appear on every other open device.

**Status: work in progress.** I built this to learn fullstack development
and run it on my own server for daily use.

## Features

- Shared shopping list with realtime sync (WebSockets)
- Login with username and password (JWT, argon2 password hashing)
- Invite-only: new accounts can only be created by a logged-in user
- Autocomplete based on previously added items
- Item history

## Stack

| Part     | Tech                                   |
|----------|----------------------------------------|
| Backend  | Python, FastAPI, SQLModel, SQLite      |
| Frontend | Vue 3, single HTML file                |
| Realtime | WebSockets                             |
| Auth     | JWT (python-jose), argon2 (passlib)    |
| Deploy   | Docker Compose behind nginx with HTTPS |

## Run

Create a `.env` file (see `env.example`):

```bash
cp env.example .env
# put a random secret into .env, e.g.:
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Then:

```bash
docker compose up -d --build
```

The backend listens on `127.0.0.1:8000`. In my setup, nginx serves the
frontend and proxies the API, and the first user is created directly
in the database.

## Screenshots

*(coming soon)*
