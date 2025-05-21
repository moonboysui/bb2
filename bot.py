import asyncio
import os
import logging
import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import FSInputFile
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.markdown import hbold
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from database import async_session, init_db, GroupConfig, Boost, TokenLeaderboard, BuyEvent
from utils import (
    is_admin, format_alert, format_leaderboard, get_swap_link,
    buy_emoji_line, short_addr
)
import sui_api

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
BOOST_WALLET_ADDRESS = os.environ.get("BOOST_WALLET_ADDRESS")
TRENDING_CHANNEL = os.environ.get("TRENDING_CHANNEL", "@moonbagstrending")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(storage=MemoryStorage())

# --- CONFIGURATION FSM ---

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

class ConfigStates(StatesGroup):
    waiting_token_address = State()
    waiting_token_name = State()
    waiting_token_symbol = State()
    waiting_emoji = State()
    waiting_buy_step = State()
    waiting_min_buy = State()
    waiting_website = State()
    waiting_telegram = State()
    waiting_x = State()
    waiting_chart_url = State()
    waiting_media = State()
    confirm = State()

# --- GROUP CONFIG COMMAND ---

@dp.message(CommandStart())
async def start_handler(message: types.Message, state: FSMContext):
    if message.chat.type in ("group", "supergroup"):
        # Only admins can configure
        user = await bot.get_chat_member(message.chat.id, message.from_user.id)
        if not is_admin(user):
            await message.reply("Only group admins can configure the buybot.")
            return
        await message.reply("Please continue setup in private chat. "
                            "Message me here: https://t.me/{}".format(bot.me.username))
        return
    await message.answer("Welcome to the Sui Buybot!\nType /config to start setup for your group.")

@dp.message(Command("config"))
async def config_start(message: types.Message, state: FSMContext):
    await message.answer("Let's start configuration. Please enter the token contract address you want to track:")
    await state.set_state(ConfigStates.waiting_token_address)

@dp.message(ConfigStates.waiting_token_address)
async def config_token_address(message: types.Message, state: FSMContext):
    await state.update_data(token_address=message.text.strip())
    await message.answer("Token name (e.g., Mooncoin):")
    await state.set_state(ConfigStates.waiting_token_name)

@dp.message(ConfigStates.waiting_token_name)
async def config_token_name(message: types.Message, state: FSMContext):
    await state.update_data(token_name=message.text.strip())
    await message.answer("Token symbol (e.g., MOON):")
    await state.set_state(ConfigStates.waiting_token_symbol)

@dp.message(ConfigStates.waiting_token_symbol)
async def config_token_symbol(message: types.Message, state: FSMContext):
    await state.update_data(token_symbol=message.text.strip())
    await message.answer("Emoji for buys (e.g., 🌕):")
    await state.set_state(ConfigStates.waiting_emoji)

@dp.message(ConfigStates.waiting_emoji)
async def config_token_emoji(message: types.Message, state: FSMContext):
    await state.update_data(emoji=message.text.strip())
    await message.answer("Buy step (how many $ per emoji, e.g., 1 means 1 emoji per $1, 5 means 1 emoji per $5):")
    await state.set_state(ConfigStates.waiting_buy_step)

@dp.message(ConfigStates.waiting_buy_step)
async def config_buy_step(message: types.Message, state: FSMContext):
    try:
        buy_step = float(message.text.strip())
        await state.update_data(buy_step=buy_step)
    except Exception:
        await message.answer("Please enter a valid number (e.g., 1 or 5)")
        return
    await message.answer("Minimum buy in USD to alert (e.g., 10):")
    await state.set_state(ConfigStates.waiting_min_buy)

@dp.message(ConfigStates.waiting_min_buy)
async def config_min_buy(message: types.Message, state: FSMContext):
    try:
        min_buy = float(message.text.strip())
        await state.update_data(min_buy=min_buy)
    except Exception:
        await message.answer("Please enter a valid number (e.g., 10)")
        return
    await message.answer("Website link (or skip):")
    await state.set_state(ConfigStates.waiting_website)

@dp.message(ConfigStates.waiting_website)
async def config_website(message: types.Message, state: FSMContext):
    await state.update_data(website=message.text.strip())
    await message.answer("Telegram link (or skip):")
    await state.set_state(ConfigStates.waiting_telegram)

@dp.message(ConfigStates.waiting_telegram)
async def config_telegram(message: types.Message, state: FSMContext):
    await state.update_data(telegram=message.text.strip())
    await message.answer("X (Twitter) link (or skip):")
    await state.set_state(ConfigStates.waiting_x)

@dp.message(ConfigStates.waiting_x)
async def config_x(message: types.Message, state: FSMContext):
    await state.update_data(x=message.text.strip())
    await message.answer("Chart link (or skip):")
    await state.set_state(ConfigStates.waiting_chart_url)

@dp.message(ConfigStates.waiting_chart_url)
async def config_chart_url(message: types.Message, state: FSMContext):
    await state.update_data(chart_url=message.text.strip())
    await message.answer("You can now upload a token logo/image, or type 'skip':")
    await state.set_state(ConfigStates.waiting_media)

@dp.message(ConfigStates.waiting_media)
async def config_media(message: types.Message, state: FSMContext):
    media_id = None
    if message.content_type in ("photo",):
        media_id = message.photo[-1].file_id
    elif message.text and message.text.strip().lower() == "skip":
        pass
    else:
        await message.answer("Please send a photo or type 'skip'.")
        return
    await state.update_data(custom_media_id=media_id)
    data = await state.get_data()
    summary = (f"Config summary:\n"
               f"Token address: {data['token_address']}\n"
               f"Name: {data['token_name']}\n"
               f"Symbol: {data['token_symbol']}\n"
               f"Emoji: {data['emoji']}\n"
               f"Buy step: {data['buy_step']}\n"
               f"Min buy: {data['min_buy']}\n"
               f"Website: {data['website']}\n"
               f"Telegram: {data['telegram']}\n"
               f"X: {data['x']}\n"
               f"Chart: {data['chart_url']}\n"
               f"Media: {'Provided' if media_id else 'Not provided'}\n"
               "Type 'confirm' to save, or 'cancel' to abort.")
    await message.answer(summary)
    await state.set_state(ConfigStates.confirm)

@dp.message(ConfigStates.confirm)
async def config_confirm(message: types.Message, state: FSMContext):
    if message.text.strip().lower() == "confirm":
        user_id = message.from_user.id
        async with async_session() as session:
            data = await state.get_data()
            # For this example, group_id is set to user's private chat ID; in practice, you'd map this to their group.
            group_id = str(user_id)
            # Save config
            config = await session.get(GroupConfig, group_id)
            if not config:
                config = GroupConfig(
                    group_id=group_id,
                    token_address=data['token_address'],
                    token_name=data['token_name'],
                    token_symbol=data['token_symbol'],
                    emoji=data['emoji'],
                    buy_step=data['buy_step'],
                    min_buy=data['min_buy'],
                    website=data['website'],
                    telegram=data['telegram'],
                    x=data['x'],
                    chart_url=data['chart_url'],
                    custom_media_id=data['custom_media_id'],
                )
                session.add(config)
            else:
                for k, v in data.items():
                    setattr(config, k, v)
            await session.commit()
        await message.answer("Configuration saved! Buys will now be tracked for your group.")
        await state.clear()
    else:
        await message.answer("Cancelled.")
        await state.clear()

# --- BUY EVENT HANDLER ---

async def handle_buy_event(buy_event):
    # For each group config, check if buy_event.token matches and send alerts
    async with async_session() as session:
        q = await session.execute(select(GroupConfig))
        configs = q.scalars()
        for config in configs:
            if buy_event["token"] == config.token_address:
                # Only send if meets min_buy threshold, unless boosted
                boosted = await is_boosted(session, config.token_address)
                if buy_event["usd_amount"] >= config.min_buy or boosted:
                    await send_buy_alert(buy_event, config, boosted)
                    # Record event for leaderboard
                    await save_buy_event(session, buy_event, config.group_id)
                    await update_leaderboard(session, buy_event, config)

async def is_boosted(session: AsyncSession, token_address: str) -> bool:
    now = datetime.datetime.utcnow()
    q = await session.execute(
        select(Boost).where(
            Boost.token_address == token_address,
            Boost.is_active == True,
            Boost.start_time <= now,
            Boost.end_time >= now
        )
    )
    return q.scalar_one_or_none() is not None

async def send_buy_alert(buy_event, config, boosted):
    # Compose alert message
    media = config.custom_media_id
    msg = format_alert(buy_event, config, trending_channel=TRENDING_CHANNEL)
    # Inline button: buy link
    buy_btn = types.InlineKeyboardButton(text="Buy", url=get_swap_link(config.token_address))
    kb = types.InlineKeyboardMarkup(inline_keyboard=[[buy_btn]])
    # Send to group (simulate group_id as user_id for now; in prod, store real group chat IDs)
    try:
        if media:
            await bot.send_photo(chat_id=config.group_id, photo=media, caption=msg, reply_markup=kb)
        else:
            await bot.send_message(chat_id=config.group_id, text=msg, reply_markup=kb)
    except Exception as e:
        logging.error(f"Error sending alert to group {config.group_id}: {e}")
    # If boosted or over $200, send in trending channel
    if boosted or buy_event["usd_amount"] >= 200:
        try:
            if media:
                await bot.send_photo(chat_id=TRENDING_CHANNEL, photo=media, caption=msg, reply_markup=kb)
            else:
                await bot.send_message(chat_id=TRENDING_CHANNEL, text=msg, reply_markup=kb)
        except Exception as e:
            logging.error(f"Error sending alert to trending channel: {e}")

async def save_buy_event(session: AsyncSession, buy_event, group_id):
    event = BuyEvent(
        token_address=buy_event["token"],
        group_id=group_id,
        buyer=buy_event["buyer"],
        amount_usd=buy_event["usd_amount"],
        amount_sui=buy_event["sui_amount"],
        amount_token=buy_event["token_amount"],
        tx_hash=buy_event["tx_hash"],
    )
    session.add(event)
    await session.commit()

async def update_leaderboard(session: AsyncSession, buy_event, config):
    # Update or insert leaderboard entry
    q = await session.execute(
        select(TokenLeaderboard).where(TokenLeaderboard.token_address == config.token_address)
    )
    entry = q.scalar_one_or_none()
    now = datetime.datetime.utcnow()
    if not entry:
        entry = TokenLeaderboard(
            token_address=config.token_address,
            token_symbol=config.token_symbol,
            group_id=config.group_id,
            volume_30m=buy_event["usd_amount"],
            market_cap=buy_event["market_cap"],
            price=buy_event["price"],
            percent_change_30m=0,
            last_updated=now,
            boost_points=0,
            telegram=config.telegram,
            chart_url=config.chart_url,
        )
        session.add(entry)
    else:
        # Add to volume, update price/mcap
        entry.volume_30m += buy_event["usd_amount"]
        entry.market_cap = buy_event["market_cap"]
        entry.price = buy_event["price"]
        entry.last_updated = now
    await session.commit()

# --- LEADERBOARD PERIODIC TASK ---

async def leaderboard_task():
    while True:
        await asyncio.sleep(60 * 30)
        async with async_session() as session:
            # Fetch top 10 by volume_30m + boost_points
            q = await session.execute(
                select(TokenLeaderboard).order_by(
                    (TokenLeaderboard.volume_30m + TokenLeaderboard.boost_points).desc()
                ).limit(10)
            )
            entries = q.scalars().all()
            leaderboard = [
                {
                    "symbol": e.token_symbol,
                    "telegram": e.telegram,
                    "mcap": e.market_cap,
                    "volume": e.volume_30m,
                    "change": f"{e.percent_change_30m:+.2f}"
                }
                for e in entries
            ]
            msg = format_leaderboard(leaderboard)
            try:
                await bot.send_message(chat_id=TRENDING_CHANNEL, text=msg)
            except Exception as e:
                logging.error(f"Error sending leaderboard: {e}")

# --- BOOST HANDLER ---

class BoostStates(StatesGroup):
    waiting_token_address = State()
    waiting_duration = State()
    waiting_deposit = State()
    confirm_boost = State()

BOOST_OPTIONS = [
    ("4 hours", 15, 4),
    ("8 hours", 20, 8),
    ("12 hours", 27, 12),
    ("24 hours", 45, 24),
    ("48 hours", 80, 48),
    ("72 hours", 110, 72),
    ("1 Week", 180, 168),
]

@dp.message(Command("boost"))
async def boost_start(message: types.Message, state: FSMContext):
    await message.answer("Enter the token contract address you want to boost:")
    await state.set_state(BoostStates.waiting_token_address)

@dp.message(BoostStates.waiting_token_address)
async def boost_token_addr(message: types.Message, state: FSMContext):
    await state.update_data(token_address=message.text.strip())
    opts = "\n".join([f"{i+1}. {x[0]} - {x[1]} SUI" for i, x in enumerate(BOOST_OPTIONS)])
    await message.answer(f"Select boost duration:\n{opts}\n\nReply with the number (e.g., 1 for 4 hours):")
    await state.set_state(BoostStates.waiting_duration)

@dp.message(BoostStates.waiting_duration)
async def boost_duration(message: types.Message, state: FSMContext):
    try:
        idx = int(message.text.strip()) - 1
        option = BOOST_OPTIONS[idx]
        await state.update_data(duration=option[2], price=option[1])
    except Exception:
        await message.answer("Please reply with a valid number (1-7).")
        return
    await message.answer(f"Send {option[1]} SUI to {BOOST_WALLET_ADDRESS}.\n"
                         f"Reply with your transaction hash after payment:")
    await state.set_state(BoostStates.waiting_deposit)

@dp.message(BoostStates.waiting_deposit)
async def boost_deposit(message: types.Message, state: FSMContext):
    tx_hash = message.text.strip()
    data = await state.get_data()
    # TODO: Verify transaction on-chain (out of scope for this example)
    await state.update_data(tx_hash=tx_hash)
    await message.answer("Verifying payment...")
    # Simulate verification success
    await asyncio.sleep(2)
    # Activate boost
    now = datetime.datetime.utcnow()
    end_time = now + datetime.timedelta(hours=data["duration"])
    async with async_session() as session:
        # Only one boost per token at a time
        await session.execute(
            update(Boost)
            .where(Boost.token_address == data["token_address"], Boost.is_active == True)
            .values(is_active=False)
        )
        boost = Boost(
            token_address=data["token_address"],
            start_time=now,
            end_time=end_time,
            paid_amount=data["price"],
            owner=message.from_user.id,
            group_id=str(message.from_user.id),
            is_active=True,
        )
        session.add(boost)
        await session.commit()
    await message.answer("Boost activated!")
    # Alert trending channel
    try:
        await bot.send_message(
            chat_id=TRENDING_CHANNEL,
            text=f"🚀 <b>BOOST ACTIVATED</b> for <code>{data['token_address']}</code>! Every buy will be posted here for the next {data['duration']} hours!"
        )
    except Exception:
        pass
    await state.clear()

# --- MAIN ENTRYPOINT ---

async def main():
    await init_db()
    # Start Sui event listener in background
    asyncio.create_task(sui_api.listen_for_buys(handle_buy_event))
    # Start leaderboard updater
    asyncio.create_task(leaderboard_task())
    # Start bot polling
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
