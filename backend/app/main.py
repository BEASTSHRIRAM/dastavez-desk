from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import cases, catalog, files, studio
from app.config import get_settings
from app.repositories.cases import NotFound
from app.seed import bootstrap


@asynccontextmanager
async def lifespan(_: FastAPI):
    bootstrap()  # tables (SQLite dev), template registry and fictional demo data; idempotent
    yield


app = FastAPI(title="Dastavez Desk API", version="0.1.0", lifespan=lifespan,
              description="Voice-first document operations. Speak once. Review everything. Print ready.")
app.add_middleware(CORSMiddleware, allow_origins=list(get_settings().cors_origins), allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])
for r in (catalog.router, cases.router, files.router, studio.router):
    app.include_router(r)


@app.exception_handler(NotFound)
async def not_found(_: Request, exc: NotFound):
    return JSONResponse({"detail": str(exc)}, status_code=404)
