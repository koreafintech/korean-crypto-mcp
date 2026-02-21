"""
Korean Crypto MCP Server v3
업비트 + 빗썸 + 김치프리미엄
FastMCP (stdio) + FastAPI (HTTP) 듀얼 모드
"""

import asyncio
import os
import sys
import httpx
from mcp.server.fastmcp import FastMCP
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# ── MCP 서버 ──────────────────────────────────────────
mcp = FastMCP("korean-crypto")

UPBIT     = "https://api.upbit.com/v1"
BITHUMB   = "https://api.bithumb.com/public"
COINGECKO = "https://api.coingecko.com/api/v3"
FX_URL    = "https://open.er-api.com/v6/latest/USD"

# 코인 심볼 → CoinGecko ID 매핑
COINGECKO_IDS = {
    "BTC": "bitcoin", "ETH": "ethereum", "XRP": "ripple",
    "SOL": "solana", "ADA": "cardano", "DOGE": "dogecoin",
    "AVAX": "avalanche-2", "DOT": "polkadot", "MATIC": "matic-network",
    "LINK": "chainlink", "UNI": "uniswap", "ATOM": "cosmos",
    "LTC": "litecoin", "BCH": "bitcoin-cash", "ETC": "ethereum-classic",
    "NEAR": "near", "APT": "aptos", "ARB": "arbitrum",
    "OP": "optimism", "SUI": "sui", "TRX": "tron",
    "SHIB": "shiba-inu", "PEPE": "pepe", "BNB": "binancecoin",
    "TON": "the-open-network", "STX": "blockstack",
    "SAND": "the-sandbox", "MANA": "decentraland",
}


async def get(url, params=None):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(url, params=params)
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def get_price(market: str) -> str:
    """업비트 실시간 현재가. 예: KRW-BTC 또는 KRW-BTC,KRW-ETH"""
    data = await get(f"{UPBIT}/ticker", params={"markets": market.upper()})
    lines = []
    for d in data:
        icon = "🟢" if d["change"] == "RISE" else ("🔴" if d["change"] == "FALL" else "⚪")
        lines.append(
            f"{icon} {d['market']}\n"
            f"  현재가: {d['trade_price']:,.0f}원\n"
            f"  전일대비: {d['signed_change_rate']*100:+.2f}% ({d['signed_change_price']:+,.0f}원)\n"
            f"  고가: {d['high_price']:,.0f} / 저가: {d['low_price']:,.0f}\n"
            f"  24h 거래대금: {d['acc_trade_price_24h']/1e8:.1f}억원"
        )
    return "\n\n".join(lines)


@mcp.tool()
async def get_markets(quote: str = "KRW") -> str:
    """업비트 마켓 목록. quote: KRW / BTC / USDT"""
    data = await get(f"{UPBIT}/market/all", params={"isDetails": "false"})
    filtered = [m for m in data if m["market"].startswith(quote.upper() + "-")]
    coins = ", ".join([m["market"].split("-")[1] for m in filtered])
    return f"업비트 {quote.upper()} 마켓 ({len(filtered)}개):\n{coins}"


@mcp.tool()
async def get_orderbook(market: str) -> str:
    """업비트 호가창. 예: KRW-BTC"""
    data = await get(f"{UPBIT}/orderbook", params={"markets": market.upper()})
    ob = data[0]
    units = ob["orderbook_units"][:5]
    lines = [f"📊 {market.upper()} 호가창\n"]
    lines.append("  [매도]")
    for u in reversed(units):
        lines.append(f"  {u['ask_price']:>15,.0f}원  |  {u['ask_size']:.4f}")
    lines.append("  ─────────────────────────")
    for u in units:
        lines.append(f"  {u['bid_price']:>15,.0f}원  |  {u['bid_size']:.4f}")
    lines.append("  [매수]")
    return "\n".join(lines)


@mcp.tool()
async def get_candles(market: str, interval: str = "days", count: int = 10) -> str:
    """업비트 캔들. interval: minutes/1, minutes/60, days, weeks, months"""
    data = await get(f"{UPBIT}/candles/{interval}",
                     params={"market": market.upper(), "count": min(count, 200)})
    lines = [f"🕯️ {market.upper()} ({interval}) {count}개\n"]
    lines.append(f"{'날짜':<18} {'시가':>12} {'고가':>12} {'저가':>12} {'종가':>12}")
    lines.append("─" * 68)
    for c in data:
        dt = c.get("candle_date_time_kst", "")[:16]
        lines.append(f"{dt:<18} {c['opening_price']:>12,.0f} {c['high_price']:>12,.0f} "
                     f"{c['low_price']:>12,.0f} {c['trade_price']:>12,.0f}")
    return "\n".join(lines)


@mcp.tool()
async def get_kimchi_premium(coin: str) -> str:
    """김치프리미엄 계산. 업비트 vs CoinGecko(글로벌). 예: BTC"""
    coin = coin.upper()

    # 업비트 KRW 가격
    upbit_data = await get(f"{UPBIT}/ticker", params={"markets": f"KRW-{coin}"})
    krw_price = upbit_data[0]["trade_price"]

    # CoinGecko USD 가격
    cg_id = COINGECKO_IDS.get(coin)
    if not cg_id:
        # 매핑에 없으면 심볼로 검색 시도
        try:
            search = await get(f"{COINGECKO}/search", params={"query": coin})
            coins = search.get("coins", [])
            if not coins:
                return f"CoinGecko에서 {coin} 정보를 찾을 수 없습니다."
            cg_id = coins[0]["id"]
        except Exception:
            return f"CoinGecko에서 {coin} 정보를 가져오지 못했습니다."

    try:
        cg_data = await get(f"{COINGECKO}/simple/price",
                            params={"ids": cg_id, "vs_currencies": "usd"})
        usd_price = cg_data[cg_id]["usd"]
    except Exception:
        return f"CoinGecko에서 {coin}({cg_id}) 가격을 가져오지 못했습니다."

    # 환율
    try:
        fx = await get(FX_URL)
        usd_krw = fx["rates"]["KRW"]
    except Exception:
        usd_krw = 1350.0

    krw_equiv = usd_price * usd_krw
    pct = (krw_price - krw_equiv) / krw_equiv * 100
    emoji = "🌶️" if pct > 3 else ("🔵" if pct < -1 else "⚖️")
    comment = ("한국 시장 고평가" if pct > 5
               else "소폭 프리미엄" if pct > 2
               else "역프리미엄 — 저평가" if pct < -1
               else "중립 구간")

    return (
        f"{emoji} {coin} 김치프리미엄\n\n"
        f"  업비트:            {krw_price:>15,.0f} 원\n"
        f"  CoinGecko(USD):   {usd_price:>15,.4f} $\n"
        f"  USD/KRW 환율:      {usd_krw:>15,.2f} 원\n"
        f"  글로벌 환산가:     {krw_equiv:>15,.0f} 원\n"
        f"  ─────────────────────────────────\n"
        f"  김치프리미엄:      {pct:>+14.2f} %\n\n"
        f"  📌 {comment}"
    )


@mcp.tool()
async def compare_exchanges(coin: str) -> str:
    """업비트 vs 빗썸 가격 비교. 예: BTC"""
    coin = coin.upper()
    upbit_data = await get(f"{UPBIT}/ticker", params={"markets": f"KRW-{coin}"})
    upbit_price = upbit_data[0]["trade_price"]

    try:
        bithumb_data = await get(f"{BITHUMB}/ticker/{coin}_KRW")
        bithumb_price = float(bithumb_data["data"]["closing_price"])
    except Exception:
        return f"빗썸에서 {coin} 데이터를 가져오지 못했습니다."

    diff = upbit_price - bithumb_price
    pct = diff / bithumb_price * 100
    cheaper = "빗썸이 저렴" if diff > 0 else "업비트가 저렴"

    return (
        f"⚖️ {coin} 거래소 비교\n\n"
        f"  업비트: {upbit_price:>15,.0f} 원\n"
        f"  빗썸:   {bithumb_price:>15,.0f} 원\n"
        f"  ─────────────────────────────\n"
        f"  차이:   {diff:>+13,.0f} 원 ({pct:+.3f}%)\n"
        f"  → {cheaper}"
    )


@mcp.tool()
async def get_top_movers(direction: str = "up", limit: int = 10) -> str:
    """상승/하락 상위 코인. direction: up / down"""
    markets_data = await get(f"{UPBIT}/market/all", params={"isDetails": "false"})
    krw_markets = [m["market"] for m in markets_data if m["market"].startswith("KRW-")]

    all_tickers = []
    for i in range(0, len(krw_markets), 100):
        chunk = krw_markets[i:i+100]
        tickers = await get(f"{UPBIT}/ticker", params={"markets": ",".join(chunk)})
        all_tickers.extend(tickers)

    sorted_t = sorted(all_tickers, key=lambda x: x["signed_change_rate"], reverse=(direction == "up"))
    top = sorted_t[:limit]

    title = f"🚀 상승률 TOP {limit}" if direction == "up" else f"📉 하락률 TOP {limit}"
    lines = [f"{title} (24h)\n"]
    lines.append(f"{'#':<3} {'코인':<8} {'현재가':>12} {'변동률':>8} {'거래대금':>10}")
    lines.append("─" * 47)
    for i, t in enumerate(top, 1):
        coin = t["market"].replace("KRW-", "")
        icon = "🟢" if t["change"] == "RISE" else "🔴"
        lines.append(
            f"{i:<3} {icon}{coin:<6} "
            f"{t['trade_price']:>12,.0f} "
            f"{t['signed_change_rate']*100:>+7.2f}% "
            f"{t['acc_trade_price_24h']/1e8:>8.1f}억"
        )
    return "\n".join(lines)


# ── FastAPI HTTP 서버 ────────────────────────────────
app = FastAPI(
    title="Korean Crypto MCP API",
    description="업비트 실시간 암호화폐 데이터 API",
    version="3.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ToolRequest(BaseModel):
    arguments: dict = {}


@app.get("/")
async def root():
    return {
        "name": "korean-crypto-mcp",
        "version": "3.0.0",
        "status": "running",
        "tools": [
            "get_price", "get_markets", "get_orderbook",
            "get_candles", "get_kimchi_premium",
            "compare_exchanges", "get_top_movers"
        ]
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── A2A Agent Card ───────────────────────────────────
@app.get("/.well-known/agent.json")
async def agent_card():
    base_url = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "localhost:8000")
    if not base_url.startswith("http"):
        base_url = f"https://{base_url}"
    return {
        "name": "korean-crypto-mcp",
        "description": "한국 암호화폐 실시간 데이터 에이전트 (업비트, 빗썸, 김치프리미엄)",
        "url": base_url,
        "version": "3.0.0",
        "capabilities": {
            "streaming": False,
            "pushNotifications": False
        },
        "skills": [
            {
                "id": "get_price",
                "name": "실시간 현재가",
                "description": "업비트 실시간 현재가. 예: KRW-BTC",
                "inputModes": ["text"],
                "outputModes": ["text"]
            },
            {
                "id": "get_kimchi_premium",
                "name": "김치프리미엄",
                "description": "업비트 vs 바이낸스 김치프리미엄 계산",
                "inputModes": ["text"],
                "outputModes": ["text"]
            },
            {
                "id": "get_top_movers",
                "name": "상승/하락 TOP",
                "description": "24h 상승/하락 상위 코인",
                "inputModes": ["text"],
                "outputModes": ["text"]
            },
            {
                "id": "compare_exchanges",
                "name": "거래소 비교",
                "description": "업비트 vs 빗썸 가격 비교",
                "inputModes": ["text"],
                "outputModes": ["text"]
            }
        ]
    }


# ── A2A Task 엔드포인트 ──────────────────────────────
@app.post("/tasks/send")
async def tasks_send(request: dict):
    """A2A 표준 task 처리"""
    try:
        message = request.get("message", {})
        parts = message.get("parts", [])
        text = ""
        for part in parts:
            if part.get("type") == "text":
                text = part.get("text", "")
                break

        skill_id = request.get("skillId", "get_price")
        metadata = request.get("metadata", {})

        result = await _dispatch_skill(skill_id, text, metadata)

        return {
            "id": request.get("id", "task-1"),
            "status": {"state": "completed"},
            "artifacts": [{
                "parts": [{"type": "text", "text": result}]
            }]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _dispatch_skill(skill_id: str, text: str, metadata: dict) -> str:
    if skill_id == "get_price":
        market = metadata.get("market", text.strip() or "KRW-BTC")
        return await get_price(market)
    elif skill_id == "get_markets":
        quote = metadata.get("quote", text.strip() or "KRW")
        return await get_markets(quote)
    elif skill_id == "get_orderbook":
        market = metadata.get("market", text.strip() or "KRW-BTC")
        return await get_orderbook(market)
    elif skill_id == "get_candles":
        market = metadata.get("market", "KRW-BTC")
        interval = metadata.get("interval", "days")
        count = int(metadata.get("count", 10))
        return await get_candles(market, interval, count)
    elif skill_id == "get_kimchi_premium":
        coin = metadata.get("coin", text.strip() or "BTC")
        return await get_kimchi_premium(coin)
    elif skill_id == "compare_exchanges":
        coin = metadata.get("coin", text.strip() or "BTC")
        return await compare_exchanges(coin)
    elif skill_id == "get_top_movers":
        direction = metadata.get("direction", "up")
        limit = int(metadata.get("limit", 10))
        return await get_top_movers(direction, limit)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown skill: {skill_id}")


# ── 개별 REST 엔드포인트 (편의용) ───────────────────
@app.get("/price/{market}")
async def api_get_price(market: str):
    result = await get_price(market)
    return {"result": result}

@app.get("/markets")
async def api_get_markets(quote: str = "KRW"):
    result = await get_markets(quote)
    return {"result": result}

@app.get("/orderbook/{market}")
async def api_get_orderbook(market: str):
    result = await get_orderbook(market)
    return {"result": result}

@app.get("/candles/{market}")
async def api_get_candles(market: str, interval: str = "days", count: int = 10):
    result = await get_candles(market, interval, count)
    return {"result": result}

@app.get("/kimchi/{coin}")
async def api_kimchi(coin: str):
    result = await get_kimchi_premium(coin)
    return {"result": result}

@app.get("/compare/{coin}")
async def api_compare(coin: str):
    result = await compare_exchanges(coin)
    return {"result": result}

@app.get("/top-movers")
async def api_top_movers(direction: str = "up", limit: int = 10):
    result = await get_top_movers(direction, limit)
    return {"result": result}


# ── 실행 ────────────────────────────────────────────
if __name__ == "__main__":
    mode = os.environ.get("RUN_MODE", "http")
    if mode == "stdio":
        # Claude Desktop용 stdio 모드
        mcp.run()
    else:
        # Railway / HTTP 서버 모드
        port = int(os.environ.get("PORT", 8000))
        uvicorn.run(app, host="0.0.0.0", port=port)
