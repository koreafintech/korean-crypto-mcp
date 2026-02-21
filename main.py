"""
Korean Crypto MCP Server v4
업비트 + 빗썸 + 김치프리미엄 + 텔레그램 알림봇
FastMCP (stdio) + FastAPI (HTTP) 듀얼 모드
"""

import asyncio
import os
import httpx
from datetime import datetime
from mcp.server.fastmcp import FastMCP
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn

# ── MCP 서버 ──────────────────────────────────────────
mcp = FastMCP("korean-crypto")

UPBIT     = "https://api.upbit.com/v1"
BITHUMB   = "https://api.bithumb.com/public"
COINGECKO = "https://api.coingecko.com/api/v3"
FX_URL    = "https://open.er-api.com/v6/latest/USD"

# 텔레그램 설정 (Railway 환경변수로 관리)
TG_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# 알림 임계값 (환경변수로 조정 가능)
ALERT_KIMCHI_HIGH  = float(os.environ.get("ALERT_KIMCHI_HIGH", "3.0"))
ALERT_KIMCHI_LOW   = float(os.environ.get("ALERT_KIMCHI_LOW", "-1.0"))
ALERT_COINS        = os.environ.get("ALERT_COINS", "BTC,ETH,XRP").split(",")
ALERT_INTERVAL_MIN = int(os.environ.get("ALERT_INTERVAL_MIN", "5"))

# 알림 중복 방지 상태
_last_alert: dict = {}
_monitor_task = None

# CoinGecko ID 매핑
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


# ── 유틸 ────────────────────────────────────────────
async def get(url, params=None):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(url, params=params)
        r.raise_for_status()
        return r.json()


async def send_telegram(message: str) -> bool:
    if not TG_TOKEN or not TG_CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(url, json={
                "chat_id": TG_CHAT_ID,
                "text": message,
                "parse_mode": "HTML"
            })
            return r.status_code == 200
    except Exception:
        return False


def _can_alert(key: str, cooldown_minutes: int = 60) -> bool:
    last = _last_alert.get(key)
    if last is None:
        return True
    return (datetime.now() - last).total_seconds() / 60 >= cooldown_minutes


# ── MCP 도구 ──────────────────────────────────────────
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
    lines = [f"📊 {market.upper()} 호가창\n", "  [매도]"]
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
    lines = [f"🕯️ {market.upper()} ({interval}) {count}개\n",
             f"{'날짜':<18} {'시가':>12} {'고가':>12} {'저가':>12} {'종가':>12}",
             "─" * 68]
    for c in data:
        dt = c.get("candle_date_time_kst", "")[:16]
        lines.append(f"{dt:<18} {c['opening_price']:>12,.0f} {c['high_price']:>12,.0f} "
                     f"{c['low_price']:>12,.0f} {c['trade_price']:>12,.0f}")
    return "\n".join(lines)


@mcp.tool()
async def get_kimchi_premium(coin: str) -> str:
    """김치프리미엄 계산. 업비트 vs CoinGecko(글로벌). 예: BTC"""
    coin = coin.upper()
    upbit_data = await get(f"{UPBIT}/ticker", params={"markets": f"KRW-{coin}"})
    krw_price = upbit_data[0]["trade_price"]

    cg_id = COINGECKO_IDS.get(coin)
    if not cg_id:
        try:
            search = await get(f"{COINGECKO}/search", params={"query": coin})
            coins_list = search.get("coins", [])
            if not coins_list:
                return f"CoinGecko에서 {coin} 정보를 찾을 수 없습니다."
            cg_id = coins_list[0]["id"]
        except Exception:
            return f"CoinGecko에서 {coin} 정보를 가져오지 못했습니다."

    try:
        cg_data = await get(f"{COINGECKO}/simple/price",
                            params={"ids": cg_id, "vs_currencies": "usd"})
        usd_price = cg_data[cg_id]["usd"]
    except Exception:
        return f"CoinGecko에서 {coin}({cg_id}) 가격을 가져오지 못했습니다."

    try:
        fx = await get(FX_URL)
        usd_krw = fx["rates"]["KRW"]
    except Exception:
        usd_krw = 1350.0

    krw_equiv = usd_price * usd_krw
    pct = (krw_price - krw_equiv) / krw_equiv * 100
    emoji = "🌶️" if pct > 3 else ("🔵" if pct < -1 else "⚖️")
    comment = ("한국 시장 고평가" if pct > 5 else "소폭 프리미엄" if pct > 2
               else "역프리미엄 — 저평가" if pct < -1 else "중립 구간")

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
    return (
        f"⚖️ {coin} 거래소 비교\n\n"
        f"  업비트: {upbit_price:>15,.0f} 원\n"
        f"  빗썸:   {bithumb_price:>15,.0f} 원\n"
        f"  ─────────────────────────────\n"
        f"  차이:   {diff:>+13,.0f} 원 ({pct:+.3f}%)\n"
        f"  → {'빗썸이 저렴' if diff > 0 else '업비트가 저렴'}"
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
    lines = [f"{title} (24h)\n",
             f"{'#':<3} {'코인':<8} {'현재가':>12} {'변동률':>8} {'거래대금':>10}",
             "─" * 47]
    for i, t in enumerate(top, 1):
        coin = t["market"].replace("KRW-", "")
        icon = "🟢" if t["change"] == "RISE" else "🔴"
        lines.append(f"{i:<3} {icon}{coin:<6} {t['trade_price']:>12,.0f} "
                     f"{t['signed_change_rate']*100:>+7.2f}% {t['acc_trade_price_24h']/1e8:>8.1f}억")
    return "\n".join(lines)


# ── 텔레그램 모니터링 ────────────────────────────────
async def _get_kimchi_pct(coin: str) -> float | None:
    try:
        coin = coin.upper()
        upbit_data = await get(f"{UPBIT}/ticker", params={"markets": f"KRW-{coin}"})
        krw_price = upbit_data[0]["trade_price"]
        cg_id = COINGECKO_IDS.get(coin)
        if not cg_id:
            return None
        cg_data = await get(f"{COINGECKO}/simple/price",
                            params={"ids": cg_id, "vs_currencies": "usd"})
        usd_price = cg_data[cg_id]["usd"]
        try:
            fx = await get(FX_URL)
            usd_krw = fx["rates"]["KRW"]
        except Exception:
            usd_krw = 1350.0
        return (krw_price - usd_price * usd_krw) / (usd_price * usd_krw) * 100
    except Exception:
        return None


async def monitor_loop():
    await asyncio.sleep(10)
    print(f"[Monitor] 시작 — {ALERT_INTERVAL_MIN}분 간격 | 코인: {ALERT_COINS}")
    while True:
        now_str = datetime.now().strftime("%H:%M")
        for coin in ALERT_COINS:
            coin = coin.strip().upper()
            pct = await _get_kimchi_pct(coin)
            if pct is None:
                continue

            if pct >= ALERT_KIMCHI_HIGH:
                key = f"{coin}_high"
                if _can_alert(key):
                    sent = await send_telegram(
                        f"🌶️ <b>김치프리미엄 알림</b> [{now_str}]\n\n"
                        f"코인: <b>{coin}</b>\n"
                        f"프리미엄: <b>{pct:+.2f}%</b> (기준: {ALERT_KIMCHI_HIGH}%↑)\n\n"
                        f"📌 한국 고평가 — 아비트리지 기회 가능"
                    )
                    if sent:
                        _last_alert[key] = datetime.now()
                        print(f"[Alert] {coin} 🌶️ {pct:+.2f}%")

            elif pct <= ALERT_KIMCHI_LOW:
                key = f"{coin}_low"
                if _can_alert(key):
                    sent = await send_telegram(
                        f"🔵 <b>역프리미엄 알림</b> [{now_str}]\n\n"
                        f"코인: <b>{coin}</b>\n"
                        f"역프리미엄: <b>{pct:+.2f}%</b> (기준: {ALERT_KIMCHI_LOW}%↓)\n\n"
                        f"📌 국내 저평가 — 해외→국내 기회 가능"
                    )
                    if sent:
                        _last_alert[key] = datetime.now()
                        print(f"[Alert] {coin} 🔵 {pct:+.2f}%")

        await asyncio.sleep(ALERT_INTERVAL_MIN * 60)


# ── FastAPI (lifespan) ───────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _monitor_task
    if TG_TOKEN and TG_CHAT_ID:
        _monitor_task = asyncio.create_task(monitor_loop())
        print("[Server] ✅ 텔레그램 모니터링 활성")
    else:
        print("[Server] ⚠️  텔레그램 미설정 — 환경변수 확인")
    yield
    if _monitor_task:
        _monitor_task.cancel()


app = FastAPI(
    title="Korean Crypto MCP API v4",
    description="업비트 실시간 데이터 + 텔레그램 알림봇",
    version="4.0.0",
    lifespan=lifespan
)

app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


# ── REST 엔드포인트 ──────────────────────────────────
@app.get("/")
async def root():
    return {
        "name": "korean-crypto-mcp", "version": "4.0.0", "status": "running",
        "telegram_enabled": bool(TG_TOKEN and TG_CHAT_ID),
        "alert_coins": ALERT_COINS,
        "alert_threshold": {"high": ALERT_KIMCHI_HIGH, "low": ALERT_KIMCHI_LOW},
        "tools": ["get_price","get_markets","get_orderbook","get_candles",
                  "get_kimchi_premium","compare_exchanges","get_top_movers"]
    }

@app.get("/health")
async def health():
    return {"status": "ok", "version": "4.0.0"}


# ── Smithery / MCP HTTP 엔드포인트 ──────────────────
@app.get("/mcp")
async def mcp_info():
    """Smithery MCP 엔드포인트 — 서버 정보 및 툴 목록"""
    return {
        "protocol": "mcp",
        "version": "2024-11-05",
        "name": "korean-crypto-mcp",
        "description": "한국 암호화폐 실시간 데이터 (업비트, 김치프리미엄, 빗썸)",
        "tools": [
            {"name": "get_price",
             "description": "업비트 실시간 현재가. 예: KRW-BTC",
             "inputSchema": {"type": "object", "properties": {
                 "market": {"type": "string", "description": "마켓 코드. 예: KRW-BTC"}},
                 "required": ["market"]}},
            {"name": "get_kimchi_premium",
             "description": "김치프리미엄 계산 (업비트 vs CoinGecko). 예: BTC",
             "inputSchema": {"type": "object", "properties": {
                 "coin": {"type": "string", "description": "코인 심볼. 예: BTC"}},
                 "required": ["coin"]}},
            {"name": "get_top_movers",
             "description": "24h 상승/하락 상위 코인",
             "inputSchema": {"type": "object", "properties": {
                 "direction": {"type": "string", "enum": ["up", "down"], "default": "up"},
                 "limit": {"type": "integer", "default": 10}}}},
            {"name": "compare_exchanges",
             "description": "업비트 vs 빗썸 가격 비교. 예: BTC",
             "inputSchema": {"type": "object", "properties": {
                 "coin": {"type": "string", "description": "코인 심볼. 예: BTC"}},
                 "required": ["coin"]}},
            {"name": "get_orderbook",
             "description": "업비트 호가창. 예: KRW-BTC",
             "inputSchema": {"type": "object", "properties": {
                 "market": {"type": "string", "description": "마켓 코드. 예: KRW-BTC"}},
                 "required": ["market"]}},
            {"name": "get_candles",
             "description": "업비트 캔들 데이터",
             "inputSchema": {"type": "object", "properties": {
                 "market": {"type": "string"},
                 "interval": {"type": "string", "default": "days"},
                 "count": {"type": "integer", "default": 10}},
                 "required": ["market"]}},
            {"name": "get_markets",
             "description": "업비트 마켓 목록",
             "inputSchema": {"type": "object", "properties": {
                 "quote": {"type": "string", "default": "KRW"}}}}
        ]
    }


@app.post("/mcp")
async def mcp_call(request: dict):
    """Smithery MCP 툴 호출 엔드포인트"""
    method = request.get("method", "")
    params = request.get("params", {})

    # tools/list
    if method == "tools/list":
        info = await mcp_info()
        return {"tools": info["tools"]}

    # tools/call
    if method == "tools/call":
        tool_name = params.get("name", "")
        args = params.get("arguments", {})
        try:
            dispatch = {
                "get_price":          lambda: get_price(args.get("market", "KRW-BTC")),
                "get_kimchi_premium": lambda: get_kimchi_premium(args.get("coin", "BTC")),
                "get_top_movers":     lambda: get_top_movers(args.get("direction", "up"),
                                                              int(args.get("limit", 10))),
                "compare_exchanges":  lambda: compare_exchanges(args.get("coin", "BTC")),
                "get_orderbook":      lambda: get_orderbook(args.get("market", "KRW-BTC")),
                "get_candles":        lambda: get_candles(args.get("market", "KRW-BTC"),
                                                           args.get("interval", "days"),
                                                           int(args.get("count", 10))),
                "get_markets":        lambda: get_markets(args.get("quote", "KRW")),
            }
            if tool_name not in dispatch:
                raise HTTPException(400, f"Unknown tool: {tool_name}")
            result = await dispatch[tool_name]()
            return {"content": [{"type": "text", "text": result}]}
        except Exception as e:
            raise HTTPException(500, str(e))

    raise HTTPException(400, f"Unknown method: {method}")

@app.get("/price/{market}")
async def api_price(market: str):
    return {"result": await get_price(market)}

@app.get("/markets")
async def api_markets(quote: str = "KRW"):
    return {"result": await get_markets(quote)}

@app.get("/orderbook/{market}")
async def api_orderbook(market: str):
    return {"result": await get_orderbook(market)}

@app.get("/candles/{market}")
async def api_candles(market: str, interval: str = "days", count: int = 10):
    return {"result": await get_candles(market, interval, count)}

@app.get("/kimchi/{coin}")
async def api_kimchi(coin: str):
    return {"result": await get_kimchi_premium(coin)}

@app.get("/compare/{coin}")
async def api_compare(coin: str):
    return {"result": await compare_exchanges(coin)}

@app.get("/top-movers")
async def api_top_movers(direction: str = "up", limit: int = 10):
    return {"result": await get_top_movers(direction, limit)}


# ── 텔레그램 관리 API ────────────────────────────────
@app.post("/alert/test")
async def alert_test():
    """텔레그램 연결 테스트"""
    if not TG_TOKEN or not TG_CHAT_ID:
        raise HTTPException(400, "TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID 미설정")
    msg = (
        "✅ <b>Korean Crypto Bot 연결 완료!</b>\n\n"
        f"모니터링 코인: {', '.join(ALERT_COINS)}\n"
        f"알림 기준: ≥ {ALERT_KIMCHI_HIGH}% 또는 ≤ {ALERT_KIMCHI_LOW}%\n"
        f"체크 주기: {ALERT_INTERVAL_MIN}분\n\n"
        "📡 Railway에서 24/7 모니터링 중!"
    )
    sent = await send_telegram(msg)
    return {"sent": sent, "message": msg}


@app.get("/alert/status")
async def alert_status():
    """알림 상태 확인"""
    return {
        "telegram_enabled": bool(TG_TOKEN and TG_CHAT_ID),
        "monitor_running": _monitor_task is not None and not _monitor_task.done(),
        "alert_coins": ALERT_COINS,
        "thresholds": {"high_pct": ALERT_KIMCHI_HIGH, "low_pct": ALERT_KIMCHI_LOW},
        "interval_minutes": ALERT_INTERVAL_MIN,
        "last_alerts": {k: v.strftime("%Y-%m-%d %H:%M:%S") for k, v in _last_alert.items()}
    }


@app.post("/alert/now/{coin}")
async def alert_now(coin: str):
    """즉시 김치프리미엄 체크 → 텔레그램 발송"""
    pct = await _get_kimchi_pct(coin.upper())
    if pct is None:
        raise HTTPException(400, f"{coin} 데이터 조회 실패")
    emoji = "🌶️" if pct > 3 else ("🔵" if pct < -1 else "⚖️")
    msg = (f"{emoji} <b>{coin.upper()} 즉시 리포트</b>\n"
           f"시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
           f"김치프리미엄: <b>{pct:+.2f}%</b>")
    sent = await send_telegram(msg)
    return {"sent": sent, "coin": coin.upper(), "kimchi_pct": round(pct, 2)}


# ── A2A ─────────────────────────────────────────────
@app.get("/.well-known/agent.json")
async def agent_card():
    base_url = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "localhost:8000")
    if not base_url.startswith("http"):
        base_url = f"https://{base_url}"
    return {
        "name": "korean-crypto-mcp", "version": "4.0.0",
        "description": "한국 암호화폐 실시간 데이터 + 텔레그램 알림 에이전트",
        "url": base_url,
        "capabilities": {"streaming": False, "pushNotifications": True},
        "skills": [
            {"id": "get_price", "name": "실시간 현재가", "inputModes": ["text"], "outputModes": ["text"]},
            {"id": "get_kimchi_premium", "name": "김치프리미엄", "inputModes": ["text"], "outputModes": ["text"]},
            {"id": "get_top_movers", "name": "상승/하락 TOP", "inputModes": ["text"], "outputModes": ["text"]},
            {"id": "compare_exchanges", "name": "거래소 비교", "inputModes": ["text"], "outputModes": ["text"]}
        ]
    }


@app.post("/tasks/send")
async def tasks_send(request: dict):
    try:
        parts = request.get("message", {}).get("parts", [])
        text = next((p.get("text", "") for p in parts if p.get("type") == "text"), "")
        skill_id = request.get("skillId", "get_price")
        meta = request.get("metadata", {})
        dispatch = {
            "get_price":          lambda: get_price(meta.get("market", text or "KRW-BTC")),
            "get_markets":        lambda: get_markets(meta.get("quote", "KRW")),
            "get_orderbook":      lambda: get_orderbook(meta.get("market", "KRW-BTC")),
            "get_candles":        lambda: get_candles(meta.get("market","KRW-BTC"),
                                                       meta.get("interval","days"), int(meta.get("count",10))),
            "get_kimchi_premium": lambda: get_kimchi_premium(meta.get("coin", text or "BTC")),
            "compare_exchanges":  lambda: compare_exchanges(meta.get("coin", text or "BTC")),
            "get_top_movers":     lambda: get_top_movers(meta.get("direction","up"), int(meta.get("limit",10))),
        }
        if skill_id not in dispatch:
            raise HTTPException(400, f"Unknown skill: {skill_id}")
        result = await dispatch[skill_id]()
        return {"id": request.get("id","task-1"), "status": {"state":"completed"},
                "artifacts": [{"parts": [{"type":"text","text":result}]}]}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── 실행 ────────────────────────────────────────────
if __name__ == "__main__":
    if os.environ.get("RUN_MODE") == "stdio":
        mcp.run()
    else:
        port = int(os.environ.get("PORT", 8000))
        uvicorn.run(app, host="0.0.0.0", port=port)
