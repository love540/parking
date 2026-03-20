"""
Gemini 기반 글로벌 시장 데이터 분석 스크립트
─────────────────────────────────────────────
market_data.py 에서 수집한 시장 데이터를 Google Gemini API에 전달해
한국 투자자 관점의 종합 분석 리포트를 생성합니다.

의존성 설치:
    pip install yfinance fredapi tabulate requests feedparser google-generativeai

Google Gemini API 키 (무료 발급):
    https://aistudio.google.com/app/apikey
    export GEMINI_API_KEY="your_key"
"""

import io
import os
import subprocess
import sys
from datetime import datetime

import google.generativeai as genai

# market_data.py 의 수집 함수 재사용
from market_data import (
    FRED_BOND_SERIES,
    TICKERS,
    YF_BOND_FALLBACK,
    build_bond_rows,
    fetch_fear_greed,
    fetch_fred_series,
    fetch_news,
    fetch_quote,
)

# ── Gemini 클라이언트 설정 ─────────────────────────────────────────────────────

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL   = "gemini-2.0-flash"   # 빠른 추론 · 무료 티어 지원


def _get_gemini_model():
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY 환경변수가 설정되지 않았습니다.\n"
            "  export GEMINI_API_KEY='your_key'\n"
            "  키 발급: https://aistudio.google.com/app/apikey"
        )
    genai.configure(api_key=GEMINI_API_KEY)
    return genai.GenerativeModel(GEMINI_MODEL)


# ── 시장 데이터 수집 ───────────────────────────────────────────────────────────

def collect_all_data() -> dict:
    """모든 시장 데이터를 수집해 구조화된 dict 로 반환합니다."""
    print("  [데이터 수집 중] ", end="", flush=True)

    # ① Fear & Greed
    print("Fear&Greed", end=" ", flush=True)
    fgi = fetch_fear_greed()

    # ② 국채 금리 (FRED)
    print("| 국채금리", end=" ", flush=True)
    bonds = {}
    used_fred = False
    for sid, name in FRED_BOND_SERIES.items():
        d = fetch_fred_series(sid)
        bonds[sid] = {"name": name.strip(), **d}
        if d.get("price") is not None:
            used_fred = True
    if not used_fred:
        for ticker, name in YF_BOND_FALLBACK.items():
            d = fetch_quote(ticker)
            bonds[ticker] = {"name": name, **d}

    # ③ yfinance 선물·환율·ETF
    prices = {}
    for section, items in TICKERS.items():
        print(f"| {section}", end=" ", flush=True)
        prices[section] = {}
        for ticker, name in items.items():
            d = fetch_quote(ticker)
            prices[section][ticker] = {"name": name, **d}

    # ④ 뉴스 헤드라인
    print("| 뉴스", flush=True)
    news = fetch_news()

    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "fear_greed": fgi,
        "bonds": bonds,
        "prices": prices,
        "news": news,
    }


# ── 프롬프트 빌더 ──────────────────────────────────────────────────────────────

def _fmt_pct(d: dict) -> str:
    pct = d.get("pct")
    if pct is None:
        return "N/A"
    arrow = "▲" if pct >= 0 else "▼"
    return f"{arrow}{abs(pct):.2f}%"


def build_prompt(data: dict) -> str:
    lines = [
        "당신은 글로벌 금융 시장 전문 애널리스트입니다.",
        "아래 실시간 시장 데이터를 분석해 **한국 주식 투자자** 관점의 종합 리포트를 작성하세요.",
        f"\n=== 수집 시각: {data['timestamp']} ===\n",
    ]

    # ① Fear & Greed
    fgi = data["fear_greed"]
    if "error" not in fgi:
        lines.append(
            f"[CNN Fear & Greed Index]\n"
            f"  현재 점수: {fgi['score']} (전일: {fgi['prev']}, "
            f"변화: {fgi['score'] - fgi['prev']:+.1f})\n"
            f"  등급: {fgi.get('rating', '')}\n"
        )
    else:
        lines.append(f"[CNN Fear & Greed Index] 수집 실패: {fgi['error']}\n")

    # ② 국채 금리
    lines.append("[미국 국채 금리]")
    for sid, d in data["bonds"].items():
        if d.get("price") is not None:
            lines.append(
                f"  {d['name']}: {d['price']:.3f}%  ({_fmt_pct(d)})"
            )
        else:
            lines.append(f"  {d['name']}: N/A")
    lines.append("")

    # ③ 선물·환율·ETF
    for section, items in data["prices"].items():
        lines.append(f"[{section}]")
        for ticker, d in items.items():
            if d.get("price") is not None:
                lines.append(
                    f"  {d['name']} ({ticker}): {d['price']:,.2f}  ({_fmt_pct(d)})"
                )
            else:
                lines.append(f"  {d['name']} ({ticker}): N/A")
        lines.append("")

    # ④ 뉴스
    lines.append("[주요 뉴스 헤드라인 (CNBC)]")
    for item in data["news"]:
        if "error" not in item:
            lines.append(f"  [{item['time']}] {item['title']}")
    lines.append("")

    # ── 분석 요청 지시 ─────────────────────────────────────────────────────────
    lines += [
        "─" * 60,
        "위 데이터를 바탕으로 다음 구조로 한국어 리포트를 작성하세요.\n",
        "## 1. 글로벌 시장 심리 요약 (3~5문장)",
        "   Fear & Greed 지수, 국채 금리, 달러 방향성을 종합해 현재 투자 심리를 설명하세요.\n",
        "## 2. 섹터별 핵심 시사점",
        "   ### 2-1. 미국 증시 (S&P500·나스닥 선물 기반)",
        "   ### 2-2. 원자재 (금·구리·유가·천연가스 — 인플레·경기 신호)",
        "   ### 2-3. 한국 증시 영향 (환율·외국인·EWY/FLKR ETF 흐름)\n",
        "## 3. 금리 곡선 분석",
        "   2Y-10Y 스프레드, 20Y-30Y 구간을 해석하고 채권·주식 자산배분 시사점을 설명하세요.\n",
        "## 4. 오늘의 핵심 리스크 & 기회 (bullet 3개씩)",
        "   - 리스크 요인 3가지",
        "   - 기회 요인 3가지\n",
        "## 5. 한국 투자자 전략 제언 (단기 1주, 중기 1개월)",
        "   KOSPI/KOSDAQ 방향성, 섹터 추천, ETF(EWY/FLKR/KORU) 포지션 가이드\n",
        "## 6. 주요 이벤트 모니터링 포인트",
        "   뉴스 헤드라인 및 지표 흐름에서 추가로 지켜봐야 할 사항\n",
        "※ 숫자를 구체적으로 인용하고, 투자 결정의 근거를 명확히 제시하세요.",
        "※ 예측이 불확실한 경우 반드시 '불확실성 높음' 또는 주의 문구를 포함하세요.",
    ]

    return "\n".join(lines)


# ── Gemini 호출 ────────────────────────────────────────────────────────────────

def analyze_with_gemini(prompt: str) -> str:
    """Gemini 모델에 프롬프트를 전달해 분석 텍스트를 반환합니다."""
    model = _get_gemini_model()
    response = model.generate_content(
        prompt,
        generation_config=genai.types.GenerationConfig(
            temperature=0.3,      # 사실 기반·재현성 중시
            max_output_tokens=2048,
        ),
    )
    return response.text


# ── 출력 ───────────────────────────────────────────────────────────────────────

def print_report(analysis: str, timestamp: str):
    sep = "━" * 68
    print(f"\n{sep}")
    print(f"  Gemini 시장 분석 리포트  |  {timestamp}")
    print(f"  모델: {GEMINI_MODEL}")
    print(sep)
    print()
    print(analysis)
    print(f"\n{sep}")
    print("  ※ 본 리포트는 AI 생성 분석으로 투자 권유가 아닙니다.")
    print(f"{sep}\n")


def copy_to_clipboard(text: str):
    """결과를 클립보드에 복사합니다 (macOS: pbcopy)."""
    try:
        import subprocess
        subprocess.run("pbcopy", input=text.encode(), check=True)
        print("  ✓ 결과가 클립보드에 복사되었습니다.")
    except Exception:
        pass


# ── 메인 ───────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'━'*68}")
    print(f"  Gemini 글로벌 시장 분석  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'━'*68}")

    # 1. 데이터 수집
    data = collect_all_data()

    # 2. 프롬프트 구성
    print("\n  [프롬프트 구성 중...]")
    prompt = build_prompt(data)

    # 3. Gemini 분석
    print(f"  [Gemini ({GEMINI_MODEL}) 분석 요청 중...]\n")
    try:
        analysis = analyze_with_gemini(prompt)
    except RuntimeError as e:
        print(f"\n  오류: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n  Gemini API 오류: {e}")
        sys.exit(1)

    # 4. 출력 (tee → 클립보드)
    buf = io.StringIO()
    tee = sys.stdout
    sys.stdout = buf

    print_report(analysis, data["timestamp"])

    output = buf.getvalue()
    sys.stdout = tee
    print(output, end="")
    copy_to_clipboard(output)


if __name__ == "__main__":
    main()
