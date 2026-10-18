# Smart Freight

## Run

**API** (terminal 1):

```bash
cd api
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

**Web** (terminal 2):

```bash
cd web
npm install
npm run dev
```

## View

Open http://localhost:5173

Login: `dispatcher@transontario.ca` / `changeme`
