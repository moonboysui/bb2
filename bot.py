import os
import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, Optional, List, Union
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, ChatTypeFilter
from aiogram.types import (
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    CallbackQuery,
    Message,
    ChatMemberUpdated,
    Chat
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from dotenv import load_dotenv
from database import (
    init_db, 
    get_session, 
    Token, 
    Group, 
    Boost, 
    GroupConfig,
    TokenStats
)
from sui_api import SuiAPI, TokenData, BuyData
from config import Config, ConfigState
import json
import re
from decimal import ROUND_DOWN
import traceback
from web3.main import Web3

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TRENDING_CHANNEL = os.environ.get("TRENDING_CHANNEL", "@moonbagstrending")
BOOST_WALLET = "0x7338ef163ee710923803cb0dd60b5b02cddc5fbafef417342e1bbf1fba20e702"
MIN_TRENDING_BUY = 200  # Minimum buy amount in USD for trending channel
PORT = int(os.environ.get("PORT", 8080))
DEFAULT_BUY_STEP = 5
DEFAULT_MIN_BUY = 1
MAX_EMOJIS = 50

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()

# State storage
config_sessions: Dict[int, Config] = {}
boost_sessions: Dict[int, dict] = {}
active_groups: Dict[int, GroupConfig] = {}
token_cache: Dict[str, TokenData] = {}
pending_boosts: Dict[str, dict] = {}

# Boost pricing and durations
BOOST_OPTIONS = {
    "4h": {"duration": 4, "price": 15, "display": "4 Hours - 15 SUI"},
    "8h": {"duration": 8, "price": 20, "display": "8 Hours - 20 SUI"},
    "12h": {"duration": 12, "price": 27, "display": "12 Hours - 27 SUI"},
    "24h": {"duration": 24, "price": 45, "display": "24 Hours - 45 SUI"},
    "48h": {"duration": 48, "price": 80, "display": "48 Hours - 80 SUI"},
    "72h": {"duration": 72, "price": 110, "display": "72 Hours - 110 SUI"},
    "1w": {"duration": 168, "price": 180, "display": "1 Week - 180 SUI"}
}

class BuyBotException(Exception):
    """Custom exception for bot-specific errors"""
    pass

async def validate_token_address(address: str) -> bool:
    """Validate Sui token address format and existence"""
    if not re.match(r'^0x[a-fA-F0-9]{64}$', address):
        return False
    try:
        return await SuiAPI.token_exists(address)
    except Exception as e:
        logger.error(f"Error validating token address: {e}")
        return False

def create_config_keyboard(current_config: Optional[Config] = None) -> InlineKeyboardMarkup:
    """Create configuration keyboard with current status"""
    builder = InlineKeyboardBuilder()
    
    buttons = [
        ("🎯 Token Address", "config_token", "✓" if current_config and current_config.token_address else "❌"),
        ("🌟 Buy Emojis", "config_emoji", "✓" if current_config and current_config.emoji else "❌"),
        ("💰 Min Buy ($)", "config_min_buy", "✓" if current_config and current_config.min_buy else "❌"),
        ("📊 Buy Step ($)", "config_buy_step", "✓" if current_config and current_config.buy_step else "❌"),
        ("💬 Telegram", "config_telegram", "✓" if current_config and current_config.telegram_link else "❌"),
        ("🌐 Website", "config_website", "✓" if current_config and current_config.website_link else "❌"),
        ("🐦 Twitter", "config_twitter", "✓" if current_config and current_config.twitter_link else "❌"),
        ("🖼 Custom Media", "config_media", "✓" if current_config and current_config.custom_media else "❌")
    ]
    
    for text, callback_data, status in buttons:
        builder.button(
            text=f"{text} {status}",
            callback_data=callback_data
        )
    
    builder.button(text="✅ Save Configuration", callback_data="config_save")
    builder.button(text="❌ Cancel", callback_data="config_cancel")
    
    builder.adjust(2, 2, 2, 2, 2)
    return builder.as_markup()

def create_boost_keyboard() -> InlineKeyboardMarkup:
    """Create boost options keyboard"""
    builder = InlineKeyboardBuilder()
    
    for key, data in BOOST_OPTIONS.items():
        builder.button(
            text=data["display"],
            callback_data=f"boost_{key}"
        )
    
    builder.button(text="❌ Cancel Boost", callback_data="boost_cancel")
    builder.adjust(1)
    return builder.as_markup()

async def format_buy_alert(
    buy_data: BuyData,
    token_config: GroupConfig,
    is_trending: bool = False
) -> tuple[str, InlineKeyboardMarkup]:
    """Format buy alert message with custom emojis and data"""
    try:
        # Calculate emoji count based on buy_step
        emoji_count = min(
            int(Decimal(buy_data.amount_usd) / Decimal(token_config.buy_step)),
            MAX_EMOJIS
        )
        emojis = (token_config.emoji + " ") * emoji_count if emoji_count > 0 else ""
        
        # Format wallet address
        wallet = f"{buy_data.buyer_address[:4]}...{buy_data.buyer_address[-4:]}"
        
        # Build message
        message_parts = [
            f"<b>{token_config.symbol} Buy!</b>\n",
            f"\n{emojis}\n" if emojis else "\n",
            f"⬅️ Size ${buy_data.amount_usd:,.2f} | {buy_data.amount_sui:.2f} SUI",
            f"➡️ Got {buy_data.token_amount:,.2f} {token_config.symbol}\n",
            f"👤 <a href='{buy_data.buyer_url}'>{wallet}</a> | <a href='{buy_data.tx_url}'>Txn</a>",
            f"🔼 MCap ${buy_data.mcap:,.2f}",
            f"📊 TVL/Liq ${buy_data.liquidity:,.2f}",
            f"📊 Price ${buy_data.price:.8f}",
            f"💧 SUI Price: ${buy_data.sui_price:.2f}\n"
        ]

        # Add configured links
        links = []
        if token_config.website_link:
            links.append(f"<a href='{token_config.website_link}'>Website</a>")
        if token_config.telegram_link:
            links.append(f"<a href='{token_config.telegram_link}'>Telegram</a>")
        if token_config.twitter_link:
            links.append(f"<a href='{token_config.twitter_link}'>X</a>")
        
        if links:
            message_parts.append(" | ".join(links) + "\n")
        
        # Add standard footer
        message_parts.extend([
            f"\n<a href='{buy_data.chart_url}'>Chart</a> | ",
            f"<a href='https://t.me/suivolumebot'>Vol. Bot</a> | ",
            f"<a href='https://t.me/SuiTrendingBullShark'>Sui Trending</a>\n",
            "———\n",
            "<a href='https://t.me/BullsharkTrendingBot?start=adBuyRequest'>",
            "Ad: Place your advertisement here</a>"
        ])
        
        message = "\n".join(message_parts)
        
        # Create buy button
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="🛍 Buy Now",
                url=buy_data.buy_url
            )
        ]])
        
        return message, keyboard
        
    except Exception as e:
        logger.error(f"Error formatting buy alert: {e}")
        raise BuyBotException("Failed to format buy alert")
       
# Command Handlers
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Handle /start command"""
    user_id = message.from_user.id
    
    if message.chat.type == "private":
        if "config_" in message.text:
            # Configuration flow from group
            group_id = int(message.text.split("_")[1])
            config = Config(group_id=group_id)
            config_sessions[user_id] = config
            
            await message.answer(
                "Welcome to Moon BuyBot configuration! 🌙\n\n"
                "Please configure the following settings for your group:",
                reply_markup=create_config_keyboard()
            )
        else:
            await message.answer(
                "🌙 Welcome to Moon BuyBot!\n\n"
                "Add me to your group and make me admin to start tracking token buys.\n"
                "Use /config in your group to set up tracking.\n"
                "Use /boost to boost your token in @moonbagstrending!"
            )
    else:
        # Check if user is admin
        member = await bot.get_chat_member(message.chat.id, message.from_user.id)
        if member.status in ["creator", "administrator"]:
            await message.answer(
                "Let's configure the buy bot for your group! Click below to start:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text="🔧 Configure Bot",
                        url=f"https://t.me/{(await bot.me()).username}?start=config_{message.chat.id}"
                    )
                ]])
            )
        else:
            await message.answer("⚠️ Only group administrators can configure the bot.")

@dp.message(Command("boost"))
async def cmd_boost(message: types.Message):
    """Handle /boost command"""
    if message.chat.type != "private":
        await message.answer(
            "Please use this command in private chat:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="🚀 Boost Token",
                    url=f"https://t.me/{(await bot.me()).username}?start=boost"
                )
            ]])
        )
        return
    
    boost_sessions[message.from_user.id] = {
        "step": "token",
        "timestamp": datetime.utcnow()
    }
    
    await message.answer(
        "🚀 Token Boost Configuration\n\n"
        "Please enter the contract address of the token you want to boost:\n"
        "Example: 0x7b888393d6a552819bb0a7f878183abaf04550bfb9546b20ea586d338210826f"
    )

@dp.callback_query(F.data.startswith("boost_"))
async def handle_boost_callback(callback: CallbackQuery):
    """Handle boost duration selection"""
    user_id = callback.from_user.id
    
    if user_id not in boost_sessions:
        await callback.answer("Please start the boost process again with /boost")
        return
    
    if callback.data == "boost_cancel":
        del boost_sessions[user_id]
        await callback.message.edit_text("Boost configuration cancelled.")
        return
    
    duration_key = callback.data.split("_")[1]
    boost_data = BOOST_OPTIONS[duration_key]
    session = boost_sessions[user_id]
    
    session.update({
        "duration": boost_data["duration"],
        "price": boost_data["price"],
        "step": "payment"
    })
    
    payment_instructions = (
        f"🚀 Boost Payment\n\n"
        f"Token: {session['token']}\n"
        f"Duration: {boost_data['display']}\n\n"
        f"Please send exactly {boost_data['price']} SUI to:\n"
        f"<code>{BOOST_WALLET}</code>\n\n"
        f"Your token will be boosted for {boost_data['duration']} hours after payment confirmation.\n"
        f"Payment window: 30 minutes"
    )
    
    await callback.message.edit_text(
        payment_instructions,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ Cancel Payment", callback_data="boost_cancel")
        ]])
    )
    
    # Start payment monitoring
    asyncio.create_task(monitor_boost_payment(user_id, session))

async def monitor_boost_payment(user_id: int, session: dict):
    """Monitor for boost payment confirmation"""
    token_address = session["token"]
    expected_amount = session["price"]
    start_time = datetime.utcnow()
    
    try:
        while (datetime.utcnow() - start_time) < timedelta(minutes=30):
            if await SuiAPI.verify_payment(
                BOOST_WALLET,
                expected_amount,
                start_time
            ):
                # Payment confirmed, apply boost
                async with get_session() as db:
                    boost = Boost(
                        token_address=token_address,
                        duration_hours=session["duration"],
                        start_time=datetime.utcnow(),
                        paid_amount=expected_amount,
                        user_id=user_id
                    )
                    db.add(boost)
                    await db.commit()
                
                # Update token cache
                if token_address in token_cache:
                    token_cache[token_address].is_boosted = True
                
                # Notify user
                await bot.send_message(
                    user_id,
                    f"✅ Boost payment confirmed!\n\n"
                    f"Your token will be boosted for {session['duration']} hours.\n"
                    f"All buys will be shown in @moonbagstrending during this period!"
                )
                
                # Notify trending channel
                token_data = await SuiAPI.get_token_data(token_address)
                await bot.send_message(
                    TRENDING_CHANNEL,
                    f"🚀 New Token Boost!\n\n"
                    f"${token_data.symbol} ({token_data.name})\n"
                    f"Duration: {session['duration']} hours\n"
                    f"Contract: <code>{token_address}</code>\n\n"
                    f"All buys will be displayed here during the boost period! 🔥"
                )
                
                del boost_sessions[user_id]
                return
            
            await asyncio.sleep(10)
        
        # Payment timeout
        await bot.send_message(
            user_id,
            "⚠️ Boost payment timeout. Please try again with /boost"
        )
    except Exception as e:
        logger.error(f"Error monitoring boost payment: {e}")
        await bot.send_message(
            user_id,
            "❌ Error processing boost payment. Please contact support."
        )
    finally:
        if user_id in boost_sessions:
            del boost_sessions[user_id]

async def process_buy_event(buy_data: BuyData):
    """Process incoming buy events"""
    try:
        # Get token configuration for all groups tracking this token
        async with get_session() as db:
            groups = await db.execute(
                select(GroupConfig).where(
                    GroupConfig.token_address == buy_data.token_address
                )
            )
            configs = groups.scalars().all()
        
        # Check if token is boosted
        is_boosted = await check_token_boost(buy_data.token_address)
        
        # Process for each configured group
        for config in configs:
            if Decimal(buy_data.amount_usd) >= Decimal(config.min_buy):
                message, keyboard = await format_buy_alert(buy_data, config)
                
                try:
                    await bot.send_message(
                        config.group_id,
                        message,
                        reply_markup=keyboard
                    )
                except TelegramAPIError as e:
                    logger.error(f"Failed to send alert to group {config.group_id}: {e}")
        
        # Send to trending channel if meets criteria
        if (
            Decimal(buy_data.amount_usd) >= MIN_TRENDING_BUY
            or is_boosted
        ):
            trending_message, trending_keyboard = await format_buy_alert(
                buy_data,
                configs[0],  # Use first config for formatting
                is_trending=True
            )
            
            await bot.send_message(
                TRENDING_CHANNEL,
                trending_message,
                reply_markup=trending_keyboard
            )
    
    except Exception as e:
        logger.error(f"Error processing buy event: {e}")

async def update_leaderboard():
    """Update trending leaderboard every 30 minutes"""
    while True:
        try:
            # Get top tokens by volume including boost effects
            top_tokens = await SuiAPI.get_trending_tokens()
            
            message = (
                "🏆 Sui Trending Tokens\n"
                "Last 30 Minutes\n\n"
            )
            
            for i, token in enumerate(top_tokens[:10], 1):
                price_change = token.price_change_30m
                change_symbol = "🟢" if price_change >= 0 else "🔴"
                
                message += (
                    f"{i}. <a href='{token.telegram_link}'>${token.symbol}</a>\n"
                    f"💰 MCap: ${token.mcap:,.0f}\n"
                    f"📊 {change_symbol} {abs(price_change):.2f}%\n\n"
                )
            
            # Send and pin in trending channel
            sent = await bot.send_message(TRENDING_CHANNEL, message)
            
            try:
                # Unpin previous message if exists
                await bot.unpin_all_chat_messages(TRENDING_CHANNEL)
                # Pin new message
                await bot.pin_chat_message(TRENDING_CHANNEL, sent.message_id)
            except TelegramAPIError as e:
                logger.error(f"Error managing pins: {e}")
            
        except Exception as e:
            logger.error(f"Error updating leaderboard: {e}")
        
        await asyncio.sleep(1800)  # 30 minutes

async def check_token_boost(token_address: str) -> bool:
    """Check if token is currently boosted"""
    async with get_session() as db:
        boost = await db.execute(
            select(Boost)
            .where(
                Boost.token_address == token_address,
                Boost.start_time + timedelta(hours=Boost.duration_hours) > datetime.utcnow()
            )
            .order_by(Boost.start_time.desc())
        )
        return bool(boost.scalar())

async def startup():
    """Startup tasks"""
    # Initialize database
    await init_db()
    
    # Start background tasks
    asyncio.create_task(update_leaderboard())
    asyncio.create_task(SuiAPI.start_buy_monitoring(process_buy_event))
    
    # Setup webhook for Render
    if os.environ.get("WEBHOOK_URL"):
        await bot.set_webhook(
            url=f"{os.environ['WEBHOOK_URL']}/{BOT_TOKEN}",
            drop_pending_updates=True
        )
        logger.info("Webhook set up successfully")

async def shutdown():
    """Shutdown tasks"""
    await bot.delete_webhook()
    await bot.session.close()

def setup_web_app():
    """Setup web app for Render"""
    from aiohttp import web
    
    app = web.Application()
    
    async def handle_webhook(request):
        if request.match_info.get("token") == BOT_TOKEN:
            update = types.Update(**await request.json())
            await dp.feed_update(bot, update)
            return web.Response()
        return web.Response(status=403)
    
    async def handle_health_check(request):
        return web.Response(text="Moon BuyBot is running!")
    
    app.router.add_post(f"/{BOT_TOKEN}", handle_webhook)
    app.router.add_get("/", handle_health_check)
    
    return app

if __name__ == "__main__":
    from aiohttp import web
    
    # Setup web app
    app = setup_web_app()
    
    # Register startup/shutdown
    dp.startup.register(startup)
    dp.shutdown.register(shutdown)
    
    # Start both bot and web server
    web.run_app(
        app,
        host="0.0.0.0",
        port=PORT,
        access_log=logger
    )
