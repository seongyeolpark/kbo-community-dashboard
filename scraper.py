"""MLBpark KBO타운 게시판에서 KBO 구단별 관련 글을 수집한다.

MLBpark는 팀별 게시판이 따로 없고 KBO타운(b=kbotown) 하나로 운영되므로,
검색(m=search, query=<팀 검색어>)으로 각 구단 관련 글을 필터링해 가져온다.

- 목록/검색 페이지는 한 페이지에 약 30개 글(제목·날짜·댓글수·URL)을 준다.
- 오늘 작성 글은 날짜 칸에 시간(HH:MM:SS), 이전 글은 날짜(YYYY-MM-DD)로 표시된다.
- 사내망 SSL 프록시 때문에 verify=False로 요청한다.
- 수집 결과는 cache/mlbpark_kbo.csv 에 (id, team) 기준으로 누적 저장(중복 제거)한다.
"""
from __future__ import annotations

import os
import re
import time
from datetime import date, datetime, timedelta

import pandas as pd
import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE = "https://mlbpark.donga.com/mp/b.php"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

# KBO 10개 구단: 표시명 -> 검색어(MLBpark 검색에 넣을 질의어)
# 검색은 b=kbotown(야구 게시판)으로 제한되므로 각 팀의 가장 흔한 호칭을 쓴다.
# (닉네임 '다이노스/위즈'는 실사용 빈도가 낮아 최신 글을 대부분 놓친다 → 약칭 사용)
TEAMS: dict[str, str] = {
    "LG 트윈스": "LG",
    "두산 베어스": "두산",
    "KIA 타이거즈": "기아",
    "삼성 라이온즈": "삼성",
    "롯데 자이언츠": "롯데",
    "SSG 랜더스": "SSG",
    "NC 다이노스": "NC",
    "KT 위즈": "KT",
    "키움 히어로즈": "키움",
    "한화 이글스": "한화",
}

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
CACHE_FILE = os.path.join(CACHE_DIR, "mlbpark_kbo.csv")
BODY_CACHE_FILE = os.path.join(CACHE_DIR, "mlbpark_bodies.csv")
COLUMNS = ["id", "team", "date", "title", "comments", "url"]

_TIME_RE = re.compile(r"^\d{1,2}:\d{2}:\d{2}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ID_RE = re.compile(r"[?&]id=(\d+)")
_RECO_RE = re.compile(r"\s*추천\s*[\d,]+\s*(공유)?\s*$")  # 본문 끝 '추천 N 공유' 제거
_CNT_RE = re.compile(r"\[\s*(\d+)\s*\]\s*$")  # 제목 끝 댓글수 [12]


def _parse_row_date(text: str, today: date) -> datetime | None:
    text = text.strip()
    if _TIME_RE.match(text):
        h, m, s = (int(x) for x in text.split(":"))
        return datetime(today.year, today.month, today.day, h, m, s)
    if _DATE_RE.match(text):
        y, mo, d = (int(x) for x in text.split("-"))
        return datetime(y, mo, d)
    return None


PAGE_SIZE = 30  # 한 페이지 30건. MLBpark 검색의 p 파라미터는 '시작 행 오프셋'이다.


def _fetch_page(query: str, offset: int, timeout: int = 15) -> str:
    params = {
        "m": "search",
        "b": "kbotown",
        "select": "sct",      # 제목+본문 검색
        "query": query,
        "p": offset,          # 1, 31, 61, ... (30씩 증가)
    }
    r = requests.get(BASE, params=params, headers=HEADERS, timeout=timeout, verify=False)
    r.raise_for_status()
    return r.content.decode("utf-8", "ignore")


def _parse_list(html: str, today: date) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.select("tr"):
        a = tr.find("a", href=re.compile(r"m=view"))
        if not a:
            continue
        tit_el = tr.select_one(".tit")
        date_el = tr.select_one(".date")
        if not tit_el or not date_el:
            continue
        raw_title = tit_el.get_text(" ", strip=True)
        m = _CNT_RE.search(raw_title)
        comments = int(m.group(1)) if m else 0
        title = _CNT_RE.sub("", raw_title).strip()
        dt = _parse_row_date(date_el.get_text(strip=True), today)
        if dt is None or not title:
            continue
        href = a.get("href", "")
        idm = _ID_RE.search(href)
        post_id = idm.group(1) if idm else href
        rows.append(
            {"id": post_id, "date": dt, "title": title, "comments": comments, "url": href}
        )
    return rows


def _load_cache() -> pd.DataFrame:
    if os.path.exists(CACHE_FILE):
        try:
            df = pd.read_csv(CACHE_FILE, dtype={"id": str})
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            return df.dropna(subset=["date"])[COLUMNS]
        except Exception:
            pass
    return pd.DataFrame(columns=COLUMNS)


def _save_cache(df: pd.DataFrame) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    df.to_csv(CACHE_FILE, index=False, encoding="utf-8-sig")


def _scrape_one_team(
    team: str, query: str, cutoff: datetime, max_pages: int, delay: float, progress_cb
) -> tuple[list[dict], dict]:
    today = date.today()
    fresh: list[dict] = []
    seen_ids: set[str] = set()
    hit_cutoff = False
    pages_fetched = 0
    for i in range(max_pages):
        offset = 1 + i * PAGE_SIZE
        try:
            html = _fetch_page(query, offset)
        except Exception as e:
            if progress_cb:
                progress_cb(team, i + 1, max_pages, f"{team} {i + 1}p 요청 실패: {e}")
            break
        rows = _parse_list(html, today)
        pages_fetched += 1
        rows = [r for r in rows if r["id"] not in seen_ids]  # 오프셋 중복 방지
        if not rows:
            break
        for r in rows:
            r["team"] = team
            seen_ids.add(r["id"])
        fresh.extend(rows)
        if progress_cb:
            progress_cb(team, i + 1, max_pages, f"{team} · {i + 1}p · 누적 {len(fresh)}건")
        if min(r["date"] for r in rows) < cutoff:
            hit_cutoff = True
            break
        if delay:
            time.sleep(delay)
    meta = {
        "pages_fetched": pages_fetched,
        "hit_cutoff": hit_cutoff,
        "cap_reached": (not hit_cutoff) and pages_fetched >= max_pages,
        "fetched_rows": len(fresh),
    }
    return fresh, meta


def scrape(
    teams: list[str],
    period_days: int,
    max_pages: int = 40,
    delay: float = 0.35,
    progress_cb=None,
) -> tuple[pd.DataFrame, dict]:
    """선택한 구단들의 관련 글을 최신순으로 수집한다.

    각 팀마다 period_days 이전(cutoff)에 도달하거나 max_pages에 도달하면 멈춘다.
    반환: (기간 필터링된 DataFrame[team 포함], meta dict)
    """
    today = date.today()
    cutoff = datetime(today.year, today.month, today.day) - timedelta(days=period_days - 1)

    all_fresh: list[dict] = []
    per_team_meta: dict[str, dict] = {}
    for team in teams:
        query = TEAMS.get(team, team)
        fresh, meta = _scrape_one_team(team, query, cutoff, max_pages, delay, progress_cb)
        all_fresh.extend(fresh)
        per_team_meta[team] = meta

    cache = _load_cache()
    fresh_df = pd.DataFrame(all_fresh, columns=COLUMNS)
    if not fresh_df.empty:
        fresh_df["id"] = fresh_df["id"].astype(str)
        fresh_df["date"] = pd.to_datetime(fresh_df["date"])
    merged = pd.concat([cache, fresh_df], ignore_index=True)
    merged["date"] = pd.to_datetime(merged["date"], errors="coerce")  # 빈 캐시 시 dtype 보정
    merged = (
        merged.dropna(subset=["date"])
        .drop_duplicates(subset=["id", "team"], keep="last")
        .sort_values("date", ascending=False)
        .reset_index(drop=True)
    )
    _save_cache(merged)

    result = merged[
        (merged["date"] >= cutoff) & (merged["team"].isin(teams))
    ].reset_index(drop=True)
    meta = {
        "cutoff": cutoff,
        "per_team": per_team_meta,
        "cap_reached": any(m["cap_reached"] for m in per_team_meta.values()),
    }
    return result, meta


# ------------------------------------------------------------------ 본문 수집
def _load_body_cache() -> dict:
    if os.path.exists(BODY_CACHE_FILE):
        try:
            b = pd.read_csv(BODY_CACHE_FILE, dtype={"id": str})
            return dict(zip(b["id"], b["body"].fillna("")))
        except Exception:
            pass
    return {}


def _save_body_cache(d: dict) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    pd.DataFrame({"id": list(d.keys()), "body": list(d.values())}).to_csv(
        BODY_CACHE_FILE, index=False, encoding="utf-8-sig")


def _fetch_body(url: str, timeout: int = 15) -> str:
    """글 상세(m=view)에서 본문(.ar_txt)만 추출. 광고/댓글은 별도 영역이라 제외됨."""
    r = requests.get(url, headers=HEADERS, timeout=timeout, verify=False)
    r.raise_for_status()
    soup = BeautifulSoup(r.content.decode("utf-8", "ignore"), "html.parser")
    el = soup.select_one(".ar_txt")
    if not el:
        return ""
    return _RECO_RE.sub("", el.get_text(" ", strip=True))


def attach_bodies(df: pd.DataFrame, max_posts: int = 300, delay: float = 0.25,
                  progress_cb=None) -> tuple[pd.DataFrame, dict]:
    """df의 각 글 본문을 (id 캐시 사용) 수집해 'body' 컬럼으로 붙인다.
    글당 1요청이라 비용이 크므로 max_posts로 상한을 둔다(최신 글 우선)."""
    cache = _load_body_cache()
    seen, pairs = set(), []
    for i, u in zip(df["id"], df["url"]):     # df는 최신순 → 최신 글부터 본문 수집
        if i not in seen:
            seen.add(i)
            pairs.append((i, u))
    fetched = 0
    for i, u in pairs:
        if i in cache:
            continue
        if fetched >= max_posts:
            break
        try:
            cache[i] = _fetch_body(u)
        except Exception:
            cache[i] = ""
        fetched += 1
        if progress_cb:
            progress_cb(fetched, min(len(pairs), max_posts))
        if delay:
            time.sleep(delay)
    _save_body_cache(cache)
    out = df.copy()
    out["body"] = out["id"].map(cache).fillna("")
    meta = {"fetched": fetched, "unique_posts": len(pairs),
            "capped": len(pairs) > max_posts}
    return out, meta


if __name__ == "__main__":
    df, meta = scrape(teams=["LG 트윈스", "한화 이글스"], period_days=7, max_pages=3)
    print(meta["per_team"])
    print(df.groupby("team").size())
    print(df.head(6).to_string())
