import os
from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from sqlalchemy import (
    Column, Integer, String, DateTime, 
    Boolean, Numeric, ForeignKey, Index,
    create_engine, select, func, text
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import (
    declarative_base, 
    sessionmaker, 
    relationship,
    selectinload
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import expression
from dotenv import load_dotenv

load_dotenv()

# Database URL from environment
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")

# Convert sync URL to async
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# Create async engine
engine = create_async_engine(DATABASE_URL, echo=False, pool_size=20, max_overflow=10)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()

class Group(Base):
    """Telegram groups using the bot"""
    __tablename__ = "groups"
    
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, unique=True, nullable=False)
    title = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    configs = relationship("GroupConfig", back_populates="group", cascade="all, delete-orphan")
    
    Index("idx_groups_chat_id", chat_id)

class GroupConfig(Base):
    """Token configuration for each group"""
    __tablename__ = "group_configs"
    
    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    token_address = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    emoji = Column(String, default="🌙")
    min_buy = Column(Numeric(20, 8), default=1.0)
    buy_step = Column(Numeric(20, 8), default=5.0)
    telegram_link = Column(String, nullable=True)
    website_link = Column(String, nullable=True)
    twitter_link = Column(String, nullable=True)
    custom_media = Column(JSONB, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    group = relationship("Group", back_populates="configs")
    
    Index("idx_group_configs_token", token_address)
    Index("idx_group_configs_group_token", group_id, token_address, unique=True)

class Token(Base):
    """Token information and statistics"""
    __tablename__ = "tokens"
    
    address = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    decimals = Column(Integer, nullable=False)
    total_supply = Column(Numeric(36, 18), nullable=False)
    price = Column(Numeric(36, 18), default=0)
    mcap = Column(Numeric(36, 18), default=0)
    liquidity = Column(Numeric(36, 18), default=0)
    volume_24h = Column(Numeric(36, 18), default=0)
    volume_30m = Column(Numeric(36, 18), default=0)
    price_change_24h = Column(Numeric(10, 2), default=0)
    price_change_30m = Column(Numeric(10, 2), default=0)
    last_updated = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    boosts = relationship("Boost", back_populates="token", cascade="all, delete-orphan")
    
    Index("idx_tokens_symbol", symbol)
    Index("idx_tokens_volume", volume_30m.desc())

class Boost(Base):
    """Token boost records"""
    __tablename__ = "boosts"
    
    id = Column(Integer, primary_key=True)
    token_address = Column(String, ForeignKey("tokens.address", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, nullable=False)
    duration_hours = Column(Integer, nullable=False)
    paid_amount = Column(Numeric(20, 8), nullable=False)
    start_time = Column(DateTime, nullable=False)
    is_active = Column(Boolean, 
                      server_default=expression.true(),
                      server_onupdate=expression.text(
                          'CASE WHEN NOW() < start_time + (duration_hours || \' hours\')::interval THEN true ELSE false END'
                      ))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    token = relationship("Token", back_populates="boosts")
    
    Index("idx_boosts_token", token_address)
    Index("idx_boosts_active", is_active)
    Index("idx_boosts_start_time", start_time)

class BuyEvent(Base):
    """Record of token buy events"""
    __tablename__ = "buy_events"
    
    id = Column(Integer, primary_key=True)
    token_address = Column(String, ForeignKey("tokens.address"), nullable=False)
    buyer_address = Column(String, nullable=False)
    amount_sui = Column(Numeric(20, 8), nullable=False)
    amount_usd = Column(Numeric(20, 8), nullable=False)
    token_amount = Column(Numeric(36, 18), nullable=False)
    price = Column(Numeric(36, 18), nullable=False)
    tx_hash = Column(String, nullable=False, unique=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    Index("idx_buy_events_token", token_address)
    Index("idx_buy_events_timestamp", timestamp.desc())
    Index("idx_buy_events_amount", amount_usd.desc())

async def get_session() -> AsyncSession:
    """Get database session"""
    async with AsyncSessionLocal() as session:
        return session

async def init_db():
    """Initialize database"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_active_boosts() -> List[Boost]:
    """Get all active token boosts"""
    async with get_session() as session:
        result = await session.execute(
            select(Boost)
            .where(Boost.is_active == True)
            .options(selectinload(Boost.token))
        )
        return result.scalars().all()

async def get_token_stats(token_address: str) -> Optional[Token]:
    """Get token statistics"""
    async with get_session() as session:
        result = await session.execute(
            select(Token).where(Token.address == token_address)
        )
        return result.scalar_one_or_none()

async def update_token_stats(
    token_address: str,
    price: Decimal,
    mcap: Decimal,
    liquidity: Decimal,
    volume_30m: Decimal,
    price_change_30m: Decimal
):
    """Update token statistics"""
    async with get_session() as session:
        await session.execute(
            text("""
                UPDATE tokens 
                SET price = :price,
                    mcap = :mcap,
                    liquidity = :liquidity,
                    volume_30m = :volume_30m,
                    price_change_30m = :price_change_30m,
                    last_updated = NOW()
                WHERE address = :token_address
            """),
            {
                "token_address": token_address,
                "price": price,
                "mcap": mcap,
                "liquidity": liquidity,
                "volume_30m": volume_30m,
                "price_change_30m": price_change_30m
            }
        )
        await session.commit()

async def get_group_configs(token_address: str) -> List[GroupConfig]:
    """Get all group configurations for a token"""
    async with get_session() as session:
        result = await session.execute(
            select(GroupConfig)
            .where(
                GroupConfig.token_address == token_address,
                GroupConfig.is_active == True
            )
            .options(selectinload(GroupConfig.group))
        )
        return result.scalars().all()

async def record_buy_event(buy_event: BuyEvent):
    """Record a new buy event"""
    async with get_session() as session:
        session.add(buy_event)
        await session.commit()

async def get_trending_tokens(limit: int = 10) -> List[Token]:
    """Get trending tokens by volume"""
    async with get_session() as session:
        result = await session.execute(
            select(Token)
            .order_by(Token.volume_30m.desc())
            .limit(limit)
        )
        return result.scalars().all()
