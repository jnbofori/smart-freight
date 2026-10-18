# Smart Freight Web

Vue 3 dispatcher UI for the Trans Ontario freight-planning prototype.

Stack: Vite, Vue Router, Pinia, Element Plus, Tailwind CSS. Talks to the FastAPI app in `../api` with cookie-based auth.

## Setup

Requires Node 20+ (22 recommended).

```bash
cd web
npm install
```

## Run

Start the API first (from `../api`):

```bash
cd ../api
source .venv/bin/activate
uvicorn app.main:app --reload
```

Then the UI:

```bash
cd ../web
npm run dev
```

Open http://localhost:5173 (or http://127.0.0.1:5173).

Dev requests are proxied to the API so auth cookies stay same-origin (avoids `localhost` vs `127.0.0.1` cookie issues).

## Demo login

- Email: `dispatcher@transontario.ca`
- Password: `changeme`

## Configuration

`.env` (dev default — empty base URL uses the Vite proxy):

```
VITE_API_BASE_URL=
```

Optional: `VITE_API_PROXY_TARGET=http://127.0.0.1:8000` (Vite config default).

## Pages

| Route | Purpose |
|-------|---------|
| `/login` | Sign in |
| `/optimize` | Run / persist / reset AI corridor routing + truck+driver co-assignment; visualize LIFO load |
| `/trucks` | Fleet CRUD |
| `/drivers` | Driver CRUD (quals, hours) |
| `/orders` | Order CRUD (including delivery windows) |
