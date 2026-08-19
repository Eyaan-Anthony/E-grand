# app/main.py
from fastapi import FastAPI
from contextlib import asynccontextmanager
import structlog
from app.routers import stores, products, checkout

# Initialize structured logger
logger = structlog.get_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup actions (e.g., verifying connections, initializing cache)
    logger.info("Starting up e-Santa backend services...")
    yield
    # Shutdown actions
    logger.info("Shutting down e-Santa backend services...")

app = FastAPI(
    title="e-Santa Backend API",
    description="High-performance backend for local grocery e-commerce and proximity inventory management in Douala.",
    version="1.0.0",
    lifespan=lifespan
)

# Include Routers
app.include_router(stores.router)  
app.include_router(products.router)
app.include_router(checkout.router)

@app.get("/health", tags=["System Health"])
async def health_check():
    return {"status": "healthy", "service": "e-santa-backend"}