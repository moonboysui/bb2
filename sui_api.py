import asyncio
import aiohttp
import websockets
import json
import os
import datetime
from typing import List, Dict, Optional

# List of contract addresses (update as needed)
MOONBAGS_CONTRACTS = [
    # Example addresses. Update with actual from https://suiscan.xyz/mainnet/directory/MoonBags
    "0x7b888393d6a552819bb0a7f878183abaf04550bfb9546b20ea586d338210826f",  # moonbags
]
SPLASH_CONTRACTS = [
    # Add Splash.xyz contract addresses here
]
MOVEPUMP_CONTRACTS = [
    # Add MovePump contract addresses here
]
TURBOS_CONTRACTS = [
    # Add Turbos.fun contract addresses here
]
ALL_LAUNCHPAD_CONTRACTS = set(MOONBAGS_CONTRACTS + SPLASH_CONTRACTS + MOVEPUMP_CONTRACTS + TURBOS_CONTRACTS)

BLOCKEDEN_WSS = os.environ.get("BLOCKEDEN_WSS")
BLOCKEDEN_RPC = os.environ.get("BLOCKEDEN_RPC")
SUIVISION_API_KEY = os.environ.get("SUIVISION_API_KEY")

# Helper: get SUI/USD price from Suivision (fallback to 1 if unavailable)
async def get_sui_usd():
    if not SUIVISION_API_KEY:
        return 1.0
    url = "https://api.suivision.xyz/v1/market/price"
    headers = {"Authorization": SUIVISION_API_KEY}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as r:
                data = await r.json()
                return float(data.get("price", 1.0))
    except Exception:
        return 1.0

# Helper: get token info from Suivision (if listed on DEX)
async def get_token_market_info(token_address: str) -> dict:
    if not SUIVISION_API_KEY:
        return {}
    url = f"https://api.suivision.xyz/v1/token/{token_address}"
    headers = {"Authorization": SUIVISION_API_KEY}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                return await resp.json()
            return {}

# Main event listener coroutine
async def listen_for_buys(on_buy_callback):
    async with websockets.connect(BLOCKEDEN_WSS) as ws:
        # Subscribe to events for all launchpad contracts
        for pkg in ALL_LAUNCHPAD_CONTRACTS:
            subscribe_msg = {
                "jsonrpc": "2.0",
                "id": int(pkg[-6:], 16) % 1000000,
                "method": "sui_subscribeEvent",
                "params": [{
                    "MoveEvent": {
                        "package": pkg
                    }
                }]
            }
            await ws.send(json.dumps(subscribe_msg))
        print("Subscribed to launchpad contracts for buy events.")

        while True:
            try:
                msg = await ws.recv()
                data = json.loads(msg)
                if "result" in data and "params" in data["result"]:
                    evt = data["result"]["params"]["result"]
                    await process_event(evt, on_buy_callback)
            except Exception as e:
                print(f"Error in Sui event loop: {e}")
                await asyncio.sleep(2)

# Helper: parse event and call on_buy_callback if relevant
async def process_event(event: dict, on_buy_callback):
    evt_type = event.get("type", "")
    parsed = event.get("parsedJson", {})
    # Typical buy event types: "Minted", "Purchased", or DEX Swap (depends on contract)
    if any(x in evt_type for x in ["Minted", "Purchased", "Swap"]):
        # Extract relevant data; structure may change per launchpad!
        buyer = parsed.get("buyer") or parsed.get("recipient") or parsed.get("user")
        amount_sui = float(parsed.get("amount", 0))
        token_amount = float(parsed.get("token_amount", 0))
        token = parsed.get("token") or parsed.get("token_id") or event.get("package")
        tx_hash = event.get("id", "")
        timestamp = event.get("timestamp", datetime.datetime.utcnow().isoformat())
        # Fetch market data
        market_info = await get_token_market_info(token)
        sui_usd = await get_sui_usd()
        usd_amount = amount_sui * sui_usd
        mcap = market_info.get("market_cap", 0)
        tvl = market_info.get("tvl", 0)
        price = market_info.get("price", 0)
        # Compose event
        buy_event = {
            "buyer": buyer,
            "sui_amount": amount_sui,
            "token_amount": token_amount,
            "usd_amount": usd_amount,
            "token": token,
            "market_cap": mcap,
            "tvl": tvl,
            "price": price,
            "sui_price": sui_usd,
            "tx_hash": tx_hash,
            "timestamp": timestamp,
            "buyer_link": f"https://suivision.xyz/account/{buyer}",
            "txn_link": f"https://suivision.xyz/txblock/{tx_hash}",
        }
        await on_buy_callback(buy_event)

# Utility: fetch token metadata from Sui RPC (for symbol, decimals, etc.)
async def get_token_metadata(token_address: str) -> dict:
    url = BLOCKEDEN_RPC
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "sui_getObject",
        "params": [token_address]
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                data = await resp.json()
                details = data.get("result", {}).get("details", {})
                fields = details.get("data", {}).get("fields", {})
                return {
                    "symbol": fields.get("symbol", ""),
                    "name": fields.get("name", ""),
                    "decimals": fields.get("decimals", 9)
                }
    except Exception:
        return {}

# For DEX tokens: add code here to subscribe to swap events for major Sui DEX contracts

# You can expand this file with more helpers as needed!
