from datetime import datetime
from sqlalchemy import Column, Integer, BigInteger, String, Float, DateTime, ForeignKey, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncAttrs
from sqlalchemy.orm import DeclarativeBase
from app.config import DATABASE_URL

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True
)

async_session = async_sessionmaker(engine, expire_on_commit=False)

class Base(AsyncAttrs, DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    telegram_id = Column(BigInteger, primary_key=True)
    full_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_activity = Column(DateTime, default=datetime.utcnow, nullable=True)
    streak_days = Column(Integer, default=1, nullable=True)
    total_tests = Column(Integer, default=0, nullable=True)
    total_correct = Column(Integer, default=0, nullable=True)

class Dictionary(Base):
    __tablename__ = "dictionaries"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), index=True, nullable=False)
    name = Column(String(120), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Word(Base):
    __tablename__ = "words"
    id = Column(Integer, primary_key=True, autoincrement=True)
    dict_id = Column(Integer, ForeignKey("dictionaries.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id = Column(BigInteger, index=True, nullable=False)
    en_word = Column(String(255), nullable=False)
    uz_word = Column(String(255), nullable=False)
    interval = Column(Integer, default=0, nullable=True)
    repetitions = Column(Integer, default=0, nullable=True)
    easiness = Column(Float, default=2.5, nullable=True)
    next_review = Column(DateTime, default=datetime.utcnow, nullable=True)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Avto-migratsiya: yangi ustunlarni tekshirib qo'shish
        try:
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP;"))
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS streak_days INTEGER DEFAULT 1;"))
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS total_tests INTEGER DEFAULT 0;"))
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS total_correct INTEGER DEFAULT 0;"))
            await conn.execute(text("ALTER TABLE words ADD COLUMN IF NOT EXISTS interval INTEGER DEFAULT 0;"))
            await conn.execute(text("ALTER TABLE words ADD COLUMN IF NOT EXISTS repetitions INTEGER DEFAULT 0;"))
            await conn.execute(text("ALTER TABLE words ADD COLUMN IF NOT EXISTS easiness FLOAT DEFAULT 2.5;"))
            await conn.execute(text("ALTER TABLE words ADD COLUMN IF NOT EXISTS next_review TIMESTAMP DEFAULT CURRENT_TIMESTAMP;"))
        except Exception:
            pass