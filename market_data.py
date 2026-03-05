"""
금융 시장 데이터 수집 스크립트
- 오일 선물 (Brent, WTI Crude)
- 미국 국채 금리 2Y/5Y/10Y/20Y/30Y  ← FRED API (정확한 20년물 포함)
- 달러원 환율
- 미국 상장 한국 ETF
- 미국 증시 선물

의존성 설치:
    pip install yfinance fredapi tabulate

FRED API 키 (무료 발급 필수):
    https://fred.stlouisfed.org/docs/api/api_key.html
    export FRED_API_KEY="your_key"
"""

import io
import os
import subprocess
import sys
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from tabulate import tabulate

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
    src = "FRED + Yahoo Finance"
    print(f"  데이터 출처: {src}")
    print(f"{'━'*68}")

    # 국채 금리 (FRED)
    bond_rows, bond_raw = build_bond_rows()
    print_section("미국 국채 금리 (FRED DGS 시리즈)", bond_rows)
    print_analysis("미국 국채 금리 (FRED DGS 시리즈)", bond_raw)

    # 나머지 섹션 (yfinance)
    for section, items in TICKERS.items():
        unit = "KRW" if section == "달러원 환율" else ""
        rows, raw_data = [], []
        for ticker, name in items.items():
            data = fetch_quote(ticker)
            rows.append(format_row(name, ticker, data, unit))
            raw_data.append({"ticker": ticker, "name": name, "pct": data.get("pct")})
        print_section(section, rows)
        print_analysis(section, raw_data)

    print(f"\n{'━'*68}")
    print("  ※ 국채 금리: FRED DGS 시리즈 (Daily Treasury Constant Maturity Rate)")
    print("  ※ DGS20 = 20년물 정확한 수익률 (yfinance 미지원 → FRED 직접 조회)")
    print("  ※ 등락은 직전 영업일 대비 / FRED 기준일은 MM/DD 로 표시")
    print("  ※ 선물 가격은 최근 월물 기준 (yfinance)")
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
