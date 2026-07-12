import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/codeknow_db"

engine = create_async_engine(DATABASE_URL)


async def check_db():
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT version();"))
        print(result.scalar())


asyncio.run(check_db())