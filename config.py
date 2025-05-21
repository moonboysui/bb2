import re
from enum import Enum, auto
from dataclasses import dataclass
from typing import Optional, Dict, Any
from decimal import Decimal
from datetime import datetime
from sui_api import SuiAPI

class ConfigState(Enum):
    """Configuration states for the setup flow"""
    IDLE = auto()
    AWAITING_TOKEN = auto()
    AWAITING_EMOJI = auto()
    AWAITING_MIN_BUY = auto()
    AWAITING_BUY_STEP = auto()
    AWAITING_TELEGRAM = auto()
    AWAITING_WEBSITE = auto()
    AWAITING_TWITTER = auto()
    AWAITING_MEDIA = auto()

@dataclass
class Config:
    """Configuration class for group settings"""
    group_id: int
    state: ConfigState = ConfigState.IDLE
    
    # Token configuration
    token_address: Optional[str] = None
    token_symbol: Optional[str] = None
    emoji: str = "🌙"
    min_buy: Decimal = Decimal("1.0")
    buy_step: Decimal = Decimal("5.0")
    
    # Social links
    telegram_link: Optional[str] = None
    website_link: Optional[str] = None
    twitter_link: Optional[str] = None
    
    # Custom media
    custom_media: Optional[Dict[str, str]] = None
    
    # Validation patterns
    TELEGRAM_PATTERN = r'^https?:\/\/(t\.me|telegram\.me)\/[a-zA-Z0-9_]{5,}$'
    WEBSITE_PATTERN = r'^https?:\/\/[\w\-\.]+\.[a-zA-Z]{2,}(?:\/[\w\-\._~:/?#\[\]@!\$&\'\(\)\*\+,;=]*)?$'
    TWITTER_PATTERN = r'^https?:\/\/(twitter\.com|x\.com)\/[a-zA-Z0-9_]{1,15}$'
    
    async def validate_token(self, address: str) -> tuple[bool, str]:
        """Validate token address and fetch symbol"""
        try:
            # Check format
            if not re.match(r'^0x[a-fA-F0-9]{64}$', address):
                return False, "Invalid token address format. Please provide a valid Sui token address."
            
            # Check if token exists and get data
            token_data = await SuiAPI.get_token_data(address)
            if not token_data:
                return False, "Token not found on Sui blockchain. Please check the address."
            
            self.token_address = address
            self.token_symbol = token_data.symbol
            return True, f"Token {token_data.symbol} ({token_data.name}) configured successfully!"
            
        except Exception as e:
            return False, f"Error validating token: {str(e)}"

    def validate_emoji(self, emoji: str) -> tuple[bool, str]:
        """Validate emoji input"""
        # Remove whitespace
        emoji = emoji.strip()
        
        # Check if it's a single emoji
        if len(emoji) > 2:  # Most emojis are 1-2 characters
            return False, "Please provide a single emoji."
        
        # Basic emoji validation (this is simplified)
        if not any(ord(c) > 127 for c in emoji):
            return False, "Invalid emoji. Please provide a valid emoji character."
        
        self.emoji = emoji
        return True, "Emoji set successfully!"

    def validate_amount(self, amount: str, is_min_buy: bool = True) -> tuple[bool, str]:
        """Validate numerical amount input"""
        try:
            # Remove any currency symbols and whitespace
            amount = amount.replace('$', '').strip()
            
            # Convert to Decimal
            value = Decimal(amount)
            
            # Validate range
            if value <= 0:
                return False, "Amount must be greater than 0."
            
            if is_min_buy:
                if value > 1000000:
                    return False, "Minimum buy amount cannot exceed $1,000,000."
                self.min_buy = value
                return True, f"Minimum buy amount set to ${value}!"
            else:
                if value > 10000:
                    return False, "Buy step cannot exceed $10,000."
                self.buy_step = value
                return True, f"Buy step set to ${value}!"
                
        except (ValueError, DecimalException):
            return False, "Invalid amount. Please enter a valid number."

    def validate_link(self, link: str, link_type: str) -> tuple[bool, str]:
        """Validate social media links"""
        # Remove whitespace
        link = link.strip()
        
        if link.lower() == "none":
            if link_type == "telegram":
                self.telegram_link = None
            elif link_type == "website":
                self.website_link = None
            elif link_type == "twitter":
                self.twitter_link = None
            return True, f"{link_type.capitalize()} link removed."
        
        # Validate format
        if link_type == "telegram":
            if not re.match(self.TELEGRAM_PATTERN, link):
                return False, "Invalid Telegram link. Please use format: https://t.me/username"
            self.telegram_link = link
        
        elif link_type == "website":
            if not re.match(self.WEBSITE_PATTERN, link):
                return False, "Invalid website URL. Please provide a valid HTTP(S) URL."
            self.website_link = link
        
        elif link_type == "twitter":
            if not re.match(self.TWITTER_PATTERN, link):
                return False, "Invalid Twitter/X link. Please use format: https://twitter.com/username"
            self.twitter_link = link
        
        return True, f"{link_type.capitalize()} link set successfully!"

    def validate_media(self, media_data: Any) -> tuple[bool, str]:
        """Validate custom media input"""
        # For now, just store the media file_id
        if isinstance(media_data, str):
            self.custom_media = {"file_id": media_data}
            return True, "Custom media set successfully!"
        return False, "Invalid media format."

    async def handle_input(self, input_text: str) -> tuple[bool, str]:
        """Handle user input based on current state"""
        try:
            if self.state == ConfigState.AWAITING_TOKEN:
                return await self.validate_token(input_text)
            
            elif self.state == ConfigState.AWAITING_EMOJI:
                return self.validate_emoji(input_text)
            
            elif self.state == ConfigState.AWAITING_MIN_BUY:
                return self.validate_amount(input_text, is_min_buy=True)
            
            elif self.state == ConfigState.AWAITING_BUY_STEP:
                return self.validate_amount(input_text, is_min_buy=False)
            
            elif self.state == ConfigState.AWAITING_TELEGRAM:
                return self.validate_link(input_text, "telegram")
            
            elif self.state == ConfigState.AWAITING_WEBSITE:
                return self.validate_link(input_text, "website")
            
            elif self.state == ConfigState.AWAITING_TWITTER:
                return self.validate_link(input_text, "twitter")
            
            elif self.state == ConfigState.AWAITING_MEDIA:
                return self.validate_media(input_text)
            
            return False, "Invalid configuration state."
            
        except Exception as e:
            return False, f"Error processing input: {str(e)}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary for database storage"""
        return {
            "group_id": self.group_id,
            "token_address": self.token_address,
            "token_symbol": self.token_symbol,
            "emoji": self.emoji,
            "min_buy": str(self.min_buy),
            "buy_step": str(self.buy_step),
            "telegram_link": self.telegram_link,
            "website_link": self.website_link,
            "twitter_link": self.twitter_link,
            "custom_media": self.custom_media
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Config':
        """Create configuration from dictionary"""
        config = cls(group_id=data["group_id"])
        config.token_address = data.get("token_address")
        config.token_symbol = data.get("token_symbol")
        config.emoji = data.get("emoji", "🌙")
        config.min_buy = Decimal(data.get("min_buy", "1.0"))
        config.buy_step = Decimal(data.get("buy_step", "5.0"))
        config.telegram_link = data.get("telegram_link")
        config.website_link = data.get("website_link")
        config.twitter_link = data.get("twitter_link")
        config.custom_media = data.get("custom_media")
        return config
