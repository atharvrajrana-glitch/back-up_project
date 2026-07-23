from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
import model
from database import engine , get_db
from routers import auth , databases , backup




app = FastAPI(
    title="Database Bcakup and PITR Orchestrator",
    description="Secure engine managing full streaming snapshots and incremental log backups.",
    version="1.0.0"
)


app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
model.Base.metadata.create_all(bind=engine)

app.include_router(auth.router)
app.include_router(databases.router)
app.include_router(backup.router)
app.mount("/frontend", StaticFiles(directory="frontend", html=True), name="frontend")

@app.get("/", include_in_schema=False)
def frontend_root():
    return RedirectResponse(url="/frontend/")

@app.get("/healthz")
def health_check():
    """check endpoint to ensure core orchestrator is running.
    """
    return {"status": "healthy", "engine": "FastAPI", "database": "connected"}

