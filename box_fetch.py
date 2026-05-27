#!/usr/bin/env python3
"""
박스오피스 데이터 수집기 — KOBIS Open API
Usage: python box_fetch.py
Output: box_data.json

API 키 발급: https://www.kobis.or.kr/kobisopenapi/homepg/apiService/searchServiceInfo.do
"""

import json
import urllib.request
from datetime import datetime, timedelta

# ── API 키 설정 ───────────────────────────────────────────────────────────────
import os
KOBIS_KEY = os.environ.get('KOBIS_KEY', '')  # GitHub Secret: KOBIS_KEY 설정 필요

DAILY_URL  = 'https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json'
WEEKLY_URL = 'https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchWeeklyBoxOfficeList.json'


# ── API 요청 ──────────────────────────────────────────────────────────────────
def kobis_get(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={'User-Agent': 'Mozilla/5.0'},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode('utf-8'))


def fetch_daily(target_dt: str) -> list:
    """일별 박스오피스 TOP 10"""
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
    """주간 박스오피스 TOP 10 (weekGb: 0=전체, 1=주중, 2=주말)"""
    url = f'{WEEKLY_URL}?key={KOBIS_KEY}&targetDt={target_dt}&weekGb={week_gb}&itemPerPage=10'
    try:
        data = kobis_get(url)
        movies = data['boxOfficeResult']['weeklyBoxOfficeList']
        print(f'[Weekly] {target_dt}: {len(movies)}편')
        return movies
    except Exception as e:
        print(f'[Weekly] 오류: {e}')
        return []


# ── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    if not KOBIS_KEY:
        print('[ERROR] KOBIS_KEY가 설정되지 않았습니다.')
        print('  kobis.or.kr 에서 API 키 발급 후 box_fetch.py 상단에 입력하세요.')
        return

    today = datetime.now()

    # 일별: 전날 기준 (오전 집계 기준)
    yesterday = (today - timedelta(days=1)).strftime('%Y%m%d')

    # 주간: 가장 최근 완료된 주 (지난 일요일 기준)
    days_since_sun = (today.weekday() + 1) % 7
    last_sunday = (today - timedelta(days=days_since_sun)).strftime('%Y%m%d')

    daily  = fetch_daily(yesterday)
    weekly = fetch_weekly(last_sunday)

    result = {
        'updated':     today.strftime('%Y-%m-%dT%H:%M:%S'),
        'daily_date':  yesterday,
        'weekly_date': last_sunday,
        'daily':       daily,
        'weekly':      weekly,
    }

    with open('box_data.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f'저장 완료: box_data.json  일별 {len(daily)}편 / 주간 {len(weekly)}편')


if __name__ == '__main__':
    main()
