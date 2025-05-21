import re
from aiogram import types
from sqlalchemy.ext.asyncio import AsyncSession
from database import GroupConfig

def short_addr(addr: str) -> str:
    if not addr or len(addr) < 10:
        return addr
    return f"{addr[:6]}...{addr[-4:]}"

def format_number(n, decimals=2):
    if n is None:
        return "N/A"
    if n >= 1_000_000:
        return f"{n/1_000_000:.{decimals}f}M"
    if n >= 1_000:
        return f"{n/1_000:.{decimals}f}K"
    return f"{n:.{decimals}f}"

def is_admin(member: types.ChatMember) -> bool:
    return getattr(member, 'is_chat_admin', False) or getattr(member, 'status', '') in ('administrator', 'creator')

def valid_url(url: str) -> bool:
    return re.match(r'https?://', url or '')

def buy_emoji_line(emoji: str, usd: float, step: float) -> str:
    if not emoji or not step or step <= 0:
        return ""
    count = int(usd // step)
    return emoji * min(count, 50)  # prevent emoji spam, max 50

def get_swap_link(token_address: str) -> str:
    # Generic swap link, can be customized
    return f"https://dexscreener.com/sui/{token_address}"

async def get_group_config(session: AsyncSession, group_id: str) -> GroupConfig:
    return await session.get(GroupConfig, group_id)

def format_alert(data: dict, config: GroupConfig, trending_channel=''):
    # Compose alert message with all required formatting, links, and rich info
    # See your spec for required fields
    token = config.token_symbol
    emoji = config.emoji or ""
    buy_line = buy_emoji_line(emoji, data['usd_amount'], config.buy_step)
    token_telegram = config.telegram or "#"
    alert = (
        f"<b><a href='{token_telegram}'>{token} Buy!</a></b>\n"
        f"{buy_line}\n"
        f"⬅️ Size ${format_number(data['usd_amount'])} | {format_number(data['sui_amount'])} SUI\n"
        f"➡️ Got {format_number(data['token_amount'])} {token}\n\n"
        f"👤 Buyer <a href='{data['buyer_link']}'>{short_addr(data['buyer'])}</a> | "
        f"<a href='{data['txn_link']}'>Txn</a>\n"
        f"🔼 MCap ${format_number(data['market_cap'])}\n"
        f"📊 TVL/Liq ${format_number(data['tvl'])}\n"
        f"📊 Price ${format_number(data['price'], 5)}\n"
        f"💧 SUI Price: ${format_number(data['sui_price'], 2)}\n\n"
        f"<a href='{config.website}'>Website</a> | "
        f"<a href='{config.telegram}'>Telegram</a> | "
        f"<a href='{config.x}'>X</a>\n\n"
        f"Chart ({config.chart_url}) | Vol. Bot (https://t.me/suivolumebot) | "
        f"Sui Trending ({trending_channel or 'https://t.me/moonbagstrending'})\n"
        f"———\n"
        f"Ad: Place your advertisement here (https://t.me/BullsharkTrendingBot?start=adBuyRequest)"
    )
    return alert

def format_leaderboard(entries: list):
    header = "<b>Top 10 Trending Tokens (30m Vol)</b>\n\n"
    lines = []
    for i, entry in enumerate(entries, 1):
        lines.append(
            f"{i}. <a href='{entry['telegram']}'>{entry['symbol']}</a> | "
            f"MCap: ${format_number(entry['mcap'])} | "
            f"30m Vol: ${format_number(entry['volume'])} | "
            f"{entry['change']}%"
        )
    return header + "\n".join(lines)
