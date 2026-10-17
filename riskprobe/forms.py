"""Filing form groups shared by SEC and DART sources.

DART report names are kept in Korean as the form ("사업보고서"); an amendment ([기재정정] etc.)
gets the same "/A" suffix SEC uses, so the rules below read the same for both markets.
"""

ANNUAL = ("10-K", "10-K/A", "20-F", "40-F", "사업보고서", "사업보고서/A")
# Reports that move the financial period forward (amendments re-state, they do not add a period).
PERIODIC = ("10-Q", "10-K", "분기보고서", "반기보고서", "사업보고서")
# Current reports: events between periodic reports.
CURRENT = ("8-K", "8-K/A", "주요사항보고서", "거래소공시")
# Forms whose changed values start a new basis (see pit.Snapshot.restated_on).
BASIS_CHANGING = {"10-K", "10-K/A", "10-Q/A", "8-K", "8-K/A", "20-F", "40-F",
                  "사업보고서", "사업보고서/A", "반기보고서/A", "분기보고서/A"}
