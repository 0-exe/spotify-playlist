"""Database setup and models using SQLAlchemy async."""
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Float, DateTime, Text, func, select

from app.config import get_settings

settings = get_settings()

# Ensure data directory exists
os.makedirs("data", exist_ok=True)

engine = create_async_engine(
    settings.database_url.replace("sqlite:///", "sqlite+aiosqlite:///")
    if not settings.database_url.startswith("sqlite+aiosqlite")
    else settings.database_url,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


class ArtistWeight(Base):
    __tablename__ = "artist_weights"

    artist_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    artist_name: Mapped[str] = mapped_column(String(255))
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class AppSetting(Base):
    """Dynamic key-value storage for settings (e.g. Gemini API key, selected model)."""
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


async def init_db():
    """Create all tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    """Dependency: yield a database session."""
    async with AsyncSessionLocal() as session:
        yield session


async def get_app_setting(key: str, default: str = "") -> str:
    """Retrieve a single setting value from the database."""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(AppSetting).where(AppSetting.key == key))
            row = result.scalar_one_or_none()
            return row.value if row and row.value is not None else default
    except Exception:
        # Fallback if DB table is not yet initialized in tests
        try:
            await init_db()
            async with AsyncSessionLocal() as session:
                result = await session.execute(select(AppSetting).where(AppSetting.key == key))
                row = result.scalar_one_or_none()
                return row.value if row and row.value is not None else default
        except Exception:
            return default


async def set_app_setting(key: str, value: str) -> None:
    """Persist a single setting value to the database."""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(AppSetting).where(AppSetting.key == key))
            row = result.scalar_one_or_none()
            if row:
                row.value = value
            else:
                session.add(AppSetting(key=key, value=value))
            await session.commit()
    except Exception:
        await init_db()
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(AppSetting).where(AppSetting.key == key))
            row = result.scalar_one_or_none()
            if row:
                row.value = value
            else:
                session.add(AppSetting(key=key, value=value))
            await session.commit()
