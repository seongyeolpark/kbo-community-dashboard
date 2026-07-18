"""LG 트윈스 공식 홈페이지에서 1군 로스터(등록 선수) 명단을 가져온다.

- https://www.lgtwins.com/game/roster 의 선수 테이블을 파싱
  (셀 구성: 배번 · 이름 · 투타유형 · 생년월일 · 신장/체중 · 등록일자)
- 네트워크 실패/사이트 변경 시 FALLBACK 명단으로 대체한다.
"""
from __future__ import annotations

import re

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ROSTER_URL = "https://www.lgtwins.com/game/roster"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
}

# 파싱 실패 시 사용할 기본 명단(최근 확인된 1군 로스터 스냅샷).
FALLBACK = [
    "강민균", "임찬규", "문보경", "신민재", "구본혁", "이영빈", "문성주", "오지환",
    "함덕주", "박해민", "우강훈", "이우찬", "오스틴", "박동원", "손주영", "톨허스트",
    "이정용", "김진성", "김진수", "리오스", "김윤식", "홍창기", "이재원", "천성호",
    "송찬의", "문정빈", "박시원", "이주헌", "김영우", "웰스",
]


def fetch_roster(timeout: int = 15) -> list[str]:
    """공식 로스터 페이지에서 (배번·이름·투타유형) 행을 찾아 이름을 순서대로 추출."""
    r = requests.get(ROSTER_URL, headers=HEADERS, timeout=timeout, verify=False)
    r.raise_for_status()
    soup = BeautifulSoup(r.content.decode("utf-8", "ignore"), "html.parser")
    names, seen = [], set()
    for tr in soup.find_all("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
        for i in range(len(cells) - 2):
            if (re.fullmatch(r"\d{1,3}", cells[i])
                    and re.fullmatch(r"[가-힣]{2,5}", cells[i + 1])
                    and re.search(r"(좌투|우투|언더)", cells[i + 2])):
                nm = cells[i + 1]
                if nm not in seen:
                    seen.add(nm)
                    names.append(nm)
                break
    return names


def get_roster() -> tuple[list[str], bool]:
    """(명단, 공식페이지_성공여부). 실패하거나 너무 적으면 FALLBACK 사용."""
    try:
        names = fetch_roster()
        if len(names) >= 15:
            return names, True
    except Exception:
        pass
    return list(FALLBACK), False


if __name__ == "__main__":
    ns, ok = get_roster()
    print("official ok:", ok, "count:", len(ns))
    print(ns)
