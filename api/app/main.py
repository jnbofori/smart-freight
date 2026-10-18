from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.router import router as auth_router
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.db_migrate import ensure_schema
from app.routers import drivers, optimize, orders, trucks
from app.seed import seed_all


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_schema(engine)
    db = SessionLocal()
    try:
        seed_all(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="Smart Freight API",
    description=(
        "Trans Ontario freight-planning prototype: auth, Elite-aligned "
        "CRUD, AI-assisted corridor routing, and truck+driver co-assignment."
    ),
    version="0.6.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(trucks.router)
app.include_router(orders.router)
app.include_router(drivers.router)
app.include_router(optimize.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
