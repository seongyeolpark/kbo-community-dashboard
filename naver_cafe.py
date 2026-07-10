"""네이버 카페 '쌍둥이마당(LG트윈스 대표 팬카페)' 글 목록 수집.

- cafe: goodtwins (clubid=23679252)
- 글 '목록'은 비로그인으로 열린다: 제목·작성시각·댓글수·조회수·추천수·게시판명.
- 글 '본문/댓글 텍스트'는 회원 전용(로그인 필요)이라 수집하지 않는다.
- 사내망 SSL 프록시 때문에 verify=False로 요청한다.
"""
from __future__ import annotations

import html
import os
import time
from datetime import date, datetime, timedelta

import pandas as pd
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CAFE_SLUG = "goodtwins"
CLUB_ID = "23679252"
CAFE_NAME = "쌍둥이마당(LG트윈스 대표 팬카페)"
LIST_API = "https://apis.naver.com/cafe-web/cafe2/ArticleListV2dot1.json"
ARTICLE_URL = "https://cafe.naver.com/{slug}/{aid}"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Referer": f"https://cafe.naver.com/{CAFE_SLUG}/",
}
PAGE_SIZE = 50

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
CACHE_FILE = os.path.join(CACHE_DIR, "naver_goodtwins.csv")
COLUMNS = ["id", "board", "date", "title", "comments", "reads", "likes", "url"]

# 분석에서 제외할 운영/거래/응원방 등 게시판. 비교는 '공백 제거(strip)' 기준.
NOISE_BOARDS = {
    "필수]자기소개&등업신청",
    "레귤러 등업 게시판",
    "티켓 정가 양도",
    "경기 시작 4시간 전 티켓 양도",
    "티켓팅 정보방",
    "굿즈 (유니폼, 상품)",
    "응원마당(응원방전용)",
    "야구 말고 사는 이야기",
    "야구, 까페 Q&A / 공개제안",
    "이벤트 릴레이",
    "KS 직관 인증 게시판",
    "직관 메이트 & 동행 게시판",
    "공지사항",
    "쌍마 자료실",
}


def _fetch_list(page: int, timeout: int = 12) -> dict:
    params = {
        "search.clubid": CLUB_ID,
        "search.queryType": "lastArticle",
        "search.page": page,
        "search.perPage": PAGE_SIZE,
    }
    r = requests.get(LIST_API, params=params, headers=HEADERS, timeout=timeout, verify=False)
    r.raise_for_status()
    return r.json()["message"]["result"]


def _parse(arts: list[dict]) -> list[dict]:
    rows = []
    for a in arts:
        ts = a.get("writeDateTimestamp")
        if not ts:
            continue
        aid = a.get("articleId")
        rows.append({
            "id": str(aid),
            "board": a.get("menuName", ""),
            "date": datetime.fromtimestamp(ts / 1000),
            "title": html.unescape((a.get("subject") or "").strip()),
            "comments": int(a.get("commentCount", 0) or 0),
            "reads": int(a.get("readCount", 0) or 0),
            "likes": int(a.get("likeItCount", 0) or 0),
            "url": ARTICLE_URL.format(slug=CAFE_SLUG, aid=aid),
        })
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


def scrape(period_days: int, max_pages: int = 40, delay: float = 0.3,
           progress_cb=None) -> tuple[pd.DataFrame, dict]:
    """최신순으로 글 목록을 수집한다. cutoff 이전 도달 또는 max_pages 도달 시 종료."""
    today = date.today()
    cutoff = datetime(today.year, today.month, today.day) - timedelta(days=period_days - 1)

    fresh: list[dict] = []
    seen: set[str] = set()
    hit_cutoff = False
    pages = 0
    for p in range(1, max_pages + 1):
        try:
            res = _fetch_list(p)
        except Exception as e:
            if progress_cb:
                progress_cb(p, max_pages, f"{p}p 요청 실패: {e}")
            break
        rows = [r for r in _parse(res.get("articleList", [])) if r["id"] not in seen]
        pages += 1
        if not rows:
            break
        for r in rows:
            seen.add(r["id"])
        fresh.extend(rows)
        if progress_cb:
            progress_cb(p, max_pages, f"{p}p · 누적 {len(fresh)}건")
        if min(r["date"] for r in rows) < cutoff:
            hit_cutoff = True
            break
        if not res.get("hasNext"):
            break
        if delay:
            time.sleep(delay)

    cache = _load_cache()
    fresh_df = pd.DataFrame(fresh, columns=COLUMNS)
    if not fresh_df.empty:
        fresh_df["id"] = fresh_df["id"].astype(str)
        fresh_df["date"] = pd.to_datetime(fresh_df["date"])
    merged = pd.concat([cache, fresh_df], ignore_index=True)
    merged["date"] = pd.to_datetime(merged["date"], errors="coerce")
    merged = (merged.dropna(subset=["date"])
              .drop_duplicates(subset=["id"], keep="last")
              .sort_values("date", ascending=False).reset_index(drop=True))
    _save_cache(merged)

    result = merged[merged["date"] >= cutoff].reset_index(drop=True)
    meta = {"cutoff": cutoff, "pages_fetched": pages, "hit_cutoff": hit_cutoff,
            "cap_reached": (not hit_cutoff) and pages >= max_pages,
            "fetched_rows": len(fresh)}
    return result, meta


if __name__ == "__main__":
    df, meta = scrape(period_days=1, max_pages=5)
    print(meta)
    print("boards:", df["board"].value_counts().to_dict())
    print(df.head(6)[["date", "board", "comments", "title"]].to_string())
