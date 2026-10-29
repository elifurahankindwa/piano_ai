from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.api import exports, notes, projects
from app.core.config import settings

app = FastAPI(title="Piano AI", version="0.2.0")
for r in (projects.router, notes.router, exports.router): app.include_router(r)

@app.get("/api/health")
def health(): return {"ok": True}

app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="ui")
