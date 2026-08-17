# ETF Quant LIVE v2

V5.4 신호엔진 + 실제 운용 대시보드를 한 GitHub Pages 앱으로 묶은 버전입니다.

## 핵심 구조
- GitHub Actions가 매주 금요일 18:17 KST에 16개 ETF 최신 완료주봉 신호를 자동 계산합니다.
- 토요일 10:17 KST에 데이터 지연 대비 재계산합니다.
- 휴대폰 앱은 `data/latest_signals.json`을 읽어 매수/매도/보유/KOFR 주문표를 만듭니다.
- 실제 주문은 증권사에서 사람이 최종 확인 후 실행합니다.
- 계좌금액/보유종목/거래기록은 브라우저 localStorage에만 저장되며 GitHub에 올라가지 않습니다.

## V5.4 일치 규칙
- ACTIVE 16
- 최대 6슬롯 (LIVE 기본)
- hard stop -5%
- TREND: 완료주봉 20주선 이탈 -> 다음 거래일 시가 매도
- BOTTOM: 완료주봉 20주선 도달 -> 다음 거래일 시가 50% 익절
- BOTTOM runner: 완료주봉 20주선 이탈 -> 다음 거래일 시가 잔여 매도
- 신규 후보: TREND 우선, 이후 BOTTOM / strength 내림차순
- BATTERY(305540/305720) 동일테마 최대 1
- 일반 동적교체 없음
- 잔여자금 KOFR

## 기존 quant 저장소 업그레이드
1. ZIP을 압축 해제합니다.
2. GitHub `quant` 저장소 -> Add file -> Upload files.
3. 압축 해제된 폴더 안의 **모든 파일과 폴더**를 드래그합니다. `.github`, `data` 폴더도 포함합니다.
4. Commit changes 합니다.
5. Settings -> Pages -> Build and deployment -> Source를 **GitHub Actions**로 변경합니다.
6. Actions 탭 -> `ETF Quant LIVE v2 - Weekly Signals & Pages` -> Run workflow를 한 번 실행합니다.
7. 초록색 성공 후 기존 주소 `https://bada1379-ui.github.io/quant/`를 새로고침합니다.

## 주의
- GitHub Pages는 Python을 직접 서버에서 실행하지 않습니다. Python 신호 계산은 GitHub Actions runner에서 수행되고 결과 JSON을 Pages에 배포합니다.
- GitHub 예약 workflow는 약간 지연될 수 있습니다. 앱에는 실제 생성 시각과 기준 주봉 날짜가 표시됩니다.
- public 저장소에서는 60일 동안 저장소 활동이 전혀 없으면 scheduled workflow가 비활성화될 수 있습니다. 이 workflow는 정상 실행 때 신호 history를 commit하도록 구성했습니다.
- 신호 계산 16개 중 하나라도 실패하면 `latest_signals.json`을 새 결과로 덮어쓰지 않고 workflow가 실패하게 해 오래된 정상 신호를 보존합니다.
