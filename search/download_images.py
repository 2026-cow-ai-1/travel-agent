"""shared/place_cards.csv의 image_urls(JSON 배열)로 사진을 내려받는다. API 키는 필요 없다.
파일명: search/images/{place_id}_{번호}.jpg  (번호는 image_urls 안의 순서, 1부터)
이미 받은 파일은 건너뛰므로 중간에 끊겨도 같은 명령으로 이어받는다. 실패한 주소는 search/outputs/failed_downloads.csv에 기록한다.
사진은 분석용이며 git에 올리거나 재배포하지 않는다.

실행 (search/ 폴더가 아닌 프로젝트 맨 위 폴더에서):
  python search/download_images.py             # 전체
  python search/download_images.py --limit 20  # 앞 20곳만 시험
"""
import argparse, io, json, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests
from PIL import Image
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
IMG_DIR = ROOT / "search" / "images"
OUT = ROOT / "search" / "outputs"

ap = argparse.ArgumentParser()
ap.add_argument("--cards", default=str(ROOT / "shared" / "place_cards.csv"))
ap.add_argument("--limit", type=int, help="CSV 앞에서 N개 장소만")
ap.add_argument("--workers", type=int, default=4, help="동시 요청 수 (서버 부담을 줄이려고 적게)")
ap.add_argument("--delay", type=float, default=0.2, help="요청 사이 간격(초, 워커별)")
ap.add_argument("--timeout", type=float, default=10)
ap.add_argument("--retries", type=int, default=2)
a = ap.parse_args()

# keep_default_na=False: 분류 코드 "NA"가 빈 값(NaN)으로 바뀌는 것을 막는다
cards = pd.read_csv(a.cards, dtype=str, keep_default_na=False)
if a.limit:
    cards = cards.head(a.limit)
jobs = []  # (place_id, 번호, url)
for r in cards.itertuples():
    for n, url in enumerate(json.loads(r.image_urls), start=1):
        jobs.append((r.place_id, n, url))
IMG_DIR.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)


def fetch(job):
    pid, n, url = job
    path = IMG_DIR / f"{pid}_{n}.jpg"
    if path.exists():
        return job, "skip", None, 0
    why = None
    for _ in range(a.retries + 1):
        time.sleep(a.delay)
        try:
            r = requests.get(url, timeout=a.timeout)
            if r.status_code != 200:
                why = f"HTTP {r.status_code}"
                continue
            Image.open(io.BytesIO(r.content)).verify()  # 깨진 파일 거르기
            path.write_bytes(r.content)  # 원본 그대로 저장(가공 없음)
            return job, "ok", None, len(r.content)
        except requests.Timeout:
            why = "타임아웃"
        except requests.RequestException as e:
            why = f"요청 오류 {type(e).__name__}"
        except Exception as e:
            why = f"이미지 깨짐 {type(e).__name__}"
    return job, "fail", why, 0


t0 = time.time()
with ThreadPoolExecutor(a.workers) as ex:
    res = list(tqdm(ex.map(fetch, jobs), total=len(jobs)))
sec = time.time() - t0
ok = [r for r in res if r[1] == "ok"]
fail = [r for r in res if r[1] == "fail"]
pd.DataFrame([(j[0], j[1], j[2], w) for j, _, w, _ in fail],
             columns=["place_id", "number", "url", "reason"]).to_csv(OUT / "failed_downloads.csv", index=False)
print(f"장소 {len(cards)}곳 / 사진 주소 {len(jobs)}개 → 새로 받음 {len(ok)}, 이미 있음 {sum(r[1] == 'skip' for r in res)}, 실패 {len(fail)}")
print(f"소요 {sec:.1f}초, 실패 이유: {dict(Counter(w for _, _, w, _ in fail))}")
if ok:
    print(f"평균 용량 {sum(r[3] for r in ok) / len(ok) / 1024:.0f}KB")
