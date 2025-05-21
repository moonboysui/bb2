import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Callable, Any
import aiohttp
from decimal import Decimal
from dataclasses import dataclass
import json
import websockets
from websockets.exceptions import ConnectionClosed
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# API Constants
BLOCKEDEN_WSS = os.environ.get("BLOCKEDEN_WSS")
BLOCKEDEN_RPC = os.environ.get("BLOCKEDEN_RPC")
SUIVISION_API_KEY = os.environ.get("SUIVISION_API_KEY")

@dataclass
class TokenData:
    address: str
    name: str
    symbol: str
    decimals: int
    total_supply: Decimal
    price: Decimal
    mcap: Decimal
    liquidity: Decimal
    volume_30m: Decimal
    price_change_30m: Decimal
    telegram_link: Optional[str] = None
    website_link: Optional[str] = None
    twitter_link: Optional[str] = None
    is_boosted: bool = False

@dataclass
class BuyData:
    token_address: str
    buyer_address: str
    amount_sui: Decimal
    amount_usd: Decimal
    token_amount: Decimal
    price: Decimal
    mcap: Decimal
    liquidity: Decimal
    sui_price: Decimal
    timestamp: datetime
    tx_hash: str
    buyer_url: str
    tx_url: str
    chart_url: str
    buy_url: str

class SuiAPI:
    _instance = None
    _token_cache: Dict[str, TokenData] = {}
    _price_history: Dict[str, List[Dict[str, Any]]] = {}
    _ws_client = None
    _session = None

    @classmethod
    async def get_instance(cls):
        if not cls._instance:
            cls._instance = cls()
            await cls._instance._init()
        return cls._instance

    async def _init(self):
        """Initialize HTTP session"""
        self._session = aiohttp.ClientSession()

    @classmethod
    async def start_buy_monitoring(cls, callback: Callable):
        """Start WebSocket connection to monitor buys"""
        while True:
            try:
                async with websockets.connect(BLOCKEDEN_WSS) as websocket:
                    logger.info("Connected to Sui WebSocket")
                    
                    # Subscribe to swap events
                    await websocket.send(json.dumps({
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "sui_subscribeEvent",
                        "params": [{
                            "Filter": {
                                "MoveEventType": "0x2::dex::SwapEvent"
                            }
                        }]
                    }))

                    while True:
                        try:
                            msg = await websocket.recv()
                            event = json.loads(msg)
                            
                            if "params" in event:
                                buy_data = await cls._process_swap_event(event["params"])
                                if buy_data:
                                    await callback(buy_data)
                        
                        except ConnectionClosed:
                            logger.warning("WebSocket connection closed, reconnecting...")
                            break
                        except Exception as e:
                            logger.error(f"Error processing swap event: {e}")
                            continue

            except Exception as e:
                logger.error(f"WebSocket connection error: {e}")
                await asyncio.sleep(5)

    @classmethod
    async def _process_swap_event(cls, event_data: dict) -> Optional[BuyData]:
        """Process swap event and return BuyData if it's a buy"""
        try:
            # Extract relevant data from event
            token_in = event_data["amount_in"]["token"]
            token_out = event_data["amount_out"]["token"]
            
            # Only process SUI -> Token swaps (buys)
            if token_in != "0x2::sui::SUI":
                return None
                
            token_address = token_out
            token_data = await cls.get_token_data(token_address)
            
            if not token_data:
                return None
            
            # Calculate amounts
            amount_sui = Decimal(event_data["amount_in"]["amount"]) / Decimal(10**9)  # SUI decimals
            amount_usd = amount_sui * await cls.get_sui_price()
            token_amount = Decimal(event_data["amount_out"]["amount"]) / Decimal(10**token_data.decimals)
            
            return BuyData(
                token_address=token_address,
                buyer_address=event_data["sender"],
                amount_sui=amount_sui,
                amount_usd=amount_usd,
                token_amount=token_amount,
                price=token_data.price,
                mcap=token_data.mcap,
                liquidity=token_data.liquidity,
                sui_price=await cls.get_sui_price(),
                timestamp=datetime.utcnow(),
                tx_hash=event_data["tx_digest"],
                buyer_url=f"https://suivision.xyz/account/{event_data['sender']}",
                tx_url=f"https://suivision.xyz/txblock/{event_data['tx_digest']}",
                chart_url=f"https://dexscreener.com/sui/{token_address}",
                buy_url=f"https://app.cetus.zone/swap?from=sui&to={token_address}"
            )
            
        except Exception as e:
            logger.error(f"Error processing swap event: {e}")
            return None

    @classmethod
    async def get_token_data(cls, address: str) -> Optional[TokenData]:
        """Get token data with caching"""
        try:
            # Check cache first
            if address in cls._token_cache:
                cached = cls._token_cache[address]
                if datetime.utcnow() - cached.timestamp < timedelta(minutes=5):
                    return cached.data

            # Fetch from API
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{BLOCKEDEN_RPC}/token/{address}",
                    headers={"x-api-key": SUIVISION_API_KEY}
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        token = TokenData(
                            address=address,
                            name=data["name"],
                            symbol=data["symbol"],
                            decimals=data["decimals"],
                            total_supply=Decimal(data["total_supply"]),
                            price=Decimal(data["price"]),
                            mcap=Decimal(data["market_cap"]),
                            liquidity=Decimal(data["liquidity"]),
                            volume_30m=Decimal(data["volume_30m"]),
                            price_change_30m=Decimal(data["price_change_percentage_30m"])
                        )
                        
                        # Cache the result
                        cls._token_cache[address] = {
                            "data": token,
                            "timestamp": datetime.utcnow()
                        }
                        
                        return token
            
            return None
        except Exception as e:
            logger.error(f"Error fetching token data: {e}")
            return None

    @classmethod
    async def get_trending_tokens(cls) -> List[TokenData]:
        """Get trending tokens sorted by volume and boost status"""
        try:
            # Fetch top 100 tokens by volume
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{BLOCKEDEN_RPC}/trending",
                    headers={"x-api-key": SUIVISION_API_KEY}
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        tokens = []
                        for token_data in data["tokens"]:
                            token = await cls.get_token_data(token_data["address"])
                            if token:
                                tokens.append(token)
                        
                        # Sort by volume and boost status
                        return sorted(
                            tokens,
                            key=lambda x: (x.is_boosted, x.volume_30m),
                            reverse=True
                        )
            
            return []
        except Exception as e:
            logger.error(f"Error fetching trending tokens: {e}")
            return []

    @classmethod
    async def verify_payment(cls, wallet: str, amount: Decimal, start_time: datetime) -> bool:
        """Verify SUI payment"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{BLOCKEDEN_RPC}/account/{wallet}/transactions",
                    params={"start_time": start_time.isoformat()},
                    headers={"x-api-key": SUIVISION_API_KEY}
                ) as response:
                    if response.status == 200:
                        txs = await response.json()
                        
                        for tx in txs:
                            if (
                                tx["kind"] == "Pay"
                                and tx["status"] == "success"
                                and Decimal(tx["amount"]) / Decimal(10**9) == amount
                            ):
                                return True
            
            return False
        except Exception as e:
            logger.error(f"Error verifying payment: {e}")
            return False

    @classmethod
    async def get_sui_price(cls) -> Decimal:
        """Get current SUI price in USD"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{BLOCKEDEN_RPC}/price/sui",
                    headers={"x-api-key": SUIVISION_API_KEY}
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return Decimal(str(data["price"]))
            
            return Decimal("0")
        except Exception as e:
            logger.error(f"Error fetching SUI price: {e}")
            return Decimal("0")

    @classmethod
    async def token_exists(cls, address: str) -> bool:
        """Check if token exists on Sui"""
        try:
            token_data = await cls.get_token_data(address)
            return bool(token_data)
        except Exception:
            return False
