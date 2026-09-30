# Project Status

현재 단계는 **조선 3사 KPI와 Notion 포트폴리오 화면을 연결한 분석 레이어 단계**입니다.

## 완료

- 기업명/종목코드 → DART 기업 자동 탐색
- 최근 5개 사업연도 전체 계정 수집
- 최근 20개 표시 분기 생성
- 분기 계산용 4개 buffer 분기 확보(기본 24개 계산 → 20개 표시)
- account_id 우선 계정 매칭
- 기간별 account_id 우선 Core 매핑 및 매칭 근거 보존
- BS / IS·CIS / CF 분기화
- CFS/OFS 불일치 차감 방지
- 분기 계산 근거와 상태값 보존
- DART 원본 재무 응답을 접수번호별 Raw JSON으로 보존
- Parquet Master Storage
- Excel 검토본 생성
- unittest 기반 데이터 엔진 회귀 테스트
- 연간·분기 자동 대사 및 검증 Parquet/Excel 생성
- 연간 KPI Master 생성 및 조선업 회계검토 지표 정의
- Notion에 조선산업 분석 루트와 자동화 전용 대시보드 생성
- Notion API block payload 생성 및 선택적 GitHub Actions 게시 스크립트 작성
- 데이터 엔진 버전 변경 시 기존 Master 자동 재구축
- Excel 파일이 열려 있을 때 타임스탬프 파일로 안전하게 대체 저장
- GitHub Actions 자동 갱신 골격

## 2026-09-30 중간점검

- 회귀 테스트 26개 통과
- 삼성중공업 end-to-end 실행 통과
  - 연간 2021~2025: 1,015행
  - 최근 20분기 2021 Q3~2026 Q2: 3,640행
  - Raw JSON 26개, API Key 비포함 확인
  - Excel 4개 시트 및 숫자형/`#,##0` 표시 확인
- 조선 3사 Master 재구축 및 전체 보존기간 자동 검증
  - 기업당 5개년 × 7개 Core 계정, 총 105개 규칙 검사
  - 삼성중공업: `PASS_EXACT` 31건, 최초연도 분기 부족 4건
  - 한화오션: `PASS_EXACT` 31건, 최초연도 분기 부족 4건
  - HD현대중공업: `PASS_EXACT` 24건, `WARN_ROUNDING` 7건, 최초연도 분기 부족 4건
  - Hard failure 0건
  - 검증 결과를 `data/processed` Parquet과 `outputs/excel/financial_validation.xlsx`로 저장
- GitHub Actions가 데이터 갱신 후 테스트와 자동 대사를 통과해야 commit하도록 연결
- GitHub Actions가 검증 후 `annual_metrics.parquet`까지 재생성하도록 연결

## 다음 단계

1. 조선 3사 비교용 산업 Master와 시계열 비교 테이블 구축
2. KPI별 감사위험 Rule과 설명 가능한 경고 상태 작성
3. `src/charts.py` matplotlib 자동 시각화
4. 수주잔고·계약자산·계약부채 등 산업특화 공시 데이터 확장
5. GitHub 원격 저장소 생성·push 및 Actions 실제 실행 확인

