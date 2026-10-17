반말로 말 할 것.

# 작업 원칙 (최우선)

1. **애매하거나 모르는 부분은 반드시 질문한다.** 작업 중 판단이 애매하거나 모르는 부분이 생기면 추측으로 진행하지 말고 사용자에게 먼저 질문한다.
2. **최소 비용으로 최고 성능을 내도록 설계한다.**
   - 결정적 코드(스크립트, 규칙, 계산)로 해결되는 일은 코드로 처리하고, LLM 호출은 꼭 필요한 곳에만 쓴다.
   - 무료·오픈소스 도구와 무료 API 등급을 우선 검토한다.
   - 설계안을 낼 때는 비용과 성능의 트레이드오프를 함께 밝힌다.

3. **파이프라인 이미지는 사용자가 요청할 때만 만든다.** 기능을 바꿔도 그림을 알아서 다시 그리지 않는다.

# 프로젝트 메모 (RiskProbe, 가칭)

- 계획·미정 사항: `PLANS.md`. P0 결과: `docs/p0_findings.md`. 외부 자원 출처: `SOURCES.md`
- 테스트: `python -m pytest -q` (네트워크·API 키 불필요, `tests/fakes.py`의 가짜 HTTP 사용)
- 통합 검토(메인 흐름): `python scripts/review.py HE --t0 2023-06-30 --end 2025-06-30` (`riskprobe/lifecycle.py`). 한국 기업: `KR:003490` 또는 한글 이름 (`riskprobe/sources/dart.py`, 소스 선택은 `sources/market.py`)
- Probe: `python scripts/probe.py AES --as-of 2025-06-30` (Gemini 키 있으면 공시 추출 포함), Audit: `python scripts/audit.py data/ledger/HE_2023-06-30.json --end 2025-06-30`
- Watch: `python scripts/watch.py --since 2023-06-30 --until 2023-09-30 --rate-bp 100 --ebitda-pct -20` (감시 목록 `data/watchlist.json`)
- 앱: `streamlit run app/streamlit_app.py`. 배포·테스트 방법은 `docs/deploy.md`
- SEC 기준일 복원 점검: `python scripts/p0_check.py AES 2023-06-30 2025-06-30`, 지표·역산 점검: `python scripts/p1_check.py AMT --as-of 2025-06-30` (`SEC_USER_AGENT` 필요)
- 데이터 품질 규칙(의심 값, 부호 오류, 재작성 혼합 금지)은 `docs/p1_findings.md`. 원문 값을 고치지 않고 제외하며 사유를 Unknown으로 남긴다.
- 기준일 T 분석에는 `published_at <= T`인 값만 쓴다(`riskprobe/pit.py`). 정정 값은 덮어쓰지 않고 버전으로 남긴다.
- 숫자·날짜·판정은 코드가 하고, LLM은 문장 추출·분해·해석에만 쓴다. 확률을 만들지 않는다.
- 소스 결과는 값과 함께 근거(Evidence)와 한계(Unknown)를 반환한다. Unknown.message에는 숫자를 쓰지 않는다(LLM 입력용).
