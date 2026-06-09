"""
FastAPI application entry point.
Registers all routers and configures middleware.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from src.config.settings import settings
from src.api.routers import chat, ingest, sessions, audit, stats


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Investigator AI backend starting up...")
    logger.info(f"LLM model: {settings.groq_model}")
    logger.info(f"Database: {settings.database_url.split('@')[-1]}")
    yield
    logger.info("Investigator AI backend shutting down.")


app = FastAPI(
    title="Investigator AI Assistant",
    description="AI-powered clinical research and pharmacovigilance investigator",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS — allow Streamlit frontend to call backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(chat.router)
app.include_router(ingest.router)
app.include_router(sessions.router)
app.include_router(audit.router)
app.include_router(stats.router)


@app.get("/health")
def health_check():
    """Health check endpoint for deployment monitoring."""
    return {"status": "healthy", "version": "1.0.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.api.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=True,
        log_level=settings.log_level.lower(),
    )