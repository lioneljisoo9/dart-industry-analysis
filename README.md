# DART Industry Analysis

OpenDART 전체 재무제표 API를 이용해 기업의 최근 연간/분기 재무데이터를 수집하고, 로컬 Master Data에 보존하는 프로젝트입니다.

## 현재 구현 범위

- 기업명 또는 6자리 종목코드로 기업 자동 탐색
- 연결재무제표(CFS) 우선, 연결이 없으면 별도재무제표(OFS) 자동 fallback
- 최초 실행 시 최근 5개 사업연도 전체 재무계정 수집
- 분기 데이터는 **계산용 최대 24개 분기(20개 표시 + 4개 buffer)** 를 먼저 확보
- 사용자·Excel·Master에는 최근 **20개 분기만 표시/보존**
- 첫 표시 분기 계산에 필요한 직전 분기를 buffer로 사용
- 분기 손익계산서: Q1~Q3는 DART 3개월 금액 사용
- Q4 손익: FY - Q3 누적
- 분기 현금흐름표: YTD 누적값 차감으로 개별 분기 계산
- Q4 현금흐름: FY - Q3 누적
- 계정 매칭은 `account_id` 우선, 계정명은 보조 기준
- Core 계정에는 `standard_account_match`로 매칭 근거 보존
- CFS/OFS가 서로 다른 기간끼리는 차감 계산하지 않음
- `quarter_amount_basis`, `calculation_status`로 분기 숫자의 생성 근거·실패 원인 보존
- 성공한 DART 재무 응답은 `data/raw`에 접수번호별 JSON으로 보존
- `data/master`에 연간/분기 Parquet Master 저장
- 평소 `main.py` 실행 시 Master가 있으면 재무 API를 다시 호출하지 않음
- 자동 갱신 시 현재연도/직전연도만 확인하고 신규·변경 기간만 Master에 교체
- Master는 최근 5개년 / 최근 20분기 rolling window 유지
- 계산 로직 버전이 바뀌면 기존 Master를 자동 재구축
- Excel에 `Annual_All`, `Annual_Core`, `Quarterly_All`, `Quarterly_Core` 저장
- 연간 금액과 분기 합계·Q4 잔액을 비교하는 자동 검증 리포트 생성
- Master에서 기업·연도별 KPI와 조선업 회계검토 지표를 계산
- GitHub Actions에서 매일 Master 갱신 후 변경된 Parquet을 저장소에 commit
- GitHub Actions에서 선택적으로 Notion 자동화 전용 페이지 갱신

## 분기 계산 상태

`Quarterly_All`과 `Quarterly_Core`에는 다음 컬럼이 포함됩니다.

- `quarter_amount`: 개별 분기 기준 금액
- `quarter_amount_basis`: 계산 방식
- `calculation_status`: 계산 성공/실패 원인

대표 상태값:

- `OK`
- `AMOUNT_MISSING`
- `PREVIOUS_PERIOD_MISSING`
- `PREVIOUS_ACCOUNT_MISSING`
- `FS_DIV_MISMATCH`
- `NOT_QUARTERIZED`

## 데이터 흐름

```text
OpenDART
   ↓ 원본 JSON 보존
data/raw
   ↓ normalize
data/master/*.parquet
   ↓
Python 분석 / Excel / matplotlib / Notion
```

Excel은 분석 원본이 아니라 보존·검토용 Output입니다. 평소 분석은 `data/master`의 Parquet을 직접 읽습니다.

`data/raw`는 로컬 증빙 데이터이므로 Git에는 올리지 않습니다. API Key는 Raw JSON에 저장하지 않습니다.

## 처음 설정

이 배포본에는 `.env`와 `.venv`가 포함되어 있지 않습니다.

가상환경 생성:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`.env.example`을 참고해 프로젝트 루트에 `.env`를 직접 만들고 DART API Key를 넣습니다.

```text
DART_API_KEY=본인의_API_KEY
```

## 로컬 실행

```powershell
python main.py
```

- 해당 기업의 Master Data가 없으면 DART에서 최초 수집합니다.
- 이미 Master Data가 있으면 DART 재무 API를 다시 호출하지 않고 로컬 Parquet을 사용합니다.

## 수동 최신화

```powershell
python scripts/update_financials.py
```

기존 Master가 있으면 전체 5개년/20분기를 다시 받지 않고 현재연도와 직전연도의 보고서를 확인합니다.

## 데이터 엔진 테스트

외부 API를 호출하지 않는 회귀 테스트를 실행합니다.

```powershell
python -m unittest discover -s tests -v
```

검증 범위에는 `account_id` 우선 Core 매칭, BS 시점잔액, IS/CIS 3개월 금액과 Q4 차감, CF 누적 차감, CFS/OFS 불일치 차단, 증분 변경 감지, Raw 응답 보존이 포함됩니다.

## 로컬 Master 검증

DART API를 다시 호출하지 않고 저장된 Master만 사용해 연간·분기 금액을 대사합니다.

```powershell
python scripts/validate_financials.py
```

- 손익·현금흐름 계정: `FY = Q1 + Q2 + Q3 + Q4`
- 재무상태표 계정: `FY = Q4 시점잔액`
- 기본 허용오차: 1,000원
- `FAIL_DIFFERENCE`, 재무제표 구분·통화 불일치 등 Hard failure가 있으면 종료코드 1
- 최초 표시연도처럼 4개 분기가 모두 보존되지 않은 기간은 `NOT_TESTABLE_*`로 구분하고 실패로 처리하지 않음

결과 파일:

```text
data/processed/
├─ financial_validation.parquet
├─ 010140_validation.parquet
└─ ...

outputs/excel/
└─ financial_validation.xlsx
```

특정 기업만 검증할 수도 있습니다.

```powershell
python scripts/validate_financials.py --company 삼성중공업
```

## 연간 KPI Master

검증이 끝난 로컬 Master에서 기업 간 비교용 KPI를 계산합니다. 이 단계는
수치를 계산할 뿐이며 감사위험 판정 기준은 별도 규칙으로 관리합니다.

```powershell
python scripts/build_metrics.py
python scripts/build_metrics.py --company 삼성중공업 --company 한화오션
```

생성 파일:

```text
data/processed/annual_metrics.parquet
```

현재 KPI에는 매출 성장률, 영업이익률, 순이익률, 영업현금흐름률,
재고·계약자산·계약부채의 매출 대비 비율, 순계약자산,
영업이익과 영업현금흐름의 차이가 포함됩니다. 계정 누락과 분모 0은
0으로 바꾸지 않고 상태·`NaN`으로 보존합니다.

## Master 파일

```text
data/master/
├─ 010140_annual.parquet
├─ 010140_quarterly.parquet
├─ 010140_metadata.json
└─ ...
```

## GitHub Actions

Repository Settings > Secrets and variables > Actions에 다음 secret을 등록합니다.

- `DART_API_KEY`
- `NOTION_TOKEN` (Notion integration token)
- `NOTION_PAGE_ID` (자동화 전용 대시보드 페이지 ID)

기본 스케줄은 매일 00:00 UTC(한국시간 09:00)입니다. 자동 갱신 후 테스트와 Master 검증을 모두 통과해야 변경 데이터가 commit됩니다. Notion secret 두 개가 등록된 경우에만 대시보드 갱신 단계가 실행됩니다.

## Notion 포트폴리오

현재 Notion의 `조선 산업 공부` 페이지에 데이터 자동화 현황과 2025년 조선 3사 KPI를 정리했고, 그 하위에 `조선산업 자동화 대시보드` 전용 페이지를 만들었습니다. 이 전용 페이지는 `scripts/publish_notion.py`가 최신 KPI로 내용을 교체하는 대상입니다.

로컬에서 연결을 확인하려면 `.env`에 다음 값을 넣습니다.

```text
NOTION_TOKEN=secret_...
NOTION_PAGE_ID=자동화_전용_페이지_ID
```

Notion integration에는 해당 대시보드 페이지를 반드시 공유해야 합니다. 토큰이 없으면 로컬 KPI 계산과 Parquet 저장은 그대로 실행되고 Notion 단계만 실행되지 않습니다.

## 보안

- `.env`는 GitHub에 올리지 않습니다.
- `.venv`도 GitHub에 올리지 않습니다.
- `.env.example`만 공유합니다.

