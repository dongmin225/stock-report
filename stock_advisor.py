import os
import csv
import html
import json
import subprocess
import requests
import yfinance as yf
from pykrx import stock as krx_stock
from datetime import datetime, timedelta
from anthropic import Anthropic

# ==== 여기에 본인 키 값들을 입력하세요 ====
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID") or "PLACEHOLDER"
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET") or "PLACEHOLDER"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY") or "PLACEHOLDER"
KAKAO_REST_API_KEY = os.environ.get("KAKAO_REST_API_KEY") or "PLACEHOLDER"
KAKAO_REFRESH_TOKEN = os.environ.get("KAKAO_REFRESH_TOKEN") or "PLACEHOLDER"
GITHUB_PAGES_URL = "https://dongmin225.github.io/stock-report/"  # 본인 주소로 확인!
# ==========================================

client = Anthropic(api_key=ANTHROPIC_API_KEY)


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


def get_ai_opinion(stock_name, profit_rate, news_list):
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

위 정보를 종합해서 매수/보유/매도 중 어떤 의견인지, 근거가 되는 뉴스 내용까지 포함해서
4~6문장으로 답변해줘. 참고용 의견이라는 전제이며, 마크다운 기호(*, # 등) 없이 순수 텍스트로만 답변해줘."""

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


def build_html_report(results):
    today_str = datetime.today().strftime("%Y년 %m월 %d일")

    cards = ""
    for r in results:
        emoji, status = get_verdict_emoji(r["profit_rate"]) if r["profit_rate"] is not None else ("⚠️", "조회실패")

        news_html = ""
        for n in r.get("news", []):
            news_html += f'''
            <li>
                <a href="{n['link']}" target="_blank">{n['title']}</a>
                <p class="desc">{n['description']}</p>
            </li>'''

        rate_display = f"{r['profit_rate']:+.2f}%" if r["profit_rate"] is not None else "조회 실패"
        rate_color = "red" if (r["profit_rate"] or 0) < 0 else "green"

        cards += f'''
        <div class="card">
            <h2>{emoji} {r['name']} <span class="rate" style="color:{rate_color}">{rate_display}</span></h2>
            <p class="opinion">{r.get('opinion', '')}</p>
            <ul class="news-list">{news_html}</ul>
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
    .rate {{ font-size: 15px; float: right; }}
    .opinion {{ font-size: 14px; line-height: 1.6; color: #333; white-space: pre-line; }}
    .news-list {{ list-style: none; padding: 0; margin-top: 12px; border-top: 1px solid #eee; padding-top: 8px; }}
    .news-list li {{ margin-bottom: 8px; }}
    .news-list a {{ font-size: 13px; color: #1a73e8; text-decoration: none; }}
    .news-list .desc {{ font-size: 12px; color: #777; margin: 2px 0 0 0; }}
    .footer {{ font-size: 12px; color: #999; text-align: center; margin-top: 20px; }}
</style>
</head>
<body>
<h1>📊 {today_str} 포트폴리오 리포트</h1>
{cards}
<p class="footer">⚠️ 본 의견은 참고용이며, 실제 투자 결정은 본인의 판단과 책임 하에 이루어져야 합니다.</p>
</body>
</html>"""
    return html_content


def push_to_github():
    subprocess.run(["git", "add", "-f", "index.html"], check=True)
    subprocess.run(["git", "commit", "-m", f"리포트 업데이트 {datetime.today().strftime('%Y-%m-%d')}"], check=False)
    subprocess.run(["git", "push", "origin", "main"], check=True)


def send_kakao_message(text, link_url):
    access_token = get_kakao_access_token()
    url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
    headers = {"Authorization": f"Bearer {access_token}"}
    template = {
        "object_type": "text",
        "text": text,
        "link": {
            "web_url": link_url,
            "mobile_web_url": link_url
        },
        "button_title": "리포트 보기"
    }
    data = {"template_object": json.dumps(template, ensure_ascii=False)}
    response = requests.post(url, headers=headers, data=data)
    return response.status_code, response.json()


def main():
    with open("portfolio.csv", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        portfolio = list(reader)

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
        opinion = get_ai_opinion(name, profit_rate, news)

        results.append({"name": name, "profit_rate": profit_rate, "opinion": opinion, "news": news})
        print(f"[{name}] {profit_rate:+.2f}% 처리 완료")

    html_report = build_html_report(results)
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