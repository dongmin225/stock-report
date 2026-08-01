import os
import csv
import html
import json
import subprocess
import requests
import yfinance as yf
from pykrx import stock as krx_stock
from datetime import datetime, timedelta, timezone
from anthropic import Anthropic
from youtube_transcript_api import YouTubeTranscriptApi

# ==== 여기에 본인 키 값들을 입력하세요 ====
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID") or "PLACEHOLDER"
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET") or "PLACEHOLDER"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY") or "PLACEHOLDER"
KAKAO_REST_API_KEY = os.environ.get("KAKAO_REST_API_KEY") or "PLACEHOLDER"
KAKAO_REFRESH_TOKEN = os.environ.get("KAKAO_REFRESH_TOKEN") or "PLACEHOLDER"
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY") or "PLACEHOLDER"
GITHUB_PAGES_URL = "https://dongmin225.github.io/stock-report/"  # 본인 주소로 확인!
# ==========================================

client = Anthropic(api_key=ANTHROPIC_API_KEY)

YOUTUBE_CHANNELS = {
    "소수몽키": "UCC3yfxS5qC6PCwDzetUuEWg",
    "올랜도킴": "UCwSSqi-s0wcH6pJbH3YPZqQ",
}


def get_current_price(ticker):
    data = yf.Ticker(ticker).history(period="1d")
    if not data.empty:
        return data["Close"].iloc[-1]

    code = ticker.replace(".KS", "").replace(".KQ", "")
    today = datetime.today().strftime("%Y%m%d")
    week_ago = (datetime.today() - timedelta(days=7)).strftime("%Y%m%d")

    try:
        df = krx_stock.get_market_ohlcv(week_ago, today, code)
        if not df.empty:
            return df["종가"].iloc[-1]
    except Exception:
        pass
    return None


def get_news(query, count=5):
    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }
    params = {"query": query, "display": count, "sort": "date"}
    response = requests.get(url, headers=headers, params=params)
    items = response.json().get("items", [])

    news_list = []
    for item in items:
        title = html.unescape(item["title"].replace("<b>", "").replace("</b>", ""))
        description = html.unescape(item["description"].replace("<b>", "").replace("</b>", ""))
        link = item.get("link", "#")
        news_list.append({"title": title, "description": description, "link": link})
    return news_list


def get_uploads_playlist_id(channel_id):
    url = "https://www.googleapis.com/youtube/v3/channels"
    params = {
        "key": YOUTUBE_API_KEY,
        "id": channel_id,
        "part": "contentDetails",
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        items = response.json().get("items", [])
    except Exception:
        return None
    if not items:
        return None
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def get_channel_recent_videos(channel_id, hours=24, max_results=10):
    playlist_id = get_uploads_playlist_id(channel_id)
    if not playlist_id:
        return []

    url = "https://www.googleapis.com/youtube/v3/playlistItems"
    params = {
        "key": YOUTUBE_API_KEY,
        "playlistId": playlist_id,
        "part": "snippet",
        "maxResults": max_results,
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        items = response.json().get("items", [])
    except Exception:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    videos = []
    for item in items:
        published_str = item["snippet"]["publishedAt"]
        published_dt = datetime.strptime(published_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if published_dt < cutoff:
            continue
        video_id = item["snippet"]["resourceId"]["videoId"]
        title = item["snippet"]["title"]
        videos.append({
            "video_id": video_id,
            "title": title,
            "url": f"https://www.youtube.com/watch?v={video_id}"
        })
    return videos


def get_transcript_text(video_id, max_chars=3000):
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=["ko", "en"])
        full_text = " ".join([t["text"] for t in transcript])
        return full_text[:max_chars]
    except Exception:
        return None


def collect_youtube_summary():
    all_videos = []
    for channel_name, channel_id in YOUTUBE_CHANNELS.items():
        videos = get_channel_recent_videos(channel_id, hours=24)
        for v in videos:
            transcript = get_transcript_text(v["video_id"])
            if transcript:
                all_videos.append({
                    "channel": channel_name,
                    "title": v["title"],
                    "url": v["url"],
                    "transcript": transcript
                })

    if not all_videos:
        return "(최근 24시간 내 새로 올라온 영상이 없습니다)", []

    combined_text = "\n\n".join(
        f"[{v['channel']}] {v['title']}\n내용: {v['transcript']}" for v in all_videos
    )

    prompt = f"""다음은 최근 24시간 동안 '소수몽키'와 '올랜도킴' 유튜브 채널에 올라온 영상 자막입니다.

{combined_text}

이 내용을 종합해서, 오늘의 미국/한국 증시 시황과 두 분이 언급한 주요 종목/이슈를 
6~8문장으로 요약해줘. 특정 종목에 대한 매수/매도 의견을 언급했다면 그것도 포함해줘.
마크다운 기호(*, # 등) 없이 순수 텍스트로만 답변해줘."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=700,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text.strip(), all_videos


def get_ai_opinion(stock_name, profit_rate, news_list, youtube_summary):
    if news_list:
        news_text = "\n\n".join(
            f"제목: {n['title']}\n요약: {n['description']}" for n in news_list
        )
    else:
        news_text = "(관련 뉴스 없음)"

    prompt = f"""다음은 '{stock_name}' 종목 정보입니다.

현재 수익률: {profit_rate:+.2f}%

최근 뉴스 (제목+요약):
{news_text}

오늘의 유튜브(소수몽키, 올랜도킴) 시황 요약:
{youtube_summary}

위 정보를 종합해서 매수/보유/매도 중 어떤 의견인지, 근거를 포함해서
4~6문장으로 답변해줘. 유튜브 시황 요약이 이 종목과 직접 관련 없다면 굳이 언급하지 않아도 돼.
참고용 의견이라는 전제이며, 마크다운 기호(*, # 등) 없이 순수 텍스트로만 답변해줘."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text.strip()


def get_kakao_access_token():
    url = "https://kauth.kakao.com/oauth/token"
    data = {
        "grant_type": "refresh_token",
        "client_id": KAKAO_REST_API_KEY,
        "refresh_token": KAKAO_REFRESH_TOKEN
    }
    response = requests.post(url, data=data)
    result = response.json()
    return result["access_token"]


def get_verdict_emoji(profit_rate):
    if profit_rate <= -15:
        return "🔴", "손실 확대"
    elif profit_rate >= 15:
        return "🟢", "수익 양호"
    else:
        return "⚪", "보합"


def build_html_report(results, youtube_summary, youtube_videos):
    today_str = datetime.today().strftime("%Y년 %m월 %d일")

    yt_video_links = ""
    for v in youtube_videos:
        yt_video_links += f'<li><a href="{v["url"]}" target="_blank">▶️ [{v["channel"]}] {v["title"]}</a></li>'

    cards = ""
    for r in results:
        emoji, status = get_verdict_emoji(r["profit_rate"]) if r["profit_rate"] is not None else ("⚠️", "조회실패")

        news_html = ""
        for n in r.get("news", []):
            news_html += f'''
            <li><a href="{n['link']}" target="_blank">📰 {n['title']}</a>
            <p class="desc">{n['description']}</p></li>'''

        rate_display = f"{r['profit_rate']:+.2f}%" if r["profit_rate"] is not None else "조회 실패"
        rate_color = "red" if (r["profit_rate"] or 0) < 0 else "green"

        cards += f'''
        <div class="card">
            <h2>{emoji} {r['name']} <span class="rate" style="color:{rate_color}">{rate_display}</span></h2>
            <p class="opinion">{r.get('opinion', '')}</p>
            <h3>관련 뉴스</h3>
            <ul class="news-list">{news_html or "<li>없음</li>"}</ul>
        </div>'''

    html_content = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>포트폴리오 리포트 - {today_str}</title>
<style>
    body {{ font-family: -apple-system, 'Malgun Gothic', sans-serif; background: #f4f5f7; margin: 0; padding: 16px; }}
    h1 {{ font-size: 20px; color: #222; }}
    .card {{ background: white; border-radius: 12px; padding: 16px; margin-bottom: 16px; box-shadow: 0 1px 4px rgba(0,0,0,0.1); }}
    .card h2 {{ font-size: 17px; margin: 0 0 8px 0; }}
    .card h3 {{ font-size: 13px; color: #888; margin: 14px 0 6px 0; border-top: 1px solid #eee; padding-top: 10px; }}
    .rate {{ font-size: 15px; float: right; }}
    .opinion {{ font-size: 14px; line-height: 1.6; color: #333; white-space: pre-line; }}
    .news-list {{ list-style: none; padding: 0; margin: 0; }}
    .news-list li {{ margin-bottom: 8px; }}
    .news-list a {{ font-size: 13px; color: #1a73e8; text-decoration: none; }}
    .news-list .desc {{ font-size: 12px; color: #777; margin: 2px 0 0 0; }}
    .yt-card {{ background: #fff8e1; border-radius: 12px; padding: 16px; margin-bottom: 16px; }}
    .yt-card h2 {{ font-size: 16px; margin: 0 0 8px 0; }}
    .footer {{ font-size: 12px; color: #999; text-align: center; margin-top: 20px; }}
</style>
</head>
<body>
<h1>📊 {today_str} 포트폴리오 리포트</h1>

<div class="yt-card">
    <h2>🎥 오늘의 유튜브 시황 요약</h2>
    <p class="opinion">{youtube_summary}</p>
    <h3 style="font-size:13px;color:#888;margin-top:12px;">참고 영상</h3>
    <ul class="news-list">{yt_video_links or "<li>최근 24시간 내 영상 없음</li>"}</ul>
</div>

{cards}
<p class="footer">⚠️ 본 의견은 참고용이며, 실제 투자 결정은 본인의 판단과 책임 하에 이루어져야 합니다.</p>
</body>
</html>"""
    return html_content


def push_to_github():
    # 1. 원격의 최신 상태를 가져오기
    subprocess.run(["git", "fetch", "origin", "main"], check=True)
    # 2. 로컬 브랜치 포인터를 원격과 맞추되, 방금 만든 index.html 등 작업 파일은 그대로 유지
    subprocess.run(["git", "reset", "--mixed", "origin/main"], check=True)
    # 3. 새로 생성된 index.html을 추가해서 커밋
    subprocess.run(["git", "add", "-f", "index.html"], check=True)
    subprocess.run(["git", "commit", "-m", f"리포트 업데이트 {datetime.today().strftime('%Y-%m-%d')}"], check=False)
    # 4. push (이제 항상 원격 기준으로 최신이라 충돌 없이 성공함)
    subprocess.run(["git", "push", "origin", "main"], check=True)

def send_kakao_message(text, link_url):
    access_token = get_kakao_access_token()
    url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
    headers = {"Authorization": f"Bearer {access_token}"}
    template = {
        "object_type": "text",
        "text": text,
        "link": {"web_url": link_url, "mobile_web_url": link_url},
        "button_title": "리포트 보기"
    }
    data = {"template_object": json.dumps(template, ensure_ascii=False)}
    response = requests.post(url, headers=headers, data=data)
    return response.status_code, response.json()


def main():
    with open("portfolio.csv", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        portfolio = list(reader)

    print("유튜브 시황 수집 중...")
    youtube_summary, youtube_videos = collect_youtube_summary()
    print(f"유튜브 영상 {len(youtube_videos)}건 수집 완료")

    results = []

    for row in portfolio:
        ticker = row["종목코드"]
        name = row["종목명"]
        avg_price = float(row["매수단가"])

        current_price = get_current_price(ticker)
        if current_price is None:
            results.append({"name": name, "profit_rate": None, "opinion": "", "news": []})
            print(f"[{name}] 조회 실패")
            continue

        profit_rate = (current_price - avg_price) / avg_price * 100
        news = get_news(name)
        opinion = get_ai_opinion(name, profit_rate, news, youtube_summary)

        results.append({"name": name, "profit_rate": profit_rate, "opinion": opinion, "news": news})
        print(f"[{name}] {profit_rate:+.2f}% 처리 완료")

    html_report = build_html_report(results, youtube_summary, youtube_videos)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_report)
    print("index.html 생성 완료")

    push_to_github()
    print("GitHub 업로드 완료")

    today_str = datetime.today().strftime("%Y-%m-%d")
    status, result = send_kakao_message(
        f"📊 {today_str} 포트폴리오 리포트가 준비됐어요!\n버튼을 눌러 확인하세요.",
        GITHUB_PAGES_URL
    )
    print(f"카카오톡 발송: {status} / {result}")


if __name__ == "__main__":
    main()