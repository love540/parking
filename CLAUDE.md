# CLAUDE.md

이 레포는 두 가지 용도로 사용되는 보관소입니다.

## 레포 구조

```
parking/
├── index.html                      # 주차 할인권 계산기 (메인 앱)
├── ParkCalc.html                   # 동일 앱 (백업/이전 버전)
├── README.md                       # 주차 계산기 사용 설명
├── openalice-investment-process.md # OpenAlice 투자 프로세스 문서
└── openalice/
    └── data/
        ├── persona.md              # Alice 페르소나 정의
        ├── brain/heartbeat.md      # 워치리스트 자동 점검 지침
        └── config/                 # OpenAlice 실행 설정 (JSON 16개)
```

## 영역별 역할

### 1. 주차 할인권 계산기
- 순수 HTML/JS 단일 파일 앱, 외부 의존성 없음
- 계산 규칙: 방문권 1개(90분) + 할인권 최대 5개(30분/개), 초과 시 15분당 1,000원
- 수정 시 `index.html` 하나만 편집하면 됨

### 2. OpenAlice 설정
- [OpenAlice](https://github.com/TraderAlice/OpenAlice) 실행에 필요한 설정 파일 보관
- `openalice/data/` 를 OpenAlice 레포의 `data/` 디렉토리에 복사해서 사용
- AI 백엔드: Claude Sonnet 4.6 (`ai-provider-manager.json`)
- 대상: 미국 주식 10종목 워치리스트 (암호화폐 비활성화)

## 개발 브랜치
- 작업 브랜치: `claude/analyze-openalice-project-NWxuJ`
- 메인: `master` / `main`
