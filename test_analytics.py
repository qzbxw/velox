import sys
import os
sys.path.append(os.getcwd())

from bot.analytics import generate_market_overview_image

# Mock Data
universe = [{"name": "BTC"}, {"name": "ETH"}, {"name": "SOL"}]
assets_ctx = [
    {
        "markPx": "50000.0",
        "prevDayPx": "48000.0", # +4.16%
        "funding": "0.0001",
        "dayNtlVlm": "100000000",
        "openInterest": "50000"
    },
    {
        "markPx": "3000.0",
        "prevDayPx": "3100.0", # -3.2%
        "funding": "0.0002",
        "dayNtlVlm": "50000000",
        "openInterest": "20000"
    },
    {
        "markPx": "100.0",
        "prevDayPx": "0", # Should handle 0
        "funding": "0.0001",
        "dayNtlVlm": "10000000",
        "openInterest": "10000"
    }
]

print("Testing generation...")
buf = generate_market_overview_image(assets_ctx, universe, sort_by="change")

if buf:
    print("Success! Image generated.")
    with open("test_overview.png", "wb") as f:
        f.write(buf.read())
else:
    print("Failed to generate image.")
