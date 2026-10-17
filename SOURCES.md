# SOURCES — 외부 자원 출처와 이용 내역

## 데이터

| 자원 | 용도 | 이용 조건 | 비고 |
|---|---|---|---|
| SEC EDGAR (`data.sec.gov` submissions, companyfacts; `www.sec.gov` company_tickers, Archives) | 미국 상장사 공시 목록·XBRL 재무값·원문 링크 | 공개 데이터, 키 불필요. 연락처가 담긴 User-Agent 필수, 초당 10건 이하 (https://www.sec.gov/os/accessing-edgar-data) | 요청 간격 0.12초로 제한 |
| OpenDART (금융감독원) | 한국 상장사 공시 목록·재무제표·원본 XBRL | 무료 API 키, 일 20,000건 (https://opendart.fss.or.kr) | P0에서 원본 XBRL 다운로드 확인 |

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

아직 사용하지 않음 (P2부터 추가 예정).
