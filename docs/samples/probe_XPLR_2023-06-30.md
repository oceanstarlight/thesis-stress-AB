# 위험 탐색 보고서: XPLR Infrastructure, LP

- 기준일: 2023-06-30 (이날까지 공개된 공시만 사용) · 재무 기준 기간 말: 2023-03-31
- 연차보고서: 10-K 2023-02-23 ([원문](https://www.sec.gov/Archives/edgar/data/1603145/000160314523000005/nep-20221231.htm))
- 모든 수치는 공시 원문 값으로 코드가 계산했고, 역산 결과는 **조건부 계산(예측 아님)**이다. 확률은 제시하지 않는다.

## 1. 한눈에 보는 결론 (코드 판정)

- **순차입금/EBITDA** (공시 EBITDA, 기본 규칙 5.00배): 현재 8.17배로 기준일에 이미 기준을 넘음 → 초과
- **이자보상배율** (공시 EBITDA, 기본 규칙 2.00배): 입력 없음 — 계산하지 않음 (데이터 한계 참고)
- **금리 상승 시 이자보상배율** (공시 EBITDA, 기본 규칙 2.00배): 입력 없음 — 계산하지 않음 (데이터 한계 참고)

### 공시 위험 요인과의 연결 (LLM 해석, 숫자 없음)

- 변동금리 부채와 자본시장 혼란에 따른 이자비용 증가 위험은 이자보상배율 관련 경로에 직접적인 압력으로 작용한다.
- 재무 약정 준수 실패 위험과 차환 제약은 순차입금 대비 EBITDA 기준 충족 여부를 악화시키는 주요 원인이 된다.

### 추가로 확인할 질문

- 회사가 보유한 이자율 스왑 계약의 구체적인 금리 상한선과 변동금리 노출 규모는 어느 수준인가.
- 핵심 자회사들의 재무 약정 여유 폭과 잠재적 약정 위반 시 대응 계획은 무엇인가.

## 2. 깨지는 조건 (역산)

| 경로 | EBITDA | 기준값 | 현재 | 기준 도달 충격 | 등급 | 입력 출처 |
|---|---|---|---|---|---|---|
| EBITDA 감소 → 이자보상배율 기준 미달 | 공시 EBITDA | 2.00배 (기본 규칙) | - | 입력 없음 | - | 공시 재무값 |
| 금리 상승 → 변동금리 이자비용 증가 → 이자보상배율 기준 미달 | 공시 EBITDA | 2.00배 (기본 규칙) | - | 입력 없음 | - | 공시 재무값 |
| EBITDA 감소 → 순차입금/EBITDA 기준 초과 | 공시 EBITDA | 5.00배 (기본 규칙) | 8.17배 | 이미 초과 | 초과 | 공시 재무값 |

계산식: EBITDA 감소 → 순차입금/EBITDA 기준 초과: s = 1 - 순차입금 / (기준 배수 × EBITDA) / EBITDA 감소 → 이자보상배율 기준 미달: s = 1 - 기준 배율 × 이자비용 / EBITDA / 금리 상승 → 변동금리 이자비용 증가 → 이자보상배율 기준 미달: dr = (EBITDA / 기준 배율 - 이자비용) / 변동금리 차입금

## 3. 결론과 충돌하는 근거 (반증 탐색, 코드 규칙)

| 출처 | 신호 | 내용 | 원문 |
|---|---|---|---|
| 재무 지표 | 재고가 매출보다 빠르게 늘어남 | 재고 증가율 - 매출 증가율 13.05 (10.0%p 초과, 기본 규칙) | [1](https://www.sec.gov/Archives/edgar/data/1603145/000160314522000018/) [2](https://www.sec.gov/Archives/edgar/data/1603145/000160314523000005/) [3](https://www.sec.gov/Archives/edgar/data/1603145/000160314523000017/) |
| 수시공시 | 최근 1년 수시공시: 기타 사건, 소송·조사 | 2022-12-07 8-K (medium) | [1](https://www.sec.gov/Archives/edgar/data/1603145/000160314522000044/nep-20221207.htm) |
| 수시공시 | 최근 1년 수시공시: 기타 사건, 소송·조사 | 2022-12-08 8-K (medium) | [1](https://www.sec.gov/Archives/edgar/data/1603145/000160314522000048/nep-20221208.htm) |
| 연차보고서 | 연차보고서 위험 서술: refinancing | If NEP's subsidiaries, including NEP OpCo, do not comply with their obligations under their debt instruments, they may need to refinance all or a part of their indebtedness, which they may not be able to do on similar terms or at all. | [1](https://www.sec.gov/Archives/edgar/data/1603145/000160314523000005/nep-20221231.htm) |
| 연차보고서 | 연차보고서 위험 서술: covenant | failure to comply with the covenants in the agreements governing these obligations could result in an event of default under those agreements, which could be difficult to cure, result in bankruptcy or, with respect to subsidiary debt, result in loss of NEP OpCo's ownership interest in one or more of | [1](https://www.sec.gov/Archives/edgar/data/1603145/000160314523000005/nep-20221231.htm) |
| 연차보고서 | 연차보고서 위험 서술: liquidity | Disruptions, uncertainty or volatility in those capital and credit markets, related to, among other factors, inflation, rising interest rates, geopolitical events and the planned phase out of the London Inter-Bank Offered Rate or the reform or replacement of other benchmark interest rates, could inc | [1](https://www.sec.gov/Archives/edgar/data/1603145/000160314523000005/nep-20221231.htm) |
| 연차보고서 | 연차보고서 위험 서술: credit_rating | NEP’s liquidity, ability to access credit and capital markets and cost of borrowings is dependent on its credit ratings. | [1](https://www.sec.gov/Archives/edgar/data/1603145/000160314523000005/nep-20221231.htm) |

반증 신호는 더 들여다볼 이유이며, 위험하다는 판정이 아니다.

## 4. 핵심 지표

| 지표 | 값 | 계산식 |
|---|---|---|
| 분기 매출 전년 대비 증가율 | 7.1% | 분기 매출 / 전년 같은 분기 매출 - 1 |
| 매출총이익률(TTM) | - | 매출총이익 / 매출 |
| 영업이익률(TTM) | 13.5% | 영업이익 / 매출 |
| EBITDA(TTM) | $625M | 영업이익 + 감가상각비 |
| 이자보상배율(TTM, EBITDA 기준) | - | EBITDA / 이자비용 |
| 순차입금/EBITDA | 8.17배 | (총차입금 - 현금성자산) / EBITDA |
| 조정 EBITDA(TTM, 손상차손 가산) | - | EBITDA + 표준 태그로 확인된 손상차손 (영업권 + 기타 자산) |
| 단기차입 비중 | - | 단기차입금 / (총차입금 + 단기차입금) |
| 영업현금흐름/순이익(TTM) | 2.31배 | 영업현금흐름 / 순이익 |
| 설비투자/매출(TTM) | 104.4% | 설비투자 / 매출 |
| 재고 증가율 - 매출 증가율 | 13.0%p | 재고 전년 대비 증가율 - 매출(TTM) 전년 대비 증가율 |
| 매출채권 회전일수 | 42일 | 매출채권 / 매출(TTM) × 365 |
| 유동비율 | 1.39배 | 유동자산 / 유동부채 |

## 5. 공시에서 확인한 위험 요인

- **[floating_rate]** 회사는 금리 변동성으로부터 보호하기 위해 이자율 스왑을 사용하지만 이자율 변동 위험에 노출되어 있습니다.  
  > Some of NEP's subsidiaries’ indebtedness accrues interest at variable rates, and some of its subsidiaries use interest rate swaps to try to protect against market volatility.
- **[refinancing]** 부채 조건에 대한 준수 실패 시 부채 상환 능력이 저하될 수 있으며 유리한 조건으로 차환하지 못할 수 있습니다.  
  > If NEP's subsidiaries, including NEP OpCo, do not comply with their obligations under their debt instruments, they may need to refinance all or a part of their indebtedness, which they may not be able to do on similar terms or at all.
- **[covenant]** 재무 약정 준수 실패는 채무 불이행으로 이어질 수 있으며 자산 압류 위험을 초래할 수 있습니다.  
  > failure to comply with the covenants in the agreements governing these obligations could result in an event of default under those agreements, which could be difficult to cure, result in bankruptcy or, with respect to subsidiary debt, result in loss of NEP OpCo's ownership interest in one or more of its subsidiaries or in some or all of their assets as a result of foreclosure;
- **[liquidity]** 신용 및 자본 시장의 중대한 혼란이나 이자율 상승은 자금 조달 능력을 제한하고 자본 비용을 증가시킬 수 있습니다.  
  > Disruptions, uncertainty or volatility in those capital and credit markets, related to, among other factors, inflation, rising interest rates, geopolitical events and the planned phase out of the London Inter-Bank Offered Rate or the reform or replacement of other benchmark interest rates, could increase NEP's cost of capital and affect its ability to fund its liquidity and capital needs.
- **[credit_rating]** 회사의 유동성, 신용 및 자본 시장 접근성, 차입 비용은 신용등급에 따라 결정됩니다.  
  > NEP’s liquidity, ability to access credit and capital markets and cost of borrowings is dependent on its credit ratings.
- **[customer_concentration]** 대다수의 거래상대방이 에너지 산업에 집중되어 있어 경제 조건 변화 등에 따라 신용 위험이 가중될 수 있습니다.  
  > The majority of NEP's counterparties are in the energy industry, and this concentration may impact the overall exposure to credit risk, either positively or negatively, in that the counterparties may be similarly affected by changes in economic, industry or other conditions.
- **[contract]** 계약 상대방의 이행 실패나 평가 가정 변경은 재무 상태에 부정적인 영향을 미칠 수 있습니다.  
  > If the values of these financial contracts change in a manner that NEP does not anticipate, or if a counterparty fails to perform under a contract, it could have a material adverse effect on its business, financial condition, results of operations and ability to make cash distributions to its unitholders.
- **[regulatory]** 정부 또는 규제 기관의 조치는 자본 접근성에 영향을 미쳐 사업 수행에 부정적인 영향을 줄 수 있습니다.  
  > Actions taken in response to such crises by federal, state and local government or regulatory agencies may impact NEP’s ability to access capital and could have a material adverse impact on NEP's business, financial condition, liquidity, results of operations and ability to make cash distributions to its unitholders.

## 6. 데이터 공백·분석 한계

- 실적 보도자료 숫자는 구조화 데이터에 없어 실제 최초 공개일이 공시일보다 빠를 수 있음
- 구조화 재무 데이터가 시작되기 전 기간은 기준일 분석에 쓸 수 없음
- 공시의 보고 대상 기간과 맞지 않는 값이 있어 의심 값으로 보고 분석에서 제외함
- 원문에서 확인되지 않거나 수치를 읽을 수 없는 추출 결과를 버림
- EBITDA 감소 → 이자보상배율 기준 미달: 필요한 입력값이 없어 계산하지 않음
- 금리 상승 → 변동금리 이자비용 증가 → 이자보상배율 기준 미달: 필요한 입력값이 없어 계산하지 않음
- 매출총이익률(TTM) 계산에 필요한 매출총이익 값이 없어 계산하지 않음
- 이자보상배율(TTM, EBITDA 기준) 계산에 필요한 이자비용 값이 없어 계산하지 않음
- 최근 열두 달 손상차손이 표준 태그로 확인되지 않아 조정하지 않음
- 단기차입 비중 계산에 필요한 단기차입금 값이 없어 계산하지 않음

## 7. 출처

- [10-Q 0001603145-23-000017](https://www.sec.gov/Archives/edgar/data/1603145/000160314523000017/)
- [10-K 2023-02-23](https://www.sec.gov/Archives/edgar/data/1603145/000160314523000005/nep-20221231.htm)

## 8. 가정 원장에 기록할 항목 (사용자 승인 전)

- A1: 순차입금/EBITDA가 기준 이하로 유지된다 (기본 규칙) · 기준 5.0 (default_rule)
