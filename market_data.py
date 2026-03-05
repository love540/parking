"""
금융 시장 데이터 수집 스크립트
- 오일 선물 (Brent, WTI Crude)
- 미국 중장기 국채 금리 (10년, 20년)
- 달러원 환율
- 미국 상장 한국 ETF
- 미국 증시 선물

의존성 설치: pip install yfinance requests pandas tabulate
"""

import yfinance as yf
import pandas as pd
from datetime import datetime
from tabulate import tabulate


# ── 티커 정의 ────────────────────────────────────────────────────────────────

TICKERS = {
    "오일 선물": {
        "BZ=F":  "Brent 원유 선물",
        "CL=F":  "WTI 원유 선물 (Crude Oil)",
    },
    "미국 국채 금리": {
        "^TNX":  "미 10년물 국채 금리",
        "^TYX":  "미 30년물 국채 금리",
        "^FVX":  "미 5년물 국채 금리",
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

# 20년물은 ETF(TLT)로 근사 — Treasury ETF yield 직접 지원 없음
# 대신 yfinance 의 ^TYX(30년)와 함께 CBOT 20년 선물로 보완
BOND_EXTRA = {
    "ZT=F":  "2년 국채 선물",
    "ZN=F":  "10년 국채 선물 (CBOT)",
    "ZB=F":  "30년 국채 선물 (CBOT)",
}


# ── 데이터 수집 ───────────────────────────────────────────────────────────────

def fetch_quote(ticker: str) -> dict:
    """단일 티커의 현재가·등락 정보를 반환합니다."""
    try:
        t = yf.Ticker(ticker)
        info = t.fast_info          # 빠른 기본 정보
        price = info.last_price
        prev  = info.previous_close

        if price is None or prev is None:
            # fast_info 가 없을 때 history 로 대체
            hist = t.history(period="2d")
            if hist.empty:
                return {"price": None, "prev": None, "change": None, "pct": None}
            price = hist["Close"].iloc[-1]
            prev  = hist["Close"].iloc[-2] if len(hist) >= 2 else price

        change = price - prev
        pct    = (change / prev * 100) if prev else 0.0
        return {"price": price, "prev": prev, "change": change, "pct": pct}
    except Exception as e:
        return {"price": None, "prev": None, "change": None, "pct": None, "error": str(e)}


def format_row(name: str, ticker: str, data: dict, unit: str = "") -> list:
    """테이블 한 행을 포맷합니다."""
    if data["price"] is None:
        return [name, ticker, "N/A", "N/A", "N/A", "N/A"]

    price  = data["price"]
    change = data["change"]
    pct    = data["pct"]

    # 숫자 포맷
    if unit == "%":          # 금리는 % 표시
        p_str = f"{price:.3f}%"
        c_str = f"{change:+.3f}%p"
    elif unit == "KRW":      # 환율
        p_str = f"₩{price:,.2f}"
        c_str = f"{change:+.2f}"
    else:
        p_str = f"{price:,.2f}"
        c_str = f"{change:+.2f}"

    arrow = "▲" if change >= 0 else "▼"
    pct_str = f"{arrow} {abs(pct):.2f}%"

    return [name, ticker, p_str, c_str, pct_str, datetime.now().strftime("%H:%M:%S")]


# ── 메인 출력 ─────────────────────────────────────────────────────────────────

def print_section(title: str, rows: list[list]):
    print(f"\n{'═'*64}")
    print(f"  {title}")
    print(f"{'═'*64}")
    headers = ["종목명", "티커", "현재가", "등락", "등락률", "기준시각"]
    print(tabulate(rows, headers=headers, tablefmt="rounded_outline",
                   colalign=("left", "left", "right", "right", "right", "right")))


def main():
    print(f"\n{'━'*64}")
    print(f"  글로벌 금융 시장 데이터  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'━'*64}")

    for section, items in TICKERS.items():
        rows = []

        # 국채 금리 섹션에 CBOT 선물 추가
        if section == "미국 국채 금리":
            items = {**items, **BOND_EXTRA}

        # 단위 결정
        unit = "%" if section == "미국 국채 금리" else \
               "KRW" if section == "달러원 환율" else ""

        for ticker, name in items.items():
            data = fetch_quote(ticker)
            rows.append(format_row(name, ticker, data, unit))

        print_section(section, rows)

    print(f"\n{'━'*64}")
    print("  ※ 데이터 출처: Yahoo Finance (yfinance)")
    print("  ※ 국채 금리(^TNX, ^TYX)는 % 단위 수익률입니다.")
    print("  ※ 선물 가격은 최근 월물 기준입니다.")
    print(f"{'━'*64}\n")


if __name__ == "__main__":
    main()
