# KBO 커뮤니티 트렌드 분석 대시보드

MLBpark KBO타운 / 네이버 카페 쌍둥이마당(LG 팬카페)의 글을 수집해
워드클라우드·키워드·게시글 추이·화제 글을 시각화하는 Streamlit 대시보드.

## 기능
- **데이터 소스 선택**: MLBpark KBO타운 / 쌍둥이마당
- **기간**: 1~7일
- MLBpark: KBO 10개 구단 복수 선택(공식 구단색), 제목/본문 분석
- 쌍둥이마당: 게시판별 분석(운영/거래 게시판 제외 옵션)
- 워드클라우드, 상위·급상승 키워드, 일별 추이, 점유율, 화제 글

## 로컬 실행
```bash
pip install -r requirements.txt
python -m streamlit run app.py
```
Windows는 맑은 고딕(malgun.ttf), 리눅스/맥은 나눔·애플고딕을 자동 인식합니다.

## 배포 (Streamlit Community Cloud)
- `requirements.txt` : 파이썬 의존성
- `packages.txt` : `fonts-nanum` (리눅스 한글 폰트)
- 진입점: `app.py`

## 참고 / 한계
- 공개 게시판의 **제목·댓글수·게시판** 기준 분석입니다.
- 네이버 카페 **댓글/본문 텍스트**는 회원 전용이라 수집하지 않습니다.
- 외부 사이트를 스크레이핑하므로, 호스팅 IP가 차단·지오블록되면 수집이 실패할 수 있습니다.
