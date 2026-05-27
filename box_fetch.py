#!/usr/bin/env python3
"""
박스오피스 데이터 수집기 — KOBIS Open API + 네이버 영화 포스터
Usage: python box_fetch.py
Output: box_data.json

API 키 발급: https://www.kobis.or.kr/kobisopenapi/homepg/apiService/searchServiceInfo.do
"""

import json
import os
import urllib.request
import urllib.parse
from datetime import datetime, timedelta

# ── API 키 ────────────────────────────────────────────────────────────────────
KOBIS_KEY = os.environ.get('KOBIS_KEY', '')  # GitHub Secret: KOBIS_KEY 설정 필요

DAILY_URL  = 'https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json'
WEEKLY_URL = 'https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchWeeklyBoxOfficeList.json'

BASE_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'


# ── KOBIS API ─────────────────────────────────────────────────────────────────
def kobis_get(url: str) -> dict:
    req = urllib.request.Request(url, headers={'User-Agent': BASE_UA})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode('utf-8'))


def fetch_daily(target_dt: str) -> list:
    """일별 박스오피스 TOP 10"""
    url = f'{DAILY_URL}?key={KOBIS_KEY}&targetDt={target_dt}&itemPerPage=10'
    try:
        data  = kobis_get(url)
        movies = data['boxOfficeResult']['dailyBoxOfficeList']
        print(f'[Daily] {target_dt}: {len(movies)}편')
        return movies
    except Exception as e:
        print(f'[Daily] 오류: {e}')
        return []


def fetch_weekly(target_dt: str, week_gb: str = '0') -> list:
    """주간 박스오피스 TOP 10"""
    url = f'{WEEKLY_URL}?key={KOBIS_KEY}&targetDt={target_dt}&weekGb={week_gb}&itemPerPage=10'
    try:
        data   = kobis_get(url)
        movies = data['boxOfficeResult']['weeklyBoxOfficeList']
        print(f'[Weekly] {target_dt}: {len(movies)}편')
        return movies
    except Exception as e:
        print(f'[Weekly] 오류: {e}')
        return []


# ── 포스터 수집 (네이버 영화 현재 상영작 + 개별 검색) ─────────────────────────
def fetch_posters(titles: list, cached: dict) -> dict:
    """
    네이버 영화에서 포스터 URL 수집.
    cached: 이미 수집된 {영화명: url} — 있으면 재사용
    반환: {영화명: poster_url}
    """
    missing = [t for t in titles if t not in cached]
    if not missing:
        print('[Poster] 모두 캐시됨')
        return cached

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('[Poster] playwright 미설치 — 포스터 생략')
        return cached

    result = dict(cached)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=['--no-sandbox'])
            page = browser.new_page(user_agent=BASE_UA)

            # ① 현재 상영작 페이지에서 한 번에 수집
            print('[Poster] 네이버 영화 현재 상영작 로딩...')
            page.goto('https://movie.naver.com/movie/running/current.naver',
                      wait_until='networkidle', timeout=20000)

            poster_map = page.evaluate('''() => {
                const map = {};
                document.querySelectorAll('img').forEach(img => {
                    if (img.src.includes('pstatic') &&
                        img.alt && img.alt.length > 1 &&
                        !img.alt.includes('N페이') &&
                        !img.alt.includes('링크') &&
                        !img.alt.includes('클립') &&
                        !img.alt.includes('favicon')) {
                        map[img.alt] = img.src;
                    }
                });
                return map;
            }''')

            for title in missing:
                if title in poster_map:
                    result[title] = poster_map[title]
                    print(f'[Poster] ✓ {title}')
                else:
                    print(f'[Poster] 현상작 미검색 → 개별 검색: {title}')

            # ② 현상작에 없는 영화는 개별 검색
            still_missing = [t for t in missing if t not in result]
            for title in still_missing:
                try:
                    q   = urllib.parse.quote(title)
                    url = f'https://movie.naver.com/movie/search/result.naver?query={q}'
                    page.goto(url, wait_until='networkidle', timeout=15000)
                    src = page.evaluate(f'''() => {{
                        const imgs = [...document.querySelectorAll('img')];
                        // alt가 정확히 일치
                        let m = imgs.find(i => i.alt === `{title}`);
                        if (!m) m = imgs.find(i => i.src.includes('pstatic.net/common') && i.alt.length > 1);
                        return m ? m.src : null;
                    }}''')
                    if src:
                        result[title] = src
                        print(f'[Poster] ✓ {title} (검색)')
                    else:
                        print(f'[Poster] ✗ {title} — 포스터 없음')
                except Exception as e:
                    print(f'[Poster] ✗ {title}: {e}')

            browser.close()

    except Exception as e:
        print(f'[Poster] Playwright 오류: {e}')

    return result


# ── 포스터 병합 ───────────────────────────────────────────────────────────────
def attach_posters(movies: list, poster_map: dict) -> None:
    """movie 리스트에 poster_url 필드 추가 (in-place)"""
    for m in movies:
        m['poster_url'] = poster_map.get(m['movieNm'], '')


# ── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    if not KOBIS_KEY:
        print('[ERROR] KOBIS_KEY가 설정되지 않았습니다.')
        return

    today = datetime.now()

    # 일별: 전날 기준
    yesterday = (today - timedelta(days=1)).strftime('%Y%m%d')

    # 주간: 가장 최근 완료된 주 (지난 일요일 기준)
    days_since_sun = (today.weekday() + 1) % 7
    last_sunday    = (today - timedelta(days=days_since_sun)).strftime('%Y%m%d')

    daily  = fetch_daily(yesterday)
    weekly = fetch_weekly(last_sunday)

    # 기존 포스터 캐시 재사용
    cached_posters = {}
    try:
        with open('box_data.json', encoding='utf-8') as f:
            prev = json.load(f)
        for m in prev.get('daily', []) + prev.get('weekly', []):
            if m.get('poster_url'):
                cached_posters[m['movieNm']] = m['poster_url']
        print(f'[Poster] 캐시 {len(cached_posters)}편 로드')
    except Exception:
        pass

    # 포스터 수집 (누락분만)
    all_titles  = list({m['movieNm'] for m in daily + weekly})
    poster_map  = fetch_posters(all_titles, cached_posters)

    attach_posters(daily,  poster_map)
    attach_posters(weekly, poster_map)

    result = {
        'updated':     today.strftime('%Y-%m-%dT%H:%M:%S'),
        'daily_date':  yesterday,
        'weekly_date': last_sunday,
        'daily':       daily,
        'weekly':      weekly,
    }

    with open('box_data.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    got = sum(1 for m in daily + weekly if m.get('poster_url'))
    print(f'저장 완료: box_data.json  일별 {len(daily)}편 / 주간 {len(weekly)}편 / 포스터 {got}개')


if __name__ == '__main__':
    main()
