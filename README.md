# Korean Crypto MCP Server v3

업비트 + 빗썸 + 김치프리미엄 실시간 데이터 API

## 모드

| 모드 | 설명 | 실행 |
|------|------|------|
| `http` (기본) | Railway/A2A HTTP 서버 | `python main.py` |
| `stdio` | Claude Desktop MCP | `RUN_MODE=stdio python main.py` |

## 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| GET | `/` | 서버 정보 |
| GET | `/health` | 헬스체크 |
| GET | `/.well-known/agent.json` | A2A Agent Card |
| POST | `/tasks/send` | A2A 태스크 처리 |
| GET | `/price/{market}` | 현재가 (예: `KRW-BTC`) |
| GET | `/markets?quote=KRW` | 마켓 목록 |
| GET | `/orderbook/{market}` | 호가창 |
| GET | `/candles/{market}` | 캔들 데이터 |
| GET | `/kimchi/{coin}` | 김치프리미엄 |
| GET | `/compare/{coin}` | 업비트 vs 빗썸 비교 |
| GET | `/top-movers?direction=up` | 상승/하락 TOP |

## Railway 배포

1. GitHub에 push
2. Railway → New Project → GitHub Repo 연결
3. 자동 배포 완료

## Claude Desktop 설정 (로컬)

```json
{
  "mcpServers": {
    "korean-crypto": {
      "command": "python",
      "args": ["path/to/main.py"],
      "env": {
        "RUN_MODE": "stdio"
      }
    }
  }
}
```

## A2A 사용 예시

```bash
# 현재가 조회
curl https://your-app.railway.app/price/KRW-BTC

# 김치프리미엄
curl https://your-app.railway.app/kimchi/BTC

# A2A 태스크
curl -X POST https://your-app.railway.app/tasks/send \
  -H "Content-Type: application/json" \
  -d '{"id":"1","skillId":"get_kimchi_premium","metadata":{"coin":"BTC"}}'
```
