"""
금융 시장 데이터 수집 스크립트
- 오일 선물 (Brent, WTI Crude)
- 원자재 선물 (금, 은, 구리, 천연가스)
- 미국 국채 금리 2Y/5Y/10Y/20Y/30Y  ← FRED API (정확한 20년물 포함)
- 달러원 환율
- 미국 상장 한국 ETF
- 미국 증시 선물
- CNN Fear & Greed Index
- CNBC 시장 뉴스 헤드라인

의존성 설치:
    pip install yfinance fredapi tabulate requests feedparser

FRED API 키 (무료 발급 필수):
    https://fred.stlouisfed.org/docs/api/api_key.html
    export FRED_API_KEY="your_key"
"""

import email.utils
import io
import os
import subprocess
import sys
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from tabulate import tabulate

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False

try:
    from fredapi import Fred
    HAS_FRED = True
except ImportError:
    HAS_FRED = False

FRED_API_KEY = os.getenv("FRED_API_KEY", "72f673fa6a935610cda0519a70979239")


# ── 티커 / 시리즈 정의 ──────────────────────────────────────────────────────────

TICKERS = {
    "오일 선물": {
        "BZ=F":  "Brent 원유 선물",
        "CL=F":  "WTI 원유 선물 (Crude Oil)",
    },
    "원자재 선물": {
        "GC=F":  "금 선물 (Gold)",
        "SI=F":  "은 선물 (Silver)",
        "HG=F":  "구리 선물 (Copper) ★경기선행",
        "NG=F":  "천연가스 선물 (Nat. Gas)",
    },
    "달러원 환율": {
        "KRW=X": "달러원 (USD/KRW)",
    },
    "미국 상장 한국 ETF": {
        "EWY":   "iShares MSCI South Korea ETF",
        "FLKR":  "Franklin FTSE South Korea ETF",
        "KORU":  "Direxion Daily MSCI South Korea Bull 3x",
        "HEWY":  "iShares Currency Hedged MSCI South Korea ETF",
    },
    "미국 증시 선물": {
        "ES=F":  "S&P 500 선물 (E-mini)",
        "NQ=F":  "나스닥 100 선물 (E-mini)",
        "YM=F":  "다우존스 선물 (E-mini)",
        "RTY=F": "러셀 2000 선물 (E-mini)",
    },
}

# FRED 국채 금리 시리즈 (DGS = Daily Treasury Constant Maturity Rate)
FRED_BOND_SERIES = {
    "DGS2":  "미 2년물 국채 금리  (FRED)",
    "DGS5":  "미 5년물 국채 금리  (FRED)",
    "DGS10": "미 10년물 국채 금리 (FRED)",
    "DGS20": "미 20년물 국채 금리 (FRED)",   # ← 정확한 20년물
    "DGS30": "미 30년물 국채 금리 (FRED)",
}

# FRED 실패 시 yfinance fallback
YF_BOND_FALLBACK = {
    "^IRX": "미 13주 T-Bill (yf)",
    "^FVX": "미 5년물 국채 금리 (yf)",
    "^TNX": "미 10년물 국채 금리 (yf)",
    "^TYX": "미 30년물 국채 금리 (yf)",
}


# ── FRED 데이터 수집 ───────────────────────────────────────────────────────────

def _get_fred_client():
    """fredapi Fred 인스턴스를 반환합니다. API 키 없으면 None."""
    if not HAS_FRED or not FRED_API_KEY:
        return None
    return Fred(api_key=FRED_API_KEY)


def fetch_fred_series(series_id: str) -> dict:
    """FRED에서 시계열을 가져와 최근값·전일값·등락을 반환합니다."""
    if not HAS_FRED:
        return {"price": None, "change": None, "pct": None,
                "error": "fredapi 미설치 (pip install fredapi)"}
    fred = _get_fred_client()
    if fred is None:
        reason = "FRED_API_KEY 미설정" if HAS_FRED else "fredapi 미설치"
        return {"price": None, "change": None, "pct": None, "error": reason}
    try:
        end   = datetime.today()
        start = end - timedelta(days=14)   # 휴일 고려해 여유 있게
        s = fred.get_series(series_id, observation_start=start,
                            observation_end=end)
        s = s.dropna()
        if s.empty:
            return {"price": None, "change": None, "pct": None,
                    "error": "데이터 없음"}

        price  = float(s.iloc[-1])
        prev   = float(s.iloc[-2]) if len(s) >= 2 else price
        change = price - prev
        pct    = (change / prev * 100) if prev else 0.0
        date_str = s.index[-1].strftime("%m/%d")
        return {"price": price, "prev": prev, "change": change,
                "pct": pct, "date": date_str}
    except Exception as e:
        return {"price": None, "change": None, "pct": None, "error": str(e)}


# ── yfinance 데이터 수집 ───────────────────────────────────────────────────────

def fetch_quote(ticker: str) -> dict:
    """yfinance에서 현재가·등락 정보를 반환합니다."""
    try:
        t    = yf.Ticker(ticker)
        info = t.fast_info
        price = info.last_price
        prev  = info.previous_close

        if price is None or prev is None:
            hist = t.history(period="2d")
            if hist.empty:
                return {"price": None, "change": None, "pct": None}
            price = hist["Close"].iloc[-1]
            prev  = hist["Close"].iloc[-2] if len(hist) >= 2 else price

        change = price - prev
        pct    = (change / prev * 100) if prev else 0.0
        return {"price": price, "prev": prev, "change": change, "pct": pct}
    except Exception as e:
        return {"price": None, "change": None, "pct": None, "error": str(e)}


# ── 행 포맷 ────────────────────────────────────────────────────────────────────

def format_row(name: str, ticker: str, data: dict, unit: str = "") -> list:
    if data.get("price") is None:
        err = data.get("error", "")
        return [name, ticker, "N/A", "N/A", "N/A", f"오류: {err}"[:30]]

    price  = data["price"]
    change = data["change"]
    pct    = data["pct"]
    ts     = data.get("date") or datetime.now().strftime("%H:%M")

    if unit == "%":
        p_str = f"{price:.3f}%"
        c_str = f"{change:+.3f}%p"
    elif unit == "KRW":
        p_str = f"₩{price:,.2f}"
        c_str = f"{change:+.2f}"
    else:
        p_str = f"{price:,.2f}"
        c_str = f"{change:+.2f}"

    arrow   = "▲" if change >= 0 else "▼"
    pct_str = f"{arrow} {abs(pct):.2f}%"
    return [name, ticker, p_str, c_str, pct_str, ts]


# ── 섹션 출력 ──────────────────────────────────────────────────────────────────

def print_section(title: str, rows: list):
    print(f"\n{'═'*68}")
    print(f"  {title}")
    print(f"{'═'*68}")
    headers = ["종목명", "티커/시리즈", "현재가", "등락", "등락률", "기준일시"]
    print(tabulate(rows, headers=headers, tablefmt="rounded_outline",
                   colalign=("left", "left", "right", "right", "right", "right")))


# ── 분석 가이드 ────────────────────────────────────────────────────────────────

# bad_direction: "up" = 상승이 부정적, "down" = 하락이 부정적
# focus_tickers: None 이면 전체 평균, 리스트면 해당 티커만 집계
ANALYSIS_RULES = {
    "미국 국채 금리 (FRED DGS 시리즈)": {
        "bad_direction": "up",
        "bad_msg":  "금리 상승 → 채권가 하락·달러 강세·위험자산 압박 ↑",
        "good_msg": "금리 하락 → 채권가 상승·유동성 완화·위험자산 선호 ↑",
        "focus_tickers": ["DGS10", "DGS20", "^TNX", "^TYX"],  # 중장기 위주
    },
    "오일 선물": {
        "bad_direction": "up",
        "bad_msg":  "유가 상승 → 인플레 압력·기업 원가 증가·소비 위축 우려",
        "good_msg": "유가 하락 → 인플레 완화·기업 비용 감소·소비 여력 개선",
        "focus_tickers": None,
    },
    "달러원 환율": {
        "bad_direction": "up",
        "bad_msg":  "원화 약세 → 수입물가 상승·외국인 매도 압력 증가",
        "good_msg": "원화 강세 → 수입물가 안정·외국인 유입 환경 우호",
        "focus_tickers": None,
    },
    "미국 상장 한국 ETF": {
        "bad_direction": "down",
        "bad_msg":  "ETF 하락 → 한국 증시 약세·외국인 순매도 신호",
        "good_msg": "ETF 상승 → 한국 증시 강세·외국인 순매수 신호",
        "focus_tickers": ["EWY", "FLKR"],  # 레버리지(KORU) 제외
    },
    "미국 증시 선물": {
        "bad_direction": "down",
        "bad_msg":  "선물 하락 → 미국 증시 약세 개장 예상·리스크오프",
        "good_msg": "선물 상승 → 미국 증시 강세 개장 예상·리스크온",
        "focus_tickers": ["ES=F", "NQ=F"],  # S&P·나스닥 위주
    },
    "원자재 선물": {
        "bad_direction": "up",
        "bad_msg":  "원자재 상승 → 인플레 자극·제조업 비용 압박 (구리↑ = 수요 회복 양면)",
        "good_msg": "원자재 하락 → 인플레 완화·제조업 비용 감소 (구리↓ = 경기둔화 주의)",
        "focus_tickers": ["GC=F", "HG=F"],  # 금(안전자산)·구리(경기선행) 위주
    },
}


def print_analysis(section_title: str, raw_data: list):
    """섹션 데이터를 분석해 방향·판단·가이드를 출력합니다."""
    rule = ANALYSIS_RULES.get(section_title)
    if not rule:
        return

    focus   = rule["focus_tickers"]
    valid   = [d for d in raw_data if d["pct"] is not None]
    targets = [d for d in valid if d["ticker"] in focus] if focus else valid
    if not targets:
        targets = valid  # focus 매칭 없으면 전체 사용
    if not targets:
        return

    avg_pct = sum(d["pct"] for d in targets) / len(targets)
    bad_up  = rule["bad_direction"] == "up"
    is_bad  = (avg_pct > 0) if bad_up else (avg_pct < 0)

    arrow   = "▲" if avg_pct >= 0 else "▼"
    verdict = "⚠  부정적" if is_bad else "✓  긍정적"
    msg     = rule["bad_msg"] if is_bad else rule["good_msg"]
    detail  = "  /  ".join(
        f"{d['name']} {'▲' if d['pct'] >= 0 else '▼'}{abs(d['pct']):.2f}%"
        for d in targets
    )

    print(f"\n  [ 분석 ] {detail}")
    print(f"  [ 판단 ] 평균 {arrow}{abs(avg_pct):.2f}% → {verdict}")
    print(f"  [ 가이드 ] {msg}")


# ── CNN Fear & Greed Index ─────────────────────────────────────────────────────

FGI_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"

# (min, max, 한국어 레이블, 한국 증시 해석)
FGI_LEVELS = [
    (0,  24, "극도의 공포 (Extreme Fear)", "⚠  외국인 극단적 이탈 가능·변동성 급등 주의"),
    (25, 44, "공포 (Fear)",               "⚠  미국 약세심리·외국인 매도 압력"),
    (45, 55, "중립 (Neutral)",             "✓  방향성 모호·개별 재료 중심"),
    (56, 74, "탐욕 (Greed)",               "✓  리스크온·외국인 한국 증시 유입 우호"),
    (75, 100, "극도의 탐욕 (Extreme Greed)", "⚠  과열 구간·단기 조정 가능성 경계"),
]


def fetch_fear_greed() -> dict:
    """CNN Fear & Greed Index 비공식 엔드포인트에서 현재 점수를 가져옵니다."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; market-monitor/1.0)"}
        r = requests.get(FGI_URL, headers=headers, timeout=10)
        r.raise_for_status()
        j = r.json()
        fg = j["fear_and_greed"]
        return {
            "score":    round(fg["score"], 1),
            "prev":     round(fg.get("previous_close", fg["score"]), 1),
            "rating":   fg.get("rating", ""),
            "updated":  fg.get("timestamp", ""),
        }
    except Exception as e:
        return {"error": str(e)}


def print_fear_greed(data: dict):
    print(f"\n{'═'*68}")
    print(f"  CNN Fear & Greed Index")
    print(f"{'═'*68}")

    if "error" in data:
        print(f"  오류: {data['error'][:60]}")
        return

    score  = data["score"]
    prev   = data["prev"]
    change = round(score - prev, 1)
    arrow  = "▲" if change >= 0 else "▼"

    label, guide = "알 수 없음", ""
    for lo, hi, lbl, gd in FGI_LEVELS:
        if lo <= score <= hi:
            label, guide = lbl, gd
            break

    # 30칸 게이지 바
    bar_len = 30
    filled  = max(0, min(bar_len, int(score / 100 * bar_len)))
    bar     = "█" * filled + "░" * (bar_len - filled)

    print(f"  현재 점수 : {score}  ({arrow}{abs(change)} vs 전일  |  전일: {prev})")
    print(f"  상태     : {label}")
    print(f"  게이지   : [공포] [{bar}] [탐욕]")
    print(f"\n  [ 판단 ] {guide}")


# ── CNBC RSS 뉴스 헤드라인 ─────────────────────────────────────────────────────

# CNBC 공개 RSS 피드 (Markets / Economy / Finance)
NEWS_FEEDS = [
    ("CNBC Markets",  "https://www.cnbc.com/id/15839135/device/rss/rss.html"),
    ("CNBC Economy",  "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
    ("CNBC Finance",  "https://www.cnbc.com/id/10000664/device/rss/rss.html"),
]
NEWS_COUNT = 7   # 출력할 최신 헤드라인 수


def fetch_news() -> list:
    """CNBC RSS에서 최신 헤드라인을 가져옵니다."""
    if not HAS_FEEDPARSER:
        return [{"error": "feedparser 미설치 (pip install feedparser)"}]

    items = []
    for source, url in NEWS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                pub_str = ""
                raw_pub = entry.get("published", "")
                if raw_pub:
                    try:
                        dt = email.utils.parsedate_to_datetime(raw_pub)
                        pub_str = dt.strftime("%m/%d %H:%M")
                    except Exception:
                        pub_str = raw_pub[:16]
                items.append({
                    "source":  source,
                    "title":   entry.get("title", "(제목 없음)"),
                    "time":    pub_str,
                })
        except Exception:
            pass

    # 최신순 정렬 후 상위 N개
    items.sort(key=lambda x: x["time"], reverse=True)
    return items[:NEWS_COUNT]


def print_news(items: list):
    print(f"\n{'═'*68}")
    print(f"  글로벌 금융 뉴스 헤드라인 (CNBC RSS)")
    print(f"{'═'*68}")

    if not items:
        print("  뉴스를 불러올 수 없습니다.")
        return
    if "error" in items[0]:
        print(f"  오류: {items[0]['error']}")
        return

    for i, item in enumerate(items, 1):
        title = item["title"]
        if len(title) > 60:
            title = title[:57] + "..."
        print(f"  {i}. [{item['time']}] {title}")
        print(f"     └ {item['source']}")


# ── 국채 금리 섹션 (FRED 우선, fallback yfinance) ────────────────────────────

def build_bond_rows() -> tuple:
    rows, raw_data = [], []
    used_fred = False

    for series_id, name in FRED_BOND_SERIES.items():
        data = fetch_fred_series(series_id)
        rows.append(format_row(name, series_id, data, unit="%"))
        raw_data.append({"ticker": series_id, "name": name.strip(), "pct": data.get("pct")})
        if data.get("price") is not None:
            used_fred = True

    # FRED 전부 실패 시 yfinance fallback
    if not used_fred:
        print("  [!] FRED 수집 실패 → yfinance fallback 사용")
        rows.clear()
        raw_data.clear()
        for ticker, name in YF_BOND_FALLBACK.items():
            data = fetch_quote(ticker)
            rows.append(format_row(name, ticker, data, unit="%"))
            raw_data.append({"ticker": ticker, "name": name, "pct": data.get("pct")})

    return rows, raw_data


# ── 메인 ───────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'━'*68}")
    print(f"  글로벌 금융 시장 데이터  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  데이터 출처: FRED + Yahoo Finance + CNN + CNBC RSS")
    print(f"{'━'*68}")

    # ① CNN Fear & Greed Index (맨 위 → 전체 시장 심리 파악)
    print_fear_greed(fetch_fear_greed())

    # ② 국채 금리 (FRED)
    bond_rows, bond_raw = build_bond_rows()
    print_section("미국 국채 금리 (FRED DGS 시리즈)", bond_rows)
    print_analysis("미국 국채 금리 (FRED DGS 시리즈)", bond_raw)

    # ③ 나머지 섹션 (yfinance)
    for section, items in TICKERS.items():
        unit = "KRW" if section == "달러원 환율" else ""
        rows, raw_data = [], []
        for ticker, name in items.items():
            data = fetch_quote(ticker)
            rows.append(format_row(name, ticker, data, unit))
            raw_data.append({"ticker": ticker, "name": name, "pct": data.get("pct")})
        print_section(section, rows)
        print_analysis(section, raw_data)

    # ④ 뉴스 헤드라인 (맨 아래)
    print_news(fetch_news())

    print(f"\n{'━'*68}")
    print("  ※ 국채 금리: FRED DGS 시리즈 (Daily Treasury Constant Maturity Rate)")
    print("  ※ DGS20 = 20년물 정확한 수익률 (yfinance 미지원 → FRED 직접 조회)")
    print("  ※ 등락은 직전 영업일 대비 / FRED 기준일은 MM/DD 로 표시")
    print("  ※ 선물 가격은 최근 월물 기준 (yfinance)")
    print("  ※ Fear & Greed: CNN 비공식 API / 뉴스: CNBC RSS (무료·공개)")
    print(f"{'━'*68}\n")


def copy_to_clipboard(text: str):
    """출력 결과를 클립보드에 복사합니다 (macOS: pbcopy)."""
    try:
        subprocess.run("pbcopy", input=text.encode(), check=True)
        print("  ✓ 결과가 클립보드에 복사되었습니다.")
    except Exception:
        pass


if __name__ == "__main__":
    buf = io.StringIO()
    tee = sys.stdout
    sys.stdout = buf

    main()

    output = buf.getvalue()
    sys.stdout = tee
    print(output, end="")
    copy_to_clipboard(output)
