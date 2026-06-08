"""
app/main.py — FastAPI application factory
==========================================
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import os

from app.core.logger import logger
from app.api.routes import router
from app.api.review_routes import router as review_router
from app.api.fraud_routes import router as fraud_router
from app.api.analytics_routes import router as analytics_router
from app.api.academic_routes import router as academic_router
from app.api.academic_engine_routes import router as academic_engine_router
from app.api.scanner_routes         import router as scanner_router
from app.api.robustness_routes      import router as robustness_router
from app.api.extract import router as extraction_router
from app.workers.bulk_worker import start_worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== DocValidator API starting ===")
    await start_worker()

    yield
    logger.info("=== DocValidator API shutting down ===")


app = FastAPI(
    title="DocValidator — Enterprise KYC Intelligence Platform",
    description="OCR + Validation + Human Review + Fraud Detection + Analytics",
    version="5.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("logs", exist_ok=True)
app.mount("/logs", StaticFiles(directory="logs"), name="logs")

app.include_router(router,            prefix="/api")
app.include_router(review_router,     prefix="/api")
app.include_router(fraud_router,      prefix="/api")
app.include_router(analytics_router,  prefix="/api")
app.include_router(academic_router,        prefix="/api")
app.include_router(academic_engine_router, prefix="/api")
app.include_router(scanner_router,         prefix="/api")
app.include_router(robustness_router,      prefix="/api")
app.include_router(extraction_router,      prefix="/api")

logger.info("DocValidator API v5 — Document Reconstruction Engine initialized.")
