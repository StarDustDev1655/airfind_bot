from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, Boolean, DateTime, DECIMAL, JSON, BigInteger
from datetime import datetime

DATABASE_URL = "sqlite+aiosqlite:///./airfind.db"

engine = create_async_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String)
    first_name = Column(String)
    searches_count = Column(Integer, default=0)
    is_premium = Column(Boolean, default=False)
    premium_until = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)

class Search(Base):
    __tablename__ = "searches"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    origin = Column(String)
    destination = Column(String)
    date_from = Column(DateTime)
    date_to = Column(DateTime)
    price = Column(DECIMAL(10,2))
    currency = Column(String, default="USD")
    route = Column(JSON)
    created_at = Column(DateTime, default=datetime.now)

class Track(Base):
    __tablename__ = "tracks"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    origin = Column(String)
    destination = Column(String)
    max_price = Column(DECIMAL(10,2))
    currency = Column(String, default="USD")
    created_at = Column(DateTime, default=datetime.now)
    last_checked = Column(DateTime, default=datetime.now)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
