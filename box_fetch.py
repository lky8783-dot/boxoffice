#!/usr/bin/env python3
"""
박스오피스 데이터 수집기 — KOBIS Open API + 네이버 영화 포스터/줄거리
Usage: python box_fetch.py
Output: box_data.json
"""

import json
import os
import urllib.request
import urllib.parse
from datetime import datetime, timedelta

KOBIS_KEY = os.environ.get('KOBIS_KEY', '')

DAILY_URL  = 'https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json'
WEEKLY_URL = 'https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchWeeklyBoxOfficeList.json'
INFO_URL   = 'https://www.kobis.or.kr/kobisopenapi/webservice/rest/movie/searchMovieInfo.json'

BASE_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
           'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')


# ── KOBIS API ─────────────────────────────────────────────────────────────────
def kobis_get(url: str) -> dict:
    req = urllib.request.Request(url, headers={'User-Agent': BASE_UA})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode('utf-8'))


def fetch_daily(target_dt: str) -> list:
    url = f'{DAILY_URL}?key={KOBIS_KEY}&targetDt={target_dt}&itemPerPage=10'
    try:
        data = kobis_get(url)
        movies = data['boxOfficeResult']['dailyBoxOfficeList']
        print(f'[Daily] {target_dt}: {len(movies)}편')
        return movies
    except Exception as e:
        print(f'[Daily] 오류: {e}')
        return []


def fetch_weekly(target_dt: str, week_gb: str = '0') -> list:
    url = f'{WEEKLY_URL}?key={KOBIS_KEY}&targetDt={target_dt}&weekGb={week_gb}&itemPerPage=10'
    try:
        data = kobis_get(url)
        movies = data['boxOfficeResult']['weeklyBoxOfficeList']
        print(f'[Weekly] {target_dt}: {len(movies)}편')
        return movies
    except Exception as e:
        print(f'[Weekly] 오류: {e}')
        return []


def fetch_movie_info(movie_cd: str) -> dict:
    """KOBIS 영화 상세 — 감독, 배우, 장르, 런타임, 등급"""
    url = f'{INFO_URL}?key={KOBIS_KEY}&movieCd={movie_cd}'
    try:
        data = kobis_get(url)
        info = data['movieInfoResult']['movieInfo']
        return {
            'directors': [d['peopleNm'] for d in info.get('directors', [])],
            'actors':    [a['peopleNm'] for a in info.get('actors', [])[:5]],
            'genres':    [g['genreNm']  for g in info.get('genres', [])],
            'nations':   [n['nationNm'] for n in info.get('nations', [])],
            'rating':    next((a['watchGradeNm'] for a in info.get('audits', [])), ''),
            'runtime':   info.get('showTm', ''),
            'movieNmEn': info.get('movieNmEn', ''),
        }
    except Exception as e:
        print(f'[Info] {movie_cd}: {e}')
        return {}


# ── 네이버 검색 — 포스터 + 줄거리 ────────────────────────────────────────────
def fetch_naver_details(titles: list, cached: dict) -> dict:
    """
    search.naver.com 지식패널에서 영화별 포스터 URL + 줄거리 수집.
    반환: { 영화명: {poster_url, synopsis} }
    """
    # 포스터 OR 줄거리 OR 평점 없으면 다시 수집
    missing = [t for t in titles
               if t not in cached
               or not cached[t].get('poster_url')
               or not cached[t].get('synopsis')
               or 'naver_rating' not in cached[t]]
    if not missing:
        print('[Naver] 모두 캐시됨')
        return cached

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('[Naver] playwright 미설치')
        return cached

    result = dict(cached)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=['--no-sandbox'])
            page = browser.new_page(user_agent=BASE_UA)

            # ① 네이버 영화 현재 상영작 페이지 — 포스터만 (정확한 매칭)
            print('[Naver] 현재 상영작 포스터 로딩...')
            page.goto('https://movie.naver.com/movie/running/current.naver',
                      wait_until='networkidle', timeout=20000)
            running_map = page.evaluate('''() => {
                const m = {};
                document.querySelectorAll("img").forEach(img => {
                    if (img.src.includes("pstatic") &&
                        img.alt && img.alt.length > 1 &&
                        !img.alt.includes("N페이") &&
                        !img.alt.includes("링크") &&
                        !img.alt.includes("클립")) {
                        m[img.alt] = img.src;
                    }
                });
                return m;
            }''')

            for title in missing:
                cached_poster  = (cached.get(title) or {}).get('poster_url', '')
                cached_syn     = (cached.get(title) or {}).get('synopsis', '')
                cached_rating  = (cached.get(title) or {}).get('naver_rating', '')
                poster       = running_map.get(title, cached_poster)
                synopsis     = cached_syn
                naver_rating = cached_rating

                # ② 네이버 영화 검색 — alt 일치 확인 후 포스터 (오인식 방지)
                if not poster:
                    try:
                        q_title = urllib.parse.quote(title)
                        page.goto(f'https://movie.naver.com/movie/search/result.naver?query={q_title}',
                                  wait_until='networkidle', timeout=20000)
                        page.wait_for_timeout(800)
                        mv_poster = page.evaluate('''(targetTitle) => {
                            const imgs = [...document.querySelectorAll("img[src*=\'pstatic\']")].filter(i =>
                                i.alt && i.alt.length > 1 &&
                                !i.alt.includes("N페이") && !i.alt.includes("이벤트")
                            );
                            // alt 텍스트가 영화 제목과 일치해야만 사용 (추천/광고 포스터 방지)
                            const matched = imgs.find(i =>
                                targetTitle.startsWith(i.alt) ||
                                i.alt === targetTitle ||
                                (i.alt.length >= 3 && targetTitle.includes(i.alt))
                            );
                            return matched ? matched.src : "";
                        }''', title)
                        if mv_poster:
                            poster = mv_poster
                            print(f'[Naver Movie] matched: {title}')
                        else:
                            print(f'[Naver Movie] no match: {title}')
                    except Exception as e:
                        print(f'[Naver Movie] {title}: {e}')

                # ③ 네이버 통합검색 — 줄거리 + 별점 수집
                try:
                    q = urllib.parse.quote(title + ' 영화')
                    page.goto(f'https://search.naver.com/search.naver?where=nexearch&query={q}',
                              wait_until='domcontentloaded', timeout=20000)
                    page.wait_for_timeout(1200)

                    data = page.evaluate('''() => {
                        const syn = document.querySelector(".desc");
                        // 실관람객 평점 우선, 없으면 네티즌 평점
                        // area_star_number 는 <span>8.11<span class="area_star_total_number">10</span></span> 구조
                        const r1 = document.querySelector(".area_star_number");
                        const r2 = document.querySelector(".this_text_bold");
                        let rating = "";
                        if (r1) {
                            // 첫 번째 텍스트 노드만 (자식 span 제외)
                            const tn = [...r1.childNodes].find(n => n.nodeType === 3);
                            rating = tn ? tn.textContent.trim() : r1.textContent.replace(/10$/, "").trim();
                        } else if (r2) {
                            rating = r2.textContent.replace(/[^\\d.]/g, "").trim();
                        }
                        return {
                            synopsis: syn ? syn.textContent.trim().slice(0, 300) : "",
                            naver_rating: rating
                        };
                    }''')

                    if data.get('synopsis'):
                        synopsis = data['synopsis']
                    if data.get('naver_rating'):
                        naver_rating = data['naver_rating']

                except Exception as e:
                    print(f'[Naver] {title} 검색 오류: {e}')

                result[title] = {'poster_url': poster, 'synopsis': synopsis, 'naver_rating': naver_rating}
                status = '✓' if poster else '✗'
                print(f'[Naver] {status} {title}  syn={len(synopsis)}자  rating={naver_rating}')

            browser.close()

    except Exception as e:
        print(f'[Naver] Playwright 오류: {e}')

    return result


# ── 영화 정보 병합 ────────────────────────────────────────────────────────────
def enrich_movies(movies: list, naver_map: dict, info_cache: dict) -> None:
    """movie 리스트에 포스터·줄거리·감독·배우 등 추가 (in-place)"""
    for m in movies:
        title   = m['movieNm']
        nav     = naver_map.get(title, {})
        m['poster_url']   = nav.get('poster_url', '')
        m['synopsis']     = nav.get('synopsis', '')
        m['naver_rating'] = nav.get('naver_rating', '')

        movie_cd = m.get('movieCd', '')
        if movie_cd:
            if movie_cd not in info_cache:
                info_cache[movie_cd] = fetch_movie_info(movie_cd)
            info = info_cache[movie_cd]
            m['directors'] = info.get('directors', [])
            m['actors']    = info.get('actors', [])
            m['genres']    = info.get('genres', [])
            m['nations']   = info.get('nations', [])
            m['rating']    = info.get('rating', '')
            m['runtime']   = info.get('runtime', '')
            m['movieNmEn'] = info.get('movieNmEn', '')


# ── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    if not KOBIS_KEY:
        print('[ERROR] KOBIS_KEY 미설정')
        return

    today      = datetime.now()
    yesterday  = (today - timedelta(days=1)).strftime('%Y%m%d')
    days_sun   = (today.weekday() + 1) % 7
    last_sunday = (today - timedelta(days=days_sun)).strftime('%Y%m%d')

    daily  = fetch_daily(yesterday)
    weekly = fetch_weekly(last_sunday)

    # ── 기존 캐시 로드 ─────────────────────────────────────────────────────
    naver_cache = {}   # {영화명: {poster_url, synopsis}}
    info_cache  = {}   # {movieCd: {directors, actors, ...}}
    try:
        with open('box_data.json', encoding='utf-8') as f:
            prev = json.load(f)
        for m in prev.get('daily', []) + prev.get('weekly', []):
            t = m.get('movieNm', '')
            if t:
                naver_cache[t] = {
                    'poster_url':   m.get('poster_url', ''),
                    'synopsis':     m.get('synopsis',   ''),
                    'naver_rating': m.get('naver_rating', ''),
                }
            cd = m.get('movieCd', '')
            if cd and m.get('directors') is not None:
                info_cache[cd] = {
                    'directors': m.get('directors', []),
                    'actors':    m.get('actors', []),
                    'genres':    m.get('genres', []),
                    'nations':   m.get('nations', []),
                    'rating':    m.get('rating', ''),
                    'runtime':   m.get('runtime', ''),
                    'movieNmEn': m.get('movieNmEn', ''),
                }
        print(f'[Cache] 포스터 {len(naver_cache)}편 / 정보 {len(info_cache)}편')
    except Exception:
        pass

    # ── 네이버 상세 수집 (포스터 + 줄거리) ──────────────────────────────────
    all_titles = list({m['movieNm'] for m in daily + weekly})
    naver_map  = fetch_naver_details(all_titles, naver_cache)

    # ── KOBIS 영화 정보 + 병합 ───────────────────────────────────────────────
    enrich_movies(daily,  naver_map, info_cache)
    enrich_movies(weekly, naver_map, info_cache)

    result = {
        'updated':     today.strftime('%Y-%m-%dT%H:%M:%S'),
        'daily_date':  yesterday,
        'weekly_date': last_sunday,
        'daily':       daily,
        'weekly':      weekly,
    }

    with open('box_data.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    posters = sum(1 for m in daily + weekly if m.get('poster_url'))
    syns    = sum(1 for m in daily + weekly if m.get('synopsis'))
    infos   = sum(1 for m in daily + weekly if m.get('directors'))
    print(f'저장 완료: {len(daily)}편일별 / {len(weekly)}편주간 / 포스터:{posters} 줄거리:{syns} 감독:{infos}')


if __name__ == '__main__':
    main()
