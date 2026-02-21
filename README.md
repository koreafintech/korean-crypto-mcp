# Korean Crypto MCP Server

Real-time Korean cryptocurrency data via Upbit exchange — kimchi premium, live prices, top movers, and exchange comparison.

## Tools

| Tool | Description |
|------|-------------|
| `get_price` | Real-time price from Upbit. e.g. `KRW-BTC` |
| `get_kimchi_premium` | Kimchi premium % (Upbit vs CoinGecko global price) |
| `get_top_movers` | Top gaining/losing coins in last 24h |
| `compare_exchanges` | Upbit vs Bithumb price comparison |
| `get_orderbook` | Live order book for any KRW market |
| `get_candles` | OHLCV candle data (minutes/hours/days) |
| `get_markets` | List all available markets (KRW/BTC/USDT) |

## Example Usage

```
# Get Bitcoin kimchi premium
get_kimchi_premium(coin="BTC")
→ 🌶️ BTC Kimchi Premium: +2.34%

# Top 10 gainers today
get_top_movers(direction="up", limit=10)

# Compare BTC price between exchanges
compare_exchanges(coin="BTC")
→ Upbit: 99,800,000 KRW / Bithumb: 99,750,000 KRW
```

## What is Kimchi Premium?

The "kimchi premium" refers to the price difference between Korean crypto exchanges (like Upbit) and global exchanges. When Korean prices are higher than global prices, it's a positive kimchi premium. This server calculates it in real-time using Upbit vs CoinGecko pricing.

## Live Server

Hosted 24/7 on Railway:
```
https://web-production-fa47d.up.railway.app
```

## Connect via Smithery

```bash
smithery install koreafintech/korean-crypto-mcp
```

## Features

- ✅ Real-time Upbit data (100+ KRW markets)
- ✅ Kimchi premium calculation with live FX rates
- ✅ Upbit vs Bithumb arbitrage comparison  
- ✅ A2A Agent Card compatible
- ✅ Telegram alert bot (configurable thresholds)
