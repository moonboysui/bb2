import asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, JSON, ForeignKey, Text, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
import os

DATABASE_URL = os.environ.get("DATABASE_URL")

engine = create_async_engine(DATABASE_URL, echo=False, future=True)
async_session = async_sessionmaker(engine, expire_on_commit=False)

Base = declarative_base()

class GroupConfig(Base):
    __tablename__ = 'group_configs'
    id = Column(Integer, primary_key=True)
    group_id = Column(String, unique=True, nullable=False)
    token_address = Column(String, nullable=False)
    token_name = Column(String, nullable=False)
    token_symbol = Column(String, nullable=False)
    emoji = Column(String, nullable=True)
    buy_step = Column(Float, default=1)  # Emoji per $ unit
    min_buy = Column(Float, default=1.0)
    website = Column(String, nullable=True)
    telegram = Column(String, nullable=True)
    x = Column(String, nullable=True)
    chart_url = Column(String, nullable=True)
    swap_url = Column(String, nullable=True)
    custom_media_id = Column(String, nullable=True)  # Telegram File ID or URL
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

class Boost(Base):
    __tablename__ = 'boosts'
    id = Column(Integer, primary_key=True)
    token_address = Column(String, nullable=False)
    start_time = Column(DateTime, server_default=func.now())
    end_time = Column(DateTime, nullable=False)
    paid_amount = Column(Float, nullable=False)
    owner = Column(String, nullable=True)
    group_id = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)

class BuyEvent(Base):
    __tablename__ = 'buy_events'
    id = Column(Integer, primary_key=True)
    token_address = Column(String, nullable=False)
    group_id = Column(String, nullable=True)
    buyer = Column(String, nullable=True)
    amount_usd = Column(Float, nullable=False)
    amount_sui = Column(Float, nullable=False)
    amount_token = Column(Float, nullable=False)
    tx_hash = Column(String, nullable=False)
    timestamp = Column(DateTime, server_default=func.now())

class TokenLeaderboard(Base):
    __tablename__ = 'token_leaderboards'
    id = Column(Integer, primary_key=True)
    token_address = Column(String, nullable=False, unique=True)
    token_symbol = Column(String, nullable=False)
    group_id = Column(String, nullable=True)
    volume_30m = Column(Float, default=0)
    market_cap = Column(Float, default=0)
    price = Column(Float, default=0)
    percent_change_30m = Column(Float, default=0)
    last_updated = Column(DateTime, server_default=func.now(), onupdate=func.now())
    boost_points = Column(Float, default=0)
    telegram = Column(String, nullable=True)
    chart_url = Column(String, nullable=True)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
