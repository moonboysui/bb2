import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Dict, Any, Union
import aiohttp
from urllib.parse import urlparse

class Utils:
    @staticmethod
    def format_amount(amount: Union[Decimal, float, str], decimals: int = 2) -> str:
        """Format numerical amounts with proper separators and decimals"""
        try:
            if isinstance(amount, str):
                amount = Decimal(amount)
            
            if amount >= 1_000_000:
                return f"${amount / 1_000_000:,.2f}M"
            elif amount >= 1_000:
                return f"${amount / 1_000:,.2f}K"
            else:
                return f"${amount:,.{decimals}f}"
        except:
            return "$0.00"

    @staticmethod
    def format_large_number(number: Union[Decimal, int, float]) -> str:
        """Format large numbers with K, M, B suffixes"""
        try:
            number = float(number)
            if number >= 1_000_000_000:
                return f"{number / 1_000_000_000:.1f}B"
            elif number >= 1_000_000:
                return f"{number / 1_000_000:.1f}M"
            elif number >= 1_000:
                return f"{number / 1_000:.1f}K"
            else:
                return f"{number:.1f}"
        except:
            return "0"

    @staticmethod
    def format_price_change(change: Decimal) -> str:
        """Format price change with color emoji"""
        try:
            if change > 0:
                return f"🟢 +{change:.2f}%"
            elif change < 0:
                return f"🔴 {change:.2f}%"
            else:
                return "⚪ 0.00%"
        except:
            return "⚪ 0.00%"

    @staticmethod
    def shorten_address(address: str, chars: int = 4) -> str:
        """Shorten blockchain address"""
        if not address:
            return ""
        return f"{address[:chars]}...{address[-chars:]}"

    @staticmethod
    def validate_url(url: str) -> bool:
        """Validate URL format"""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except:
            return False

    @staticmethod
    def is_valid_emoji(text: str) -> bool:
        """Check if string is a valid emoji"""
        if not text:
            return False
        return len(text.encode('utf-16-le')) >= 4 and len(text) <= 2

    @staticmethod
    def parse_amount(amount_str: str) -> Optional[Decimal]:
        """Parse amount string to Decimal"""
        try:
            # Remove currency symbols and whitespace
            cleaned = re.sub(r'[^\d.]', '', amount_str)
            return Decimal(cleaned)
        except:
            return None

    @staticmethod
    def utc_now() -> datetime:
        """Get current UTC datetime"""
        return datetime.now(timezone.utc)

    @staticmethod
    def format_duration(hours: int) -> str:
        """Format duration in hours to human readable string"""
        if hours >= 168:  # 1 week
            weeks = hours // 168
            return f"{weeks}w"
        elif hours >= 24:
            days = hours // 24
            return f"{days}d"
        else:
            return f"{hours}h"

    @staticmethod
    def format_timeago(dt: datetime) -> str:
        """Format datetime to time ago string"""
        now = Utils.utc_now()
        diff = now - dt
        
        seconds = diff.total_seconds()
        if seconds < 60:
            return "just now"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            return f"{minutes}m ago"
        elif seconds < 86400:
            hours = int(seconds / 3600)
            return f"{hours}h ago"
        elif seconds < 604800:
            days = int(seconds / 86400)
            return f"{days}d ago"
        else:
            return dt.strftime("%Y-%m-%d")

    @staticmethod
    async def get_sui_price() -> Decimal:
        """Get current SUI price from CoinGecko"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.coingecko.com/api/v3/simple/price",
                    params={
                        "ids": "sui",
                        "vs_currencies": "usd"
                    }
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return Decimal(str(data["sui"]["usd"]))
        except:
            pass
        return Decimal("0")

    @staticmethod
    def calculate_boost_multiplier(paid_amount: Decimal) -> Decimal:
        """Calculate boost multiplier based on paid amount"""
        # Base multiplier is 1.5x
        base_multiplier = Decimal("1.5")
        
        # Additional multiplier based on payment amount
        if paid_amount >= 180:  # 1 week
            return base_multiplier * Decimal("2.5")
        elif paid_amount >= 110:  # 72 hours
            return base_multiplier * Decimal("2.0")
        elif paid_amount >= 80:  # 48 hours
            return base_multiplier * Decimal("1.8")
        elif paid_amount >= 45:  # 24 hours
            return base_multiplier * Decimal("1.5")
        elif paid_amount >= 27:  # 12 hours
            return base_multiplier * Decimal("1.3")
        elif paid_amount >= 20:  # 8 hours
            return base_multiplier * Decimal("1.2")
        else:  # 4 hours
            return base_multiplier

    @staticmethod
    def generate_buy_link(token_address: str) -> str:
        """Generate buy link for token"""
        return f"https://app.cetus.zone/swap?from=sui&to={token_address}"

    @staticmethod
    def generate_chart_link(token_address: str) -> str:
        """Generate chart link for token"""
        return f"https://dexscreener.com/sui/{token_address}"

    @staticmethod
    def safe_division(numerator: Decimal, denominator: Decimal) -> Decimal:
        """Safely divide two decimals"""
        try:
            if denominator == 0:
                return Decimal("0")
            return numerator / denominator
        except:
            return Decimal("0")
