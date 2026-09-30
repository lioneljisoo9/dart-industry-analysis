from datetime import datetime, timezone
import os

import pandas as pd
import requests
from dotenv import load_dotenv


NOTION_API_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class NotionAPIError(RuntimeError):
    """Notion API 호출 실패를 원인과 함께 표시한다."""


def get_notion_token():
    load_dotenv()
    token = os.getenv("NOTION_TOKEN", "").strip()
    if not token:
        raise ValueError(
            "NOTION_TOKEN이 설정되어 있지 않습니다. "
            ".env 또는 GitHub Actions secret에 추가하세요."
        )
    return token


def get_notion_page_id():
    load_dotenv()
    page_id = os.getenv("NOTION_PAGE_ID", "").strip()
    if not page_id:
        raise ValueError(
            "NOTION_PAGE_ID가 설정되어 있지 않습니다. "
            "자동화 전용 Notion 페이지 ID를 추가하세요."
        )
    return page_id.replace("-", "")


def _headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _request(method, path, token, **kwargs):
    response = requests.request(
        method,
        f"{NOTION_API_URL}{path}",
        headers=_headers(token),
        timeout=30,
        **kwargs,
    )
    if not response.ok:
        raise NotionAPIError(
            f"Notion API {method} {path} 실패 "
            f"({response.status_code}): {response.text[:500]}"
        )
    if not response.content:
        return {}
    return response.json()


def _rich_text(content):
    return [
        {
            "type": "text",
            "text": {"content": str(content)},
        }
    ]


def _paragraph(content):
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": _rich_text(content)},
    }


def _heading(level, content):
    block_type = f"heading_{level}"
    return {
        "object": "block",
        "type": block_type,
        block_type: {"rich_text": _rich_text(content)},
    }


def _bullet(content):
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": _rich_text(content),
        },
    }


def _format_percent(value):
    if pd.isna(value):
        return "n.a."
    return f"{float(value) * 100:.1f}%"


def build_dashboard_blocks(metrics_df, generated_at=None):
    """최근 연간 KPI를 Notion API block payload로 변환한다."""

    required = {
        "company",
        "year",
        "operating_margin",
        "operating_cash_flow_margin",
        "contract_assets_to_revenue",
        "contract_liabilities_to_revenue",
        "earnings_cash_gap_to_revenue",
    }
    missing = required.difference(metrics_df.columns)
    if missing:
        raise ValueError(
            "Notion 대시보드에 필요한 KPI 컬럼이 없습니다: "
            + ", ".join(sorted(missing))
        )

    latest = (
        metrics_df.sort_values(["company", "year"])
        .groupby("company", as_index=False)
        .tail(1)
        .sort_values("company")
    )
    if generated_at is None:
        generated_at = datetime.now(timezone.utc).isoformat()

    blocks = [
        _heading(1, "DART 자동화 대시보드"),
        _paragraph(
            "OpenDART → Raw → Master Parquet → Python KPI 흐름으로 생성한 "
            f"최근 연간 지표입니다. 생성 시각(UTC): {generated_at}"
        ),
        _heading(2, "최근 연간 KPI"),
    ]

    for _, row in latest.iterrows():
        blocks.append(
            _bullet(
                f"{row['company']} ({int(row['year'])}): "
                f"영업이익률 {_format_percent(row['operating_margin'])}, "
                f"영업현금흐름률 "
                f"{_format_percent(row['operating_cash_flow_margin'])}, "
                f"계약자산/매출 "
                f"{_format_percent(row['contract_assets_to_revenue'])}, "
                f"계약부채/매출 "
                f"{_format_percent(row['contract_liabilities_to_revenue'])}, "
                f"이익-현금흐름 차이/매출 "
                f"{_format_percent(row['earnings_cash_gap_to_revenue'])}"
            )
        )

    blocks.extend(
        [
            _heading(2, "회계·감사 검토 질문"),
            _bullet("계약자산 증가가 매출 성장보다 빠른가?"),
            _bullet("계약부채가 향후 수행의무와 어떻게 연결되는가?"),
            _bullet("영업이익과 영업현금흐름의 괴리가 운전자본으로 설명되는가?"),
            _bullet("예정원가 추정 변경이 이익률 변동을 설명하는가?"),
        ]
    )
    return blocks


def _list_page_children(page_id, token):
    children = []
    cursor = None
    while True:
        params = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        payload = _request(
            "GET",
            f"/blocks/{page_id}/children",
            token,
            params=params,
        )
        children.extend(payload.get("results", []))
        if not payload.get("has_more"):
            return children
        cursor = payload.get("next_cursor")


def publish_dashboard(metrics_df, page_id=None, token=None):
    """
    자동화 전용 Notion 페이지 내용을 교체한다.

    이 함수는 사용자가 별도로 만든 자동화 전용 페이지에서만 사용한다.
    페이지의 기존 하위 블록을 모두 삭제한 뒤 최신 KPI 블록을 추가한다.
    """

    token = token or get_notion_token()
    page_id = (page_id or get_notion_page_id()).replace("-", "")

    for block in _list_page_children(page_id, token):
        _request("DELETE", f"/blocks/{block['id']}", token)

    blocks = build_dashboard_blocks(metrics_df)
    for start in range(0, len(blocks), 100):
        _request(
            "PATCH",
            f"/blocks/{page_id}/children",
            token,
            json={"children": blocks[start : start + 100]},
        )

    return page_id

