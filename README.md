# RiskProbe (가칭)

투자 판단이 어떤 조건에서 틀릴 수 있는지 투자 전에 찾아 기록하고(Probe), 보유 중에는 그 조건에 가까워지는지 감시하며(Watch), 투자 후에는 그 판단이 왜, 어떤 종류로 틀렸는지 감사하는(Audit) AI Agent입니다. 「국부펀드 KIC, AI 에이전트 공모전」 출품용입니다.

- 계획·미정 사항: [`PLANS.md`](PLANS.md)
- P0 결과: [`docs/p0_findings.md`](docs/p0_findings.md), P1 결과: [`docs/p1_findings.md`](docs/p1_findings.md)
- 외부 자원 출처: [`SOURCES.md`](SOURCES.md)

## 실행

```bash
pip install -r requirements.txt
cp .env.example .env   # SEC_USER_AGENT 등 입력
python -m pytest -q    # 네트워크·키 불필요
python scripts/p0_check.py AES 2023-06-30 2025-06-30   # SEC 기준일 복원 점검
python scripts/p1_check.py AMT AES --as-of 2023-06-30 2025-06-30   # 지표·역산 점검
```

## 현재 구현 (P0~P1)

| 구성 | 위치 | 내용 |
|---|---|---|
| HTTP | `riskprobe/http.py` | 디스크 캐시, 호스트별 요청 간격, 키 제거 |
| SEC 수집 | `riskprobe/sources/sec.py` | 티커/CIK 조회, 공시 목록(접수 시각 포함), XBRL 값(공시별 버전) |
| 기준일 필터 | `riskprobe/pit.py` | 기준일 스냅샷, 정정 버전 이력, 재생용 공시 순서, 누수 검사 |
| 데이터 품질 | `riskprobe/quality.py` | 대상 기간 밖 이상 값 제외 |
| 지표 카탈로그 | `riskprobe/indicators.py` | 대체 태그, 분기 환산, TTM, 지표 12개, 부호 오류·재작성 혼합 차단 |
| 가정 원장 | `riskprobe/ledger.py` | 가정·기준값(출처)·상태 이력 |
| 역산 엔진 | `riskprobe/reverse.py` | 경로 템플릿 4개, 위험 등급(확률 대신 남은 여유) |
