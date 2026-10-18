# RiskProbe (가칭)

투자 판단이 어떤 조건에서 틀릴 수 있는지 투자 전에 찾아 기록하고(Probe), 보유 중에는 그 조건에 가까워지는지 감시하며(Watch), 투자 후에는 그 판단이 왜, 어떤 종류로 틀렸는지 감사하는(Audit) AI Agent입니다. 「국부펀드 KIC, AI 에이전트 공모전」 출품용입니다.

- 계획·미정 사항: [`PLANS.md`](PLANS.md)
- 파이프라인 그림: [`docs/images/pipeline.png`](docs/images/pipeline.png)
- P0 결과: [`docs/p0_findings.md`](docs/p0_findings.md), P1 결과: [`docs/p1_findings.md`](docs/p1_findings.md)
- 외부 자원 출처: [`SOURCES.md`](SOURCES.md)

## 실행

```bash
pip install -r requirements.txt
cp .env.example .env   # SEC_USER_AGENT 등 입력
python -m pytest -q    # 네트워크·키 불필요
python scripts/p0_check.py AES 2023-06-30 2025-06-30   # SEC 기준일 복원 점검
python scripts/p1_check.py AMT AES --as-of 2023-06-30 2025-06-30   # 지표·역산 점검
python scripts/review.py HE --t0 2023-06-30 --end 2025-06-30   # 통합 검토: 입력 하나 → 판단 카드 하나
python scripts/probe.py AES --as-of 2025-06-30   # Probe 위험 보고서 → reports/, 가정 원장 → data/ledger/
python scripts/thesis.py 1603145 --as-of 2023-06-30 --name XPLR_guidance   # 기업 전망으로 원장 만들기
python scripts/audit.py data/ledger/HE_2023-06-30.json --end 2025-06-30   # Audit 감사 보고서
python scripts/watch.py --since 2023-06-30 --until 2023-09-30 --rate-bp 100 --ebitda-pct -20   # Watch 감시 브리프 + 사건 시나리오
streamlit run app/streamlit_app.py   # 앱 (배포: docs/deploy.md)
```

## 현재 구현 (P0~P4)

| 구성 | 위치 | 내용 |
|---|---|---|
| HTTP | `riskprobe/http.py` | 디스크 캐시, 호스트별 요청 간격, 키 제거 |
| SEC 수집 | `riskprobe/sources/sec.py` | 회사 이름·티커·CIK 검색, 외국 기업·금융업 경고, 공시 목록(접수 시각 포함), XBRL 값(공시별 버전) |
| DART 수집 | `riskprobe/sources/dart.py` | 한국 상장사 이름(한·영)·종목코드 검색, 정기보고서별 재무제표(정정일 기준), 차입금·감가상각비 합산, 주요사항보고서·거래소공시 제목 규칙 |
| 소스 선택 | `riskprobe/sources/market.py` | `KR:종목코드`·한글 이름 → DART, 그 밖 → SEC. 통화별 금리(SOFR·CD 91일) |
| 금리 | `riskprobe/sources/rates.py` | SOFR·미 국채 10년(키 불필요), 한국은행 ECOS CD 91일·국고채 3년(키 필요) |
| 기준일 필터 | `riskprobe/pit.py` | 기준일 스냅샷, 정정 버전 이력, 재생용 공시 순서, 누수 검사 |
| 데이터 품질 | `riskprobe/quality.py` | 대상 기간 밖 이상 값 제외 |
| 지표 카탈로그 | `riskprobe/indicators.py` | 대체 태그, 분기 환산, TTM, 지표 12개, 부호 오류·재작성 혼합 차단 |
| 가정 원장 | `riskprobe/ledger.py` | 가정·기준값(출처)·상태 이력 |
| 역산 엔진 | `riskprobe/reverse.py` | 경로 템플릿 4개, 위험 등급(확률 대신 남은 여유) |
| LLM | `riskprobe/llm.py` | Gemini/Claude 구조화 호출, 캐시, 재시도. 키가 없으면 해당 단계만 생략 |
| 공시 문단 선별 | `riskprobe/text.py` | 10-K HTML → 문단, 키워드로 약 1/10만 남김 |
| 공시 추출 | `riskprobe/extract.py` | LLM 제안 → 원문 인용 확인 → 숫자는 코드가 파싱 |
| Probe | `riskprobe/probe.py` | 기준일 데이터 → 추출 → 경로별 역산(공시/조정 EBITDA, 기본 규칙/공시 약정) → 가정 원장 |
| 보고서 | `riskprobe/report.py` | 코드 판정 결론 + 숫자 없는 LLM 해석(감사) + 출처·한계 |
| 반증 탐색 | `riskprobe/counter.py` | 지표 규칙·1년 추세·최근 수시공시·연차보고서 위험 서술 |
| 수시공시 분류 | `riskprobe/events.py` | 8-K 항목 규칙 + 7.01/8.01 본문·EX-99 키워드 규칙 |
| 전망·메모 가설 | `riskprobe/guidance.py` | 실적 발표 전망 추출(인용 검증), 원장 변환, 이후 발표의 재언급 추적 |
| Audit | `riskprobe/audit.py`, `audit_report.py` | 공시일별 재생, 상태 판정, 실패 유형, 가정 무리 신호, 수시공시 선행 시간 |
| 앱 | `app/streamlit_app.py` | Probe·Audit·데이터 탭, 데모 버튼 |
| 금리 | `riskprobe/sources/rates.py` | SOFR(뉴욕 연준), 국채 10년물(연준 H.15) |
| Watch | `riskprobe/watch.py`, `watch_report.py`, `.github/workflows/watch.yml` | 기간 중 정기공시 재평가·수시공시·금리 트리거, 사건 시나리오, 평일 매일 실행·Issue 경보 |
| 통합 검토 | `riskprobe/lifecycle.py`, `lifecycle_report.py`, `scripts/review.py` | 기준일 Probe + 한 번의 재생 + 금리·시나리오 → 종합 판정(재검토 필요/주의/유지)과 판단 카드. 앱 메인 탭 |
