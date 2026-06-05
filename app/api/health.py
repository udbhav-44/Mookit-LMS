from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from ..config import settings

router = APIRouter()

@router.get("/live")
async def health_live():
    return {"status": "live"}

@router.get("/ready")
async def health_ready(request: Request):
    # Check DB
    try:
        async with request.app.state.db_engine.connect() as conn:
            from sqlalchemy import text
            await conn.execute(text("SELECT 1"))
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "unready", "reason": f"Database: {str(e)}"})
        
    # Check Redis
    try:
        await request.app.state.redis.ping()
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "unready", "reason": f"Redis: {str(e)}"})
        
    return {"status": "ready"}

@router.get("/startup")
async def health_startup():
    return {"status": "started"}
