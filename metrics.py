"""사용 지표(개인정보 없음)를 Google Sheets에 기록한다.

저장 항목: 날짜(KST) · 시간(0~23) · 접속수(visits) · 수집수(analyses).
- IP 등 개인정보는 저장하지 않는다(집계 카운트만).
- 시크릿 미설정/네트워크 실패 시 조용히 no-op → 앱 동작에 영향 없음.

필요 시크릿(.streamlit/secrets.toml 또는 Streamlit Cloud Secrets):
    [gcp_service_account]         # 서비스 계정 JSON 내용
    type = "service_account"
    project_id = "..."
    private_key = "-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----\\n"
    client_email = "xxx@xxx.iam.gserviceaccount.com"
    ...
    [metrics]
    sheet_key = "구글시트 ID"      # 시트 URL의 /d/<ID>/ 부분
"""
from __future__ import annotations

import datetime

import streamlit as st

try:
    import gspread
    from google.oauth2.service_account import Credentials
    _HAS_GSPREAD = True
except Exception:
    _HAS_GSPREAD = False

KST = datetime.timezone(datetime.timedelta(hours=9))
HEADER = ["date", "hour", "visits", "analyses"]


def _now_kst() -> datetime.datetime:
    return datetime.datetime.now(KST)


@st.cache_resource(show_spinner=False)
def _worksheet():
    """구글 시트 워크시트 핸들(캐시). 미설정/실패 시 None."""
    if not _HAS_GSPREAD:
        return None
    try:
        if "gcp_service_account" not in st.secrets or "metrics" not in st.secrets:
            return None
        info = dict(st.secrets["gcp_service_account"])
        key = st.secrets["metrics"]["sheet_key"]
        ws_name = st.secrets["metrics"].get("worksheet")   # 선택: 탭(워크시트) 이름
        creds = Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        sh = gspread.authorize(creds).open_by_key(key)
        if ws_name:
            try:
                ws = sh.worksheet(ws_name)             # 지정 탭 사용
            except gspread.WorksheetNotFound:
                ws = sh.add_worksheet(title=ws_name, rows=2000, cols=8)  # 없으면 생성
        else:
            ws = sh.sheet1                             # 미지정 시 첫 번째 탭
        if ws.acell("A1").value != "date":       # 헤더 없으면 생성
            ws.update("A1:D1", [HEADER])
        return ws
    except Exception:
        return None


def bump(kind: str) -> None:
    """kind='visit' 또는 'analysis' 카운트를 현재 (날짜, 시간) 버킷에 +1."""
    ws = _worksheet()
    if ws is None:
        return
    try:
        now = _now_kst()
        day, hour = now.strftime("%Y-%m-%d"), str(now.hour)
        col = 3 if kind == "visit" else 4
        data = ws.get_all_values()
        for i in range(1, len(data)):
            r = data[i]
            if len(r) >= 2 and r[0] == day and r[1] == hour:
                cur = int(r[col - 1]) if len(r) >= col and str(r[col - 1]).isdigit() else 0
                ws.update_cell(i + 1, col, cur + 1)
                return
        visits = 1 if kind == "visit" else 0
        analyses = 1 if kind == "analysis" else 0
        ws.append_row([day, hour, visits, analyses])
    except Exception:
        return
