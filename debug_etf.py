import asyncio
import logging
import sys
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add project root to sys.path
sys.path.append(os.getcwd())

from bot.market_overview import market_overview

async def debug_etf():
    print("--- DEBUGGING ETF FETCHING ---")
    
    # 1. Fetch Flows
    flows = await market_overview.fetch_etf_flows()
    print(f"\nResult: {flows}")
    
    # 2. Test AI Summary generation (mock data)
    print("\n--- DEBUGGING AI GENERATION ---")
    market_data = {
        "BTC": {"price": "90,123", "change_24h": 1.2},
        "ETH": {"price": "3,100", "change_24h": -0.5},
        "btc_etf_flow": 123.4,
        "eth_etf_flow": -12.5,
        "btc_etf_date": "10 Jan",
        "eth_etf_date": "10 Jan"
    }
    news = [{"title": "Test News 1", "source": "Decrypt"}, {"title": "Test News 2", "source": "CoinDesk"}]
    
    summary = await market_overview.generate_summary(market_data, news, "DEBUG TEST")
    print(f"\nAI Summary Length: {len(summary)}")
    print(f"AI Summary Content:\n{summary}")

if __name__ == "__main__":
    try:
        asyncio.run(debug_etf())
    except Exception as e:
        logger.exception("Run failed")
