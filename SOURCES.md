# SOURCES — 외부 자원 출처와 이용 내역

## 데이터

| 자원 | 용도 | 이용 조건 | 비고 |
|---|---|---|---|
| SEC EDGAR (`data.sec.gov` submissions, companyfacts; `www.sec.gov` company_tickers, Archives) | 미국 상장사 공시 목록·XBRL 재무값·원문 링크 | 공개 데이터, 키 불필요. 연락처가 담긴 User-Agent 필수, 초당 10건 이하 (https://www.sec.gov/os/accessing-edgar-data) | 요청 간격 0.12초로 제한 |
| 뉴욕 연준 Reference Rates API (SOFR) | Watch 금리 트리거, 금리 경로 재계산 | 공개 데이터, 키 불필요 (https://markets.newyorkfed.org/static/docs/markets-api.html) | |
| 연준 H.15 Selected Interest Rates (국채 10년물) | Watch 금리 트리거 | 미국 정부 공공 데이터, 출처 표기 (https://www.federalreserve.gov/releases/h15/) | 연준 Data Download Program |
| OpenDART (금융감독원) | 한국 상장사 목록(`corpCode.xml` → `data/dart_corps.json`), 공시 목록(`list.json`), 기업 개황(`company.json`), 보고서별 재무제표(`fnlttSinglAcntAll.json`) | 무료 API 키, 일 20,000건 (https://opendart.fss.or.kr) | P0에서 원본 XBRL 다운로드 확인. 지금은 보고서별 재무 API(정정 후 값, 정정일 기준)만 사용 |
| 한국은행 ECOS (시장금리 일별 817Y002) | 한국 기업 금리 경로: CD 91일(010502000), 국고채 3년(010200000) | 무료 API 키 (https://ecos.bok.or.kr/api) | 키가 없으면 한국 금리 경로 생략 |

## 기본 규칙 기준값 참고 자료 (`docs/p1_findings.md`)

- 대출 약정 관행: https://www.fe.training/?p=10006445 , https://hayot-expertise.fr/en/blog/banking-covenants-understand-respect , https://ibinterviewquestions.com/blog/debt-covenants-maintenance-vs-incurrence
- S&P 재무위험 매트릭스(구버전): https://www.maalot.co.il/Publications/MT20190402125127.PDF
- 미국 레버리지 대출 지침(2013) 해설: https://www.whitecase.com/sites/default/files/files/download/publications/article-us-leveraged-lending-guidelines.pdf , https://www.debevoise.com/insights/publications/2014/03/whats-new-leverage-lending-guidance

## 코드 (같은 저자의 기존 저장소에서 이식)

| 원본 | 이식 위치 | 변경 |
|---|---|---|
| `oceanstarlight/fund-reversing-ai` `tracer/http.py` | `riskprobe/http.py` | 설정 모듈 경로만 변경 |
| `oceanstarlight/fund-reversing-ai` `tracer/config.py` | `riskprobe/config.py` | 이 프로젝트 설정만 남김 |
| `oceanstarlight/fund-reversing-ai` `tests/fakes.py`, `tests/conftest.py` | `tests/` | SEC 페이로드 빌더로 교체 |
| `oceanstarlight/fund-reversing-ai` `tracer/sources/sec.py` | `riskprobe/sources/sec.py` | 티커 조회·User-Agent 처리만 재사용, 공시 목록·XBRL 값 수집은 새로 작성 |

## 라이브러리

| 라이브러리 | 라이선스 |
|---|---|
| requests | Apache-2.0 |
| pydantic | MIT |
| diskcache | Apache-2.0 |
| pytest | MIT |

## AI 모델·API

| 모델·API | 용도 | 비고 |
|---|---|---|
| Google Gemini API (`gemini-3.5-flash-lite`, 기본) | 연차보고서 발췌문에서 위험 요인·변동금리 차입금·금리 민감도·약정·고객 집중 추출, 보고서의 숫자 없는 해석 문장 | 결과는 원문 인용 검증·숫자 감사를 통과한 것만 사용. 같은 요청은 디스크 캐시로 재사용 |
| Anthropic Claude API (`claude-haiku-5-5`, 선택) | 위와 같음 (Gemini 키가 없을 때) | |

코드: `riskprobe/llm.py`는 `oceanstarlight/kr-fund-ai-agent` `sentinel/agents/llm.py`(→ `fund-reversing-ai` `tracer/llm.py`)에서, 원문 인용 검증 방식은 `fund-reversing-ai` `tracer/extract.py`에서, 숫자 감사(`audit`)는 `kr-fund-ai-agent` `audit_brief`에서 가져왔다.

| 라이브러리 | 라이선스 |
|---|---|
| google-genai | Apache-2.0 |
| anthropic | MIT |
