# 테스트와 배포

## 테스트

| 종류 | 명령 | 네트워크·키 | 언제 |
| --- | --- | --- | --- |
| 단위·통합 + 앱 렌더링 | `python -m pytest -q` | 불필요 (가짜 HTTP, Streamlit AppTest) | 푸시·PR마다 GitHub Actions `tests` 자동 실행 |
| 실데이터 점검 | `python scripts/probe.py AES --as-of 2025-06-30`, `python scripts/audit.py data/ledger/HE_2023-06-30.json --end 2025-06-30` | `SEC_USER_AGENT` (+ 선택 `GEMINI_API_KEY`) | 수동 |

## Streamlit Community Cloud 배포

1. share.streamlit.io → **Create app** → 저장소 `oceanstarlight/thesis-stress-AB`, 브랜치 `main`, 파일 `app/streamlit_app.py`.
2. **Advanced settings** → Python 3.12, **Secrets**에 `.streamlit/secrets.toml.example` 형식으로 입력:
   ```toml
   SEC_USER_AGENT = "이름 이메일@example.com"
   GEMINI_API_KEY = "..."
   RISKPROBE_LLM_PROVIDER = "auto"
   ```
   앱이 시작할 때 `st.secrets`의 최상위 문자열 값을 환경 변수로 옮기므로 코드 수정 없이 읽힌다.
3. 배포 후 확인: 사이드바에 `🟢 SEC EDGAR`, `🟢 LLM: gemini`가 보이는지 → Probe 데모 버튼(AES) → Audit 탭 데모(HE).

## 예약 감시 (GitHub Actions `watch`)

- 평일 매일 22:17 UTC에 `data/watchlist.json`의 원장을 확인하고, 새 경보(높음·중간)가 있으면 GitHub Issue를 연다.
- 필요한 설정: 저장소 Settings → Secrets and variables → Actions → **`SEC_USER_AGENT`** 추가. LLM 키는 필요 없다.
- 마지막 실행일은 Actions 캐시(`watch_state/state.json`)에 저장돼 다음 실행이 그 이후만 본다. 수동 실행: Actions → watch → Run workflow.

## 병합 후 앱 오류가 나면

새 코드를 병합하면 Streamlit Cloud가 파일만 바꾸고 이미 메모리에 올라간 일부 모듈은 예전 것을 계속 쓸 수 있다. 이때 로컬에서는 안 나는 `AttributeError` 같은 오류가 난다. **Manage app → ⋮ → Reboot app**으로 다시 시작하면 해결된다.

## 운영 메모

- 첫 실행은 SEC 데이터(기업별 companyfacts 수 MB, 10-K 원문 수 MB)를 받느라 기업당 수십 초 걸린다. 같은 입력은 앱 캐시(6시간)와 디스크 HTTP 캐시(24시간)로 다시 받지 않는다.
- SEC는 초당 10건 이하를 요구한다. HTTP 계층이 호스트별 간격(0.12초)을 지킨다.
- Gemini 키가 없으면 공시 추출·해석 단계만 빠지고 나머지(지표·역산·재생)는 그대로 돈다.
- 데모 원장은 `data/ledger/`에 저장소와 함께 배포된다.
