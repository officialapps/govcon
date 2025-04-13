# db.py
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")
ASYNC_DB_URL = DB_URL.replace("postgresql://", "postgresql+asyncpg://")

engine = create_async_engine(ASYNC_DB_URL, echo=True)

SessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

