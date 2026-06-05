import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from app.config import settings
from app.store.db import Base

async def init_db():
    engine = create_async_engine(settings.db.url)
    async with engine.begin() as conn:
        print("Creating all tables...")
        await conn.run_sync(Base.metadata.create_all)
        print("Done.")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(init_db())
