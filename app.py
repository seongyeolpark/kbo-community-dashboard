"""KBO 커뮤니티 트렌드 분석 대시보드.

데이터 소스: MLBpark KBO타운 / 네이버 카페 쌍둥이마당(LG 팬카페).
실행: python -m streamlit run app.py
"""
from __future__ import annotations

import colorsys

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
from matplotlib import font_manager
from matplotlib.colors import LinearSegmentedColormap, ListedColormap, to_rgb

import analyzer
import lg_roster
import naver_cafe
import scraper

# 한글 폰트: analyzer가 찾은 파일을 matplotlib에 등록하고 그 이름을 family로 사용
# (로컬 Windows=Malgun Gothic, 배포 리눅스=NanumGothic 등 자동 대응)
if analyzer.FONT_PATH:
    try:
        font_manager.fontManager.addfont(analyzer.FONT_PATH)
        _FONT_FAMILY = font_manager.FontProperties(fname=analyzer.FONT_PATH).get_name()
    except Exception:
        _FONT_FAMILY = "sans-serif"
else:
    _FONT_FAMILY = "sans-serif"

# ------------------------------------------------------------------ 다크 테마 색
SURFACE = "#1a1a17"
INK = "#f4f2ea"
INK2 = "#c3c1b6"
MUTED = "#8f8d84"
GRID = "#2f2f2a"
BASELINE = "#3a3a34"

TEAM_OFFICIAL = {
    "LG 트윈스": "#C30452", "두산 베어스": "#1A1748", "KIA 타이거즈": "#EA0029",
    "삼성 라이온즈": "#074CA1", "롯데 자이언츠": "#041E42", "SSG 랜더스": "#CE0E2D",
    "NC 다이노스": "#315288", "KT 위즈": "#000000", "키움 히어로즈": "#570514",
    "한화 이글스": "#FC4E00",
}
# 게시판 등 임의 카테고리용 팔레트(다크에서 선명)
GENERIC_HUES = ["#2a78d6", "#1baf7a", "#eda100", "#e34948", "#9085e9",
                "#eb6834", "#e87ba4", "#00a0b0", "#c98500", "#8f8d84"]


def viz_color(hex_color: str, min_l: float = 0.52, min_s: float = 0.45) -> str:
    """다크 표면에서 보이도록 최소 밝기/채도 보정(hue 유지)."""
    r, g, b = to_rgb(hex_color)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    if s < 0.08:
        l = max(l, 0.62)
    else:
        l = max(l, min_l)
        s = max(s, min_s)
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


TEAM_COLOR = {t: viz_color(TEAM_OFFICIAL[t]) for t in scraper.TEAMS}
LG_COLOR = TEAM_COLOR["LG 트윈스"]


def team_seq(hex_color: str) -> LinearSegmentedColormap:
    """막대용 순차 램프. 값 낮음=연함 → 높음=진함(짙음)."""
    r, g, b = to_rgb(hex_color)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    pale = colorsys.hls_to_rgb(h, 0.82, max(0.30, s * 0.55))
    light = colorsys.hls_to_rgb(h, 0.68, max(0.45, s * 0.85))
    deep = colorsys.hls_to_rgb(h, max(0.42, l * 0.85), s)
    return LinearSegmentedColormap.from_list("teamseq", [pale, light, hex_color, deep])


def team_tints(hex_color: str) -> ListedColormap:
    """워드클라우드 단일 카테고리용 밝기 변주."""
    r, g, b = to_rgb(hex_color)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return ListedColormap([colorsys.hls_to_rgb(h, x, s)
                           for x in (0.50, 0.60, 0.70, 0.80, 0.88)])


def text_on(hex_color: str) -> str:
    r, g, b = to_rgb(hex_color)
    return "#111111" if (0.2126 * r + 0.7152 * g + 0.0722 * b) > 0.6 else "#ffffff"


matplotlib.rcParams.update({
    "font.family": _FONT_FAMILY, "axes.unicode_minus": False,
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "text.color": INK, "axes.labelcolor": INK2, "xtick.color": MUTED,
    "ytick.color": MUTED, "axes.edgecolor": BASELINE,
})


def chrome(ax, ygrid: bool = True):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(BASELINE)
    if ygrid:
        ax.grid(axis="y", color=GRID, linewidth=0.9, zorder=0)
    ax.tick_params(length=0, labelsize=9)
    return ax


st.set_page_config(page_title="KBO 커뮤니티 트렌드 분석", page_icon="⚾", layout="wide")

SOURCES = {"MLBpark KBO타운": "mlbpark", "쌍둥이마당 (LG 팬카페)": "cafe"}
PERIODS = {f"{d}일": d for d in range(1, 8)}   # 1~7일
TEAM_NAMES = list(scraper.TEAMS.keys())

# ------------------------------------------------------------------ 사이드바
st.sidebar.title("⚾ 분석 설정")
source_label = st.sidebar.radio("데이터 소스", list(SOURCES.keys()))
source = SOURCES[source_label]
st.sidebar.caption("※ Instagram/YouTube는 접근 제한(로그인·차단)으로 지원 예정.")

period_label = st.sidebar.radio("기간", list(PERIODS.keys()), horizontal=True, index=2)
period_days = PERIODS[period_label]
st.sidebar.markdown("---")

sel_teams: list[str] = []
include_body = False
body_cap = 300
exclude_noise = True
if source == "mlbpark":
    sel_teams = st.sidebar.multiselect("구단 선택 (복수 가능)", TEAM_NAMES, default=["LG 트윈스"])
    max_pages = st.sidebar.slider("팀당 최대 수집 페이지 (1p=30건)", 5, 200, 30, step=5)
    include_body = st.sidebar.checkbox(
        "본문 내용까지 포함 (느림)", value=False,
        help="글마다 상세 페이지를 1건씩 더 요청. 요청량이 커 짧은 기간 권장.")
    body_cap = st.sidebar.slider("본문 수집 상한(글 수)", 100, 800, 300, step=50,
                                 disabled=not include_body)
else:
    st.sidebar.caption(f"카페: **{naver_cafe.CAFE_NAME}** · 팀 필터 없음(LG 전용)")
    max_pages = st.sidebar.slider("최대 수집 페이지 (1p=50건)", 5, 200, 40, step=5)
    exclude_noise = st.sidebar.checkbox(
        "운영/거래/응원방 게시판 제외", value=True,
        help="자기소개·등업, 티켓 양도·티켓팅 정보, 굿즈, 응원마당(응원방), "
             "야구 말고 사는 이야기, Q&A, 이벤트 릴레이 등을 제외. "
             "→ 쌍둥이마당·언론에서보는 트윈스·칼럼 등 토론 글 위주로 분석.")
    st.sidebar.caption("※ 댓글 '내용'은 회원 전용(로그인 필요)이라 제외. 제목·댓글수·게시판 기준 분석.")

st.sidebar.markdown("---")
exclude_teamnames = st.sidebar.checkbox("워드클라우드에서 팀명/약칭 제외", value=True)
extra_sw_raw = st.sidebar.text_input("추가 불용어 (쉼표로 구분)", value="")
extra_sw = {s for s in extra_sw_raw.split(",")} if extra_sw_raw else set()
run = st.sidebar.button("🔍 수집 & 분석", type="primary", use_container_width=True)


# ------------------------------------------------------------------ 데이터 수집
@st.cache_data(show_spinner=False, ttl=600)
def load_mlbpark(teams, period_days, max_pages, include_body, body_cap):
    prog = st.progress(0.0, text="수집 준비 중...")
    total = len(teams) * max_pages
    state = {"done": 0}

    def cb(team, page, mx, msg):
        state["done"] += 1
        prog.progress(min(state["done"] / max(total, 1), 1.0), text=msg)

    df, meta = scraper.scrape(list(teams), period_days, max_pages=max_pages, progress_cb=cb)
    if include_body and not df.empty:
        def bcb(done, tot):
            prog.progress(min(done / max(tot, 1), 1.0), text=f"본문 수집 {done}/{tot}")
        df, meta["body"] = scraper.attach_bodies(df, max_posts=body_cap, progress_cb=bcb)
    prog.empty()
    return df, meta


@st.cache_data(show_spinner=False, ttl=600)
def load_cafe(period_days, max_pages):
    prog = st.progress(0.0, text="수집 준비 중...")

    def cb(page, mx, msg):
        prog.progress(min(page / max(mx, 1), 1.0), text=msg)

    df, meta = naver_cafe.scrape(period_days, max_pages=max_pages, progress_cb=cb)
    prog.empty()
    return df, meta


st.title("KBO 커뮤니티 트렌드 분석")
tag = ""
if source == "mlbpark":
    tag = f"구단: **{', '.join(sel_teams) or '없음'}**" + (" · 본문 포함" if include_body else "")
else:
    tag = f"카페: **쌍둥이마당**"
st.caption(f"소스: **{source_label}** · 기간: **{period_label}** · {tag}")

if run:
    if source == "mlbpark":
        if not sel_teams:
            st.warning("구단을 최소 1개 이상 선택하세요.")
            st.stop()
        st.session_state["data"] = ("mlbpark",
                                    load_mlbpark(tuple(sel_teams), period_days, max_pages,
                                                 include_body, body_cap))
    else:
        st.session_state["data"] = ("cafe", load_cafe(period_days, max_pages))

data = st.session_state.get("data")
if not data:
    st.info("좌측에서 소스·기간을 고르고 **수집 & 분석**을 누르세요.")
    st.stop()

data_source, (df, meta) = data
if data_source != source:
    st.info("소스를 바꿨습니다. **수집 & 분석**을 다시 눌러주세요.")
    st.stop()
df = df.copy()

# ------------------------------------------------------------------ 소스별 카테고리 정의
if source == "mlbpark":
    df = df[df["team"].isin(sel_teams)]
    CATCOL, CAT_LABEL = "team", "팀"
    sel_cats = [t for t in TEAM_NAMES if t in sel_teams]
    cat_color = dict(TEAM_COLOR)
    cat_order = [t for t in TEAM_NAMES if t in sel_cats]
else:
    if exclude_noise:
        df = df[~df["board"].str.strip().isin(naver_cafe.NOISE_BOARDS)]
    CATCOL, CAT_LABEL = "board", "게시판"
    counts = df["board"].value_counts()
    cat_order = list(counts.index)
    sel_cats = cat_order
    cat_color = {b: viz_color(GENERIC_HUES[i % len(GENERIC_HUES)])
                 for i, b in enumerate(cat_order)}

if df.empty:
    st.warning("해당 조건에 수집된 글이 없습니다. 기간/설정을 바꿔 다시 시도하세요.")
    st.stop()

df["day"] = df["date"].dt.date
if "body" in df.columns:
    df["_text"] = (df["title"].fillna("") + " " + df["body"].fillna("")).str.strip()
else:
    df["_text"] = df["title"]

# 경고/안내
if source == "mlbpark":
    capped = [t for t, m in meta["per_team"].items()
              if m.get("cap_reached") and t in sel_teams]
    if capped:
        st.warning(f"⚠️ {', '.join(capped)} 은(는) 페이지 상한({max_pages}p)에 걸려 "
                   f"기간 전체를 못 덮었을 수 있습니다(최근 글 기준).")
    if meta.get("body"):
        bm = meta["body"]
        note = f"📄 본문 분석 포함 · 대상 글 {bm['unique_posts']:,}개(신규 {bm['fetched']:,}건)"
        if bm.get("capped"):
            note += f" · 상한({body_cap}) 초과분은 최신 글 위주"
        st.caption(note)
else:
    if meta.get("cap_reached"):
        st.warning(f"⚠️ 페이지 상한({max_pages}p)에 걸려 기간 전체를 못 덮었을 수 있습니다"
                   f"(최근 글 기준). 상한을 늘리면 더 과거까지 수집.")

# ------------------------------------------------------------------ 요약 지표
c1, c2, c3, c4 = st.columns(4)
c1.metric("총 게시글", f"{df['id'].nunique():,}")
c2.metric("일평균", f"{df['id'].nunique() / max(df['day'].nunique(), 1):.0f}")
c3.metric("총 댓글", f"{int(df['comments'].sum()):,}")
c4.metric("수집 기간", f"{df['day'].min()} ~ {df['day'].max()}")

stopwords = analyzer.build_stopwords(exclude_teamnames, extra_sw)

tabs = st.tabs(["📈 게시글 추이", f"🥧 {CAT_LABEL}별 점유율", "☁️ 워드클라우드",
                "📊 상위 키워드", "📉 키워드 추이", "🏅 선수 랭킹",
                "🔥 급상승 키워드", "💬 화제 글", "🔎 글 검색"])


def scope_selector(key: str):
    """범위 라디오. 카테고리가 1개면 라디오를 숨긴다."""
    if len(sel_cats) <= 1:
        return (sel_cats[0] if sel_cats else "전체"), df
    view = st.radio("범위", ["전체"] + sel_cats, horizontal=True, key=key)
    sub = df if view == "전체" else df[df[CATCOL] == view]
    return view, sub


def common_window(d: pd.DataFrame):
    """여러 팀 비교 시 모두가 공통 수집한 기간으로 맞춘다(MLBpark 팀 커버리지 보정용).
    카페는 한 피드에서 함께 수집하므로 보정하지 않는다."""
    if source != "mlbpark" or d[CATCOL].nunique() <= 1:
        return d, None
    start = d.groupby(CATCOL)["date"].min().max()
    return d[d["date"] >= start], (start.date() if start > d["date"].min() else None)


def wc_color_for(view: str):
    if view == "전체":
        return ListedColormap([cat_color[c] for c in cat_order]) if cat_order \
            else team_tints(LG_COLOR)
    return team_tints(cat_color.get(view, LG_COLOR))


@st.fragment
def wordcloud_fragment():
    st.subheader("워드클라우드")
    view, sub = scope_selector("wc_scope")
    freq = analyzer.word_frequencies(sub["_text"].tolist(), stopwords)
    wc = analyzer.make_wordcloud(freq, colormap=wc_color_for(view), background=SURFACE)
    if wc is None:
        st.info("표시할 단어가 없습니다.")
        return
    fig, ax = plt.subplots(figsize=(11, 5.4))
    ax.imshow(wc, interpolation="bilinear")
    ax.axis("off")
    fig.tight_layout(pad=0)
    st.pyplot(fig)
    plt.close(fig)
    src = "제목+본문" if "body" in df.columns else "제목"
    st.caption(f"{src} {len(sub):,}건 기준 · 상위 {min(len(freq), 120)}개 단어")


@st.fragment
def keyword_bar_fragment():
    st.subheader("상위 언급 키워드")
    top_n = st.slider("표시 개수", 10, 40, 20, key="topn")
    view, sub = scope_selector("bar_scope")
    base = LG_COLOR if view == "전체" else cat_color.get(view, LG_COLOR)
    bar_cmap = team_seq(base)
    freq = analyzer.word_frequencies(sub["_text"].tolist(), stopwords)
    items = freq.most_common(top_n)
    if not items:
        st.info("표시할 단어가 없습니다.")
        return
    words = [w for w, _ in items][::-1]
    counts = [c for _, c in items][::-1]
    cmax, cmin = max(counts), min(counts)
    span = max(cmax - cmin, 1)
    colors = [bar_cmap(0.18 + 0.82 * (c - cmin) / span) for c in counts]
    fig, ax = plt.subplots(figsize=(10, max(3.2, top_n * 0.32)))
    bars = ax.barh(words, counts, color=colors, height=0.72, zorder=3)
    for s in ("top", "right", "left", "bottom"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0, labelsize=10)
    ax.set_xlim(0, cmax * 1.12)
    ax.xaxis.set_visible(False)
    for bar, c in zip(bars, counts):
        ax.text(bar.get_width() + cmax * 0.012, bar.get_y() + bar.get_height() / 2,
                str(c), va="center", ha="left", fontsize=9, color=INK2)
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)
    st.caption("막대 색이 진할수록 언급 빈도가 높음.")


@st.fragment
def hot_posts_fragment():
    st.subheader("화제 글 Top")
    metric = st.radio("정렬 기준", ["댓글 수", "추천 수"] if "likes" in df.columns else ["댓글 수"],
                      horizontal=True, key="hotmetric")
    n = st.slider("개수", 10, 50, 20, key="hotn")
    sort_col = "likes" if metric == "추천 수" else "comments"
    hot = _dedupe_by_id(df).sort_values(sort_col, ascending=False).head(n)
    _posts_table(hot)
    if source == "mlbpark":
        st.caption("작성일시는 최근(당일) 글만 시간까지, 과거 글은 날짜만 제공됩니다(출처 특성).")


def _fmt_dt(ts):
    """작성일시: 자정(시간 미상)은 날짜만, 그 외는 시간까지."""
    if ts.hour == 0 and ts.minute == 0 and ts.second == 0:
        return ts.strftime("%Y-%m-%d")
    return ts.strftime("%Y-%m-%d %H:%M")


def _dedupe_by_id(d: pd.DataFrame) -> pd.DataFrame:
    """같은 글이 여러 팀에 걸린 경우 id로 합치고 팀을 묶어 표기(MLBpark)."""
    if source == "mlbpark":
        teams_by_id = d.groupby("id")["team"].apply(lambda s: ", ".join(sorted(set(s))))
        u = d.drop_duplicates("id").copy()
        u[CATCOL] = u["id"].map(teams_by_id)
        return u
    return d.drop_duplicates("id").copy()


def _posts_table(res: pd.DataFrame):
    res = res.copy()
    res["작성"] = res["date"].apply(_fmt_dt)
    cols = ["작성", CATCOL, "title", "comments"] + \
           (["likes"] if "likes" in res.columns else []) + ["url"]
    ren = {CATCOL: CAT_LABEL, "title": "제목", "comments": "댓글", "likes": "추천", "url": "링크"}
    st.dataframe(res[cols].rename(columns=ren), hide_index=True, use_container_width=True,
                 column_config={"링크": st.column_config.LinkColumn("바로가기", display_text="열기")})


@st.fragment
def search_fragment():
    st.subheader("특정 텍스트가 포함된 글 찾기")
    src = "제목·본문" if "body" in df.columns else "제목"
    q = st.text_input(f"검색어 ({src}에서 검색 · 쉼표로 여러 개 = OR)",
                      key="searchq", placeholder="예: 오스틴, 홍창기")
    if not q.strip():
        st.info(f"검색어를 입력하면 {src}에 그 텍스트가 포함된 글을 찾습니다.")
        return
    terms = [t.strip() for t in q.split(",") if t.strip()]
    text = df["_text"].fillna("").str.lower()
    mask = pd.Series(False, index=df.index)
    for t in terms:
        mask |= text.str.contains(t.lower(), regex=False)
    res = _dedupe_by_id(df[mask])

    c1, c2 = st.columns([1, 2])
    c1.metric("검색 결과", f"{len(res):,}건")
    if len(terms) > 1:
        per = {t: int(text.str.contains(t.lower(), regex=False).sum()) for t in terms}
        c2.caption("검색어별 매칭(중복 포함): " +
                   " · ".join(f"**{t}** {n:,}" for t, n in per.items()))
    if res.empty:
        st.warning("일치하는 글이 없습니다. 다른 검색어를 시도해 보세요.")
        return
    sort = st.radio("정렬", ["최신순", "댓글 많은순"], horizontal=True, key="searchsort")
    res = res.sort_values("date" if sort == "최신순" else "comments", ascending=False)
    _posts_table(res)
    st.caption(f"'{q}' 포함 글 {len(res):,}건 (기간·소스 필터 적용됨).")


@st.fragment
def rising_fragment():
    st.subheader("급상승 키워드 (기간 전반부 → 후반부)")
    _, sub = scope_selector("rise_scope")
    rising = analyzer.rising_keywords(sub, stopwords, top_n=15, text_col="_text")
    if rising.empty:
        st.info("급상승 키워드를 계산할 데이터가 부족합니다. (기간/수집량을 늘려보세요)")
        return
    disp = rising.copy()
    disp["증가"] = disp.apply(
        lambda r: "🆕 신규" if r["early"] == 0 else f"×{r['score']:.1f}", axis=1)
    disp = disp.rename(columns={"word": "단어", "early": "전반부", "late": "후반부"})
    st.dataframe(disp[["단어", "전반부", "후반부", "증가"]], hide_index=True,
                 use_container_width=True)
    st.caption("후반부(기간 뒤쪽 절반)에 최소 3회 이상 등장한 단어 중, "
               "전반부(앞쪽 절반) 대비 언급이 급증한 순. '🆕 신규'=전반부 0회.")


LINE_COLORS = [viz_color(h) for h in GENERIC_HUES]


@st.cache_data(ttl=21600, show_spinner=False)   # 6시간 캐시(로스터는 자주 안 바뀜)
def get_lg_roster():
    return lg_roster.get_roster()


def _hbar(words, counts, cmap):
    """가로 막대(빈도 그라데이션 + 값 라벨) 공통 렌더."""
    cmax, cmin = max(counts), min(counts)
    span = max(cmax - cmin, 1)
    colors = [cmap(0.18 + 0.82 * (c - cmin) / span) for c in counts]
    fig, ax = plt.subplots(figsize=(10, max(3.0, len(words) * 0.33)))
    ax.barh(words, counts, color=colors, height=0.72, zorder=3)
    for s in ("top", "right", "left", "bottom"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0, labelsize=10)
    ax.set_xlim(0, cmax * 1.12)
    ax.xaxis.set_visible(False)
    for yi, c in enumerate(counts):
        ax.text(c + cmax * 0.012, yi, str(c), va="center", fontsize=9, color=INK2)
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)


@st.fragment
def keyword_trend_fragment():
    st.subheader("키워드 언급 추이 · 연관어")
    src = "제목·본문" if "body" in df.columns else "제목"
    # 기본값: 현재 데이터의 상위 키워드 10개 자동 세팅.
    # 위젯 key에 데이터 시그니처를 붙여, 새 분석 때마다 상위 10개로 갱신되고
    # 같은 데이터 안에서 사용자가 수정하면 그 값이 유지되도록 한다.
    top10 = [w for w, _ in analyzer.word_frequencies(df["_text"].tolist(), stopwords).most_common(10)]
    sig = f"{source}_{period_days}_{len(df)}"
    q = st.text_input(f"키워드 ({src} · 쉼표로 여러 개 · 기본=상위 10개 자동)",
                      value=", ".join(top10), key=f"ktq_{sig}", placeholder="예: 오스틴, 홍창기")
    terms = [t.strip() for t in q.split(",") if t.strip()]
    if not terms:
        st.info("키워드를 입력하세요.")
        return
    low = df["_text"].fillna("").str.lower()
    days_all = sorted(df["day"].unique())
    fig, ax = plt.subplots(figsize=(11, 4.0))
    hit = False
    for i, t in enumerate(terms):
        m = low.str.contains(t.lower(), regex=False)
        if not m.any():
            continue
        hit = True
        s = df[m].groupby("day").size().reindex(days_all, fill_value=0)
        ax.plot(days_all, s.values, color=LINE_COLORS[i % len(LINE_COLORS)], lw=2.4,
                marker="o", ms=5, label=t, markeredgecolor=SURFACE, markeredgewidth=1.0,
                zorder=3, solid_capstyle="round")
    if not hit:
        plt.close(fig)
        st.warning("해당 키워드가 포함된 글이 없습니다.")
        return
    chrome(ax)
    ax.set_ylim(bottom=0)
    step = max(1, len(days_all) // 10)
    ax.set_xticks(days_all[::step])
    ax.set_xticklabels([d.strftime("%m.%d") for d in days_all[::step]])
    ax.legend(frameon=False, fontsize=9, ncol=min(len(terms), 5), loc="upper center",
              bbox_to_anchor=(0.5, 1.14), labelcolor=INK)
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)
    st.caption("각 키워드가 포함된 글 수(일별).")
    st.markdown("**연관 키워드** — 아래 키워드와 함께 자주 등장한 단어")
    focus = st.selectbox("기준 키워드", terms, key="cofocus")
    co = analyzer.co_occurrence(df["_text"].tolist(), focus, stopwords, top_n=20)
    if not co:
        st.info("연관어를 뽑을 데이터가 부족합니다.")
        return
    _hbar([w for w, _ in co][::-1], [c for _, c in co][::-1], team_seq(LG_COLOR))
    st.caption(f"'{focus}' 글에서 함께 많이 등장한 단어(글 단위 집계).")


@st.fragment
def player_rank_fragment():
    st.subheader("LG 선수·인물 언급 랭킹")
    roster, official = get_lg_roster()
    src_note = ("공식 홈페이지 1군 로스터 자동 등록" if official
                else "공식 페이지 연결 실패 → 최근 스냅샷 사용")
    sig = f"{len(roster)}_{roster[0] if roster else 'x'}"   # 로스터 바뀌면 기본값 갱신
    names_raw = st.text_area(f"대상 명단 ({src_note} · 편집 가능)", value=", ".join(roster),
                             key=f"roster_{sig}", height=90)
    names = [n.strip() for n in names_raw.replace("\n", ",").split(",") if n.strip()]
    if not names:
        st.info("명단을 입력하세요.")
        return
    top_n = st.slider("표시 인원", 5, 30, 15, key="rostern")
    low = df["_text"].fillna("").str.lower()
    counts = {n: int(low.str.contains(n.lower(), regex=False).sum()) for n in names}
    counts = {k: v for k, v in counts.items() if v > 0}
    if not counts:
        st.warning("언급된 대상이 없습니다.")
        return
    ranked = sorted(counts.items(), key=lambda x: x[1])[-top_n:]   # 오름차순(막대 아래→위)
    _hbar([k for k, _ in ranked], [v for _, v in ranked], team_seq(LG_COLOR))
    src = "제목·본문" if "body" in df.columns else "제목"
    st.caption(f"각 인물명이 {src}에 포함된 글 수. 색이 진할수록 많이 언급됨. "
               "명단은 LG 공식 1군 로스터에서 자동 등록되며, 위 칸에서 직접 편집할 수 있습니다.")


# ------------------------------------------------------------------ 1) 일별 추이
with tabs[0]:
    st.subheader("일별 게시글 수 추이")
    dfc, trim_start = common_window(df)
    # MLBpark: 팀별 라인 / 카페: 게시판이 많아 전체 단일 라인(게시판 비중은 점유율 탭)
    multi = source == "mlbpark" and len(cat_order) > 1
    fig, ax = plt.subplots(figsize=(11, 4.2))
    if multi:
        daily = (dfc.assign(day=dfc["date"].dt.date)
                 .groupby(["day", CATCOL]).size().reset_index(name="count"))
        pivot = daily.pivot(index="day", columns=CATCOL, values="count").fillna(0).sort_index()
        cols = [c for c in cat_order if c in pivot.columns]
        for cat in cols:
            y = pivot[cat]
            ax.plot(pivot.index, y, color=cat_color[cat], linewidth=2.4, marker="o",
                    markersize=5, label=cat, zorder=3, markeredgecolor=SURFACE,
                    markeredgewidth=1.0, solid_capstyle="round")
            ax.fill_between(pivot.index, y, color=cat_color[cat], alpha=0.06, zorder=1)
        ax.legend(frameon=False, fontsize=9, ncol=min(len(cols), 5), loc="upper center",
                  bbox_to_anchor=(0.5, 1.14), labelcolor=INK)
        days = list(pivot.index)
    else:
        daily = dfc.assign(day=dfc["date"].dt.date).groupby("day").size().sort_index()
        y = daily.values
        ax.plot(daily.index, y, color=LG_COLOR, linewidth=2.6, marker="o", markersize=5.5,
                zorder=3, markeredgecolor=SURFACE, markeredgewidth=1.0, solid_capstyle="round")
        ax.fill_between(daily.index, y, color=LG_COLOR, alpha=0.16, zorder=1)
        for xi, yi in zip(daily.index, y):
            ax.annotate(f"{int(yi)}", (xi, yi), textcoords="offset points",
                        xytext=(0, 6), ha="center", fontsize=8.5, color=INK2)
        days = list(daily.index)
    chrome(ax)
    ax.set_ylim(bottom=0)
    step = max(1, len(days) // 10)
    ax.set_xticks(days[::step])
    ax.set_xticklabels([d.strftime("%m.%d") for d in days[::step]])
    ax.margins(x=0.03)
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)
    cap = "스파이크 = 경기 승패·이슈로 화제량이 급증한 날."
    if trim_start:
        cap += f" · 비교를 위해 공통 수집 기간(**{trim_start} 이후**)으로 맞췄습니다."
    st.caption(cap)

# ------------------------------------------------------------------ 2) 카테고리별 점유율
with tabs[1]:
    st.subheader(f"{CAT_LABEL}별 게시글 점유율")
    dfc, trim_start = common_window(df)
    if trim_start:
        st.caption(f"공통 수집 기간(**{trim_start} 이후**) 기준(수집량 차이 보정).")
    share = (dfc.groupby(CATCOL).size().reset_index(name="count")
             .sort_values("count", ascending=False))
    # 게시판이 너무 많으면 상위 7개 + 기타
    if len(share) > 8:
        top = share.head(7)
        etc = pd.DataFrame([{CATCOL: "기타", "count": share["count"][7:].sum()}])
        share = pd.concat([top, etc], ignore_index=True)
    left, right = st.columns([1, 1])
    with left:
        colors = [cat_color.get(c, MUTED) for c in share[CATCOL]]
        fig, ax = plt.subplots(figsize=(5.2, 5.2))
        wedges, _, autotexts = ax.pie(
            share["count"], colors=colors, autopct="%1.0f%%", startangle=90,
            counterclock=False, pctdistance=0.79,
            wedgeprops={"width": 0.42, "edgecolor": SURFACE, "linewidth": 2})
        for t, col in zip(autotexts, colors):
            t.set_color(text_on(col)); t.set_fontsize(9); t.set_fontweight("bold")
        ax.text(0, 0, f"{int(share['count'].sum()):,}\n글", ha="center", va="center",
                fontsize=16, fontweight="bold", color=INK)
        ax.legend(wedges, share[CATCOL], frameon=False, fontsize=9,
                  loc="center left", bbox_to_anchor=(0.98, 0.5), labelcolor=INK)
        ax.axis("equal")
        fig.tight_layout()
        st.pyplot(fig)
        plt.close(fig)
    with right:
        st.dataframe(share.rename(columns={CATCOL: CAT_LABEL, "count": "글 수"}),
                     hide_index=True, use_container_width=True)

# ------------------------------------------------------------------ fragment 탭들
with tabs[2]:
    wordcloud_fragment()
with tabs[3]:
    keyword_bar_fragment()
with tabs[4]:
    keyword_trend_fragment()
with tabs[5]:
    player_rank_fragment()
with tabs[6]:
    rising_fragment()
with tabs[7]:
    hot_posts_fragment()
with tabs[8]:
    search_fragment()

st.divider()
with st.expander("원본 데이터 보기 / 다운로드"):
    base_cols = ["date", CATCOL, "title", "comments"] + \
                (["reads", "likes"] if source == "cafe" else []) + ["url"]
    st.dataframe(df[base_cols], hide_index=True, use_container_width=True, height=300)
    st.download_button("CSV 다운로드", df.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"{source}_analysis.csv", mime="text/csv")
