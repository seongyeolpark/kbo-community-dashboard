"""제목 텍스트 분석: 한국어 토큰화, 빈도 집계, 워드클라우드, 급상승 키워드.

konlpy(형태소 분석기)는 JVM이 필요해 사내 환경에서 불안정하므로,
정규식 기반 경량 토크나이저 + 불용어/조사 처리로 대체한다.
"""
from __future__ import annotations

import os
import re
from collections import Counter

import pandas as pd
from wordcloud import WordCloud

# 한글 폰트: 플랫폼별 후보 중 존재하는 첫 경로를 사용(로컬 Windows / 리눅스 배포 모두 대응).
# Streamlit Community Cloud는 packages.txt의 fonts-nanum으로 나눔폰트가 설치된다.
_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\malgun.ttf",                             # Windows
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",          # Debian/Ubuntu (fonts-nanum)
    "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf",
    "/usr/share/fonts/opentype/nanum/NanumGothic.ttf",
    "/Library/Fonts/AppleGothic.ttf",                           # macOS
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
]
FONT_PATH = next((p for p in _FONT_CANDIDATES if os.path.exists(p)), None)

# 형태소 분석기(kiwipiepy): 자바 없이 동작. 있으면 품사 기반으로 명사만 추출해
# 동사(VV)·형용사(VA)·부사·조사·어미를 자동 제외한다. 없으면 정규식 방식으로 대체.
# 남길 품사: 일반명사(NNG)·고유명사(NNP)·외국어(SL, 예: LG/FA/KBO)
_KEEP_TAGS = {"NNG", "NNP", "SL"}
try:
    from kiwipiepy import Kiwi

    _kiwi = Kiwi()
    HAS_KIWI = True
except Exception:
    _kiwi = None
    HAS_KIWI = False

# 한글 토큰(2자 이상) 또는 영문/숫자 혼합 토큰(2자 이상) — 정규식 fallback용
_TOKEN_RE = re.compile(r"[가-힣]{2,}|[A-Za-z][A-Za-z0-9]+")

# 제거할 조사(토큰 끝) — 제거 후 2자 이상 남을 때만 적용
_JOSA_2 = ("으로", "에서", "에게", "한테", "까지", "부터", "보다", "이라", "라고", "께서", "이나", "든지")
_JOSA_1 = ("은", "는", "이", "가", "을", "를", "의", "에", "도", "만", "과", "와", "로")

# 기본 불용어(일반 + 야구 게시판 잡음)
STOPWORDS: set[str] = {
    # 일반
    "진짜", "그냥", "근데", "이거", "저거", "그거", "정도", "생각", "지금", "오늘", "어제", "내일",
    "우리", "너무", "정말", "그리고", "그래서", "하지만", "그런데", "이제", "다시", "아직", "제일",
    "가장", "완전", "약간", "조금", "많이", "역시", "물론", "그런", "이런", "저런", "무슨", "어떤",
    "이렇게", "그렇게", "저렇게", "때문", "경우", "관련", "대한", "위해", "통해", "하는", "했다",
    "한다", "합니다", "인데", "이네", "네요", "군요", "거나", "면서", "라서", "니까", "습니다",
    "봅니다", "같은", "같이", "보다", "보면", "보니", "부터", "까지", "그게", "이게", "저게",
    "여기", "거기", "저기", "누가", "언제", "어디", "그거", "요즘", "이번", "다들", "혹시",
    # 야구 게시판 잡음
    "경기", "선수", "야구", "그냥", "팬들", "감독", "구단", "시즌", "올해", "작년", "다음",
    "질문", "본문", "관련", "속보", "단독", "기사", "뉴스", "영상", "사진", "정리", "요약",
    "있는", "없는", "없음", "있음", "하는", "되는", "이라", "라는", "다는",
    # 이미지/URL 잡음
    "jpg", "jpeg", "gif", "png", "http", "https", "www", "com", "co", "kr",
}

# 팀명/약칭(선택적으로 제외 가능)
TEAM_TOKENS: set[str] = {
    "lg", "트윈스", "엘지", "두산", "베어스", "kia", "기아", "타이거즈", "삼성", "라이온즈",
    "롯데", "자이언츠", "ssg", "랜더스", "nc", "다이노스", "kt", "위즈", "키움", "히어로즈",
    "한화", "이글스",
}


def _strip_josa(tok: str) -> str:
    if len(tok) >= 4:
        for j in _JOSA_2:
            if tok.endswith(j) and len(tok) - len(j) >= 2:
                return tok[: -len(j)]
    if len(tok) >= 3:
        if tok[-1] in _JOSA_1:
            return tok[:-1]
    return tok


def _kiwi_candidates(text: str) -> list[str]:
    """형태소 분석으로 명사·외국어만 추출(동사/형용사/부사/조사/어미 제외)."""
    res = []
    for t in _kiwi.tokenize(text):
        if t.tag in _KEEP_TAGS:
            res.append(t.form.lower() if t.tag == "SL" else t.form)
    return res


def _regex_candidates(text: str) -> list[str]:
    """kiwi가 없을 때 fallback: 정규식 토큰 + 조사 제거."""
    res = []
    for m in _TOKEN_RE.findall(text):
        tok = m.lower() if re.match(r"[A-Za-z]", m) else m
        if re.match(r"[가-힣]", tok):
            tok = _strip_josa(tok)
        res.append(tok)
    return res


def tokenize(text: str, stopwords: set[str]) -> list[str]:
    text = str(text)
    cands = _kiwi_candidates(text) if HAS_KIWI else _regex_candidates(text)
    out = []
    for tok in cands:
        if len(tok) < 2:
            continue
        if tok in stopwords:
            continue
        out.append(tok)
    return out


# ------------------------------------------------------------------ 감성(긍/부정) 사전
# 형태소 토큰(명사)에는 감성어(형용사/동사)가 빠지므로, 원문 텍스트에서 직접 스캔한다.
# 야구 팬 커뮤니티 맥락의 경량 사전(부분일치). 정확도는 근사치.
POS_WORDS = frozenset({
    "최고", "대박", "명품", "감동", "대단", "완벽", "승리", "이겼", "이긴", "쾌승",
    "쾌투", "호투", "호수비", "활약", "부활", "반등", "클래스", "레전드", "잘한", "잘함",
    "잘해", "잘하", "기대", "응원", "축하", "희망", "든든", "멋지", "멋있", "훌륭",
    "소름", "캐리", "우승", "행복", "좋아", "좋네", "좋은", "최강", "믿음직", "화이팅",
    "파이팅", "굿뉴스", "역대급", "감사", "사랑",
})
NEG_WORDS = frozenset({
    "부상", "부진", "최악", "방출", "삽질", "폭투", "실책", "병살", "역전패", "패배",
    "무기력", "답답", "짜증", "실망", "아쉽", "우려", "걱정", "논란", "위기", "강판",
    "몰락", "노답", "못한", "못해", "못하", "불안", "폭망", "멘붕", "슬럼프", "침묵",
    "자멸", "붕괴", "굴욕", "참사", "망함", "망한", "망해", "블론", "분노", "화남",
    "싫어", "싫다", "최하위", "대량실점", "혹사", "먹튀", "트레이드설",
})


def sentiment_counts(text: str) -> tuple[int, int]:
    """원문에서 긍정·부정 어휘 출현 수(부분일치) 반환."""
    s = str(text)
    pos = sum(s.count(w) for w in POS_WORDS)
    neg = sum(s.count(w) for w in NEG_WORDS)
    return pos, neg


def build_stopwords(exclude_team_names: bool, extra: set[str] | None = None) -> set[str]:
    sw = set(STOPWORDS)
    if exclude_team_names:
        sw |= TEAM_TOKENS
    if extra:
        sw |= {s.strip().lower() for s in extra if s.strip()}
    return sw


def word_frequencies(titles: list[str], stopwords: set[str]) -> Counter:
    c: Counter = Counter()
    for t in titles:
        c.update(tokenize(str(t), stopwords))
    return c


def co_occurrence(texts, keyword: str, stopwords: set[str], top_n: int = 20) -> list[tuple]:
    """keyword가 포함된 글들에서, keyword를 제외하고 함께 자주 등장하는 단어 Top."""
    kw = keyword.strip().lower()
    if not kw:
        return []
    c: Counter = Counter()
    for t in texts:
        s = str(t)
        if kw in s.lower():
            for tok in set(tokenize(s, stopwords)):   # 글당 1회(중복 토큰 제거)
                if tok != kw and kw not in tok and tok not in kw:
                    c[tok] += 1
    return c.most_common(top_n)


def make_wordcloud(freq: Counter, max_words: int = 120, colormap="tab10",
                   background: str = "#fcfcfb"):
    """빈도 dict로 WordCloud 객체를 생성한다. 빈도가 없으면 None.

    colormap 은 이름(str) 또는 matplotlib Colormap 객체 모두 허용.
    """
    if not freq:
        return None
    wc = WordCloud(
        font_path=FONT_PATH if os.path.exists(FONT_PATH) else None,
        width=900,
        height=460,
        background_color=background,
        colormap=colormap,
        max_words=max_words,
        prefer_horizontal=0.92,
        relative_scaling=0.45,
        collocations=False,
        margin=3,
        random_state=42,   # 배치 고정 → 같은 빈도면 항상 같은 레이아웃
    )
    return wc.generate_from_frequencies(dict(freq))


def rising_keywords(df: pd.DataFrame, stopwords: set[str], top_n: int = 15,
                    text_col: str = "title") -> pd.DataFrame:
    """기간을 전/후반으로 나눠 후반부에 언급이 급증한 키워드를 찾는다.

    점수 = (후반 빈도+1)/(후반글수+1) 를 전반 대비 정규화한 증가율.
    반환 컬럼: word, early, late, score
    """
    if df.empty:
        return pd.DataFrame(columns=["word", "early", "late", "score"])
    col = text_col if text_col in df.columns else "title"
    d = df.sort_values("date")
    mid = d["date"].min() + (d["date"].max() - d["date"].min()) / 2
    early_titles = d[d["date"] < mid][col].tolist()
    late_titles = d[d["date"] >= mid][col].tolist()
    fe = word_frequencies(early_titles, stopwords)
    fl = word_frequencies(late_titles, stopwords)
    ne, nl = max(len(early_titles), 1), max(len(late_titles), 1)

    rows = []
    for w, late_cnt in fl.items():
        if late_cnt < 3:  # 노이즈 제거: 후반부 최소 3회
            continue
        early_cnt = fe.get(w, 0)
        rate_late = late_cnt / nl
        rate_early = early_cnt / ne
        score = (rate_late + 1e-6) / (rate_early + 1e-6)
        rows.append({"word": w, "early": early_cnt, "late": late_cnt, "score": round(score, 2)})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["score", "late"], ascending=False).head(top_n).reset_index(drop=True)
