"""단계 1: TourAPI areaBasedList2로 자연관광(lclsSystm1=NA) 관광지 중 대표이미지가 있는 장소를 모은다.
Type1만 data/outputs/place_cards_all.csv에 저장(Type3 변경금지는 제외). 키는 .env의 TOURAPI_KEY에서만 읽는다.
--plan: 1페이지만 호출해 총 건수와 예상 호출 수를 보여주고 종료(응답은 캐시되어 본 실행에서 재사용)."""
import argparse, csv, json, time
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import unquote

import pandas as pd
import requests

URL = "https://apis.data.go.kr/B551011/KorService2/areaBasedList2"
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "outputs"; RAW = OUT / "raw"; LOG = OUT / "api_call_log.csv"
DAILY_LIMIT = 1000

ap = argparse.ArgumentParser()
ap.add_argument("--plan", action="store_true")
ap.add_argument("--rows", type=int, default=1000, help="numOfRows (한 번에 받을 건수)")
ap.add_argument("--target", type=int, default=1000, help="목표 Type1 장소 수")
ap.add_argument("--lcls1", default="NA")
a = ap.parse_args()

key = next((l.split("=", 1)[1].strip().strip("\"'") for l in open(ROOT / ".env") if l.startswith("TOURAPI_KEY=")), "")
if not key: raise SystemExit(".env에 TOURAPI_KEY가 없습니다")
OUT.mkdir(exist_ok=True); RAW.mkdir(exist_ok=True)

def calls_today():
    if not LOG.exists(): return 0
    return sum(1 for r in csv.DictReader(open(LOG)) if r["date"] == str(date.today()))

def fetch(page):
    cache = RAW / f"{a.lcls1}_rows{a.rows}_p{page}.json"
    if cache.exists(): return json.loads(cache.read_text()), False
    if calls_today() >= DAILY_LIMIT: raise SystemExit("오늘 호출 한도 도달 — 중단")
    p = dict(serviceKey=unquote(key), numOfRows=a.rows, pageNo=page, MobileOS="ETC", MobileApp="AppTest",
             _type="json", arrange="Q", contentTypeId=12, lclsSystm1=a.lcls1)
    r = requests.get(URL, params=p, timeout=30)
    new = not LOG.exists()
    with open(LOG, "a", newline="") as f:
        w = csv.writer(f)
        if new: w.writerow(["date", "time", "page", "rows", "http"])
        w.writerow([date.today(), time.strftime("%H:%M:%S"), page, a.rows, r.status_code])
    r.raise_for_status()
    j = r.json()
    if j["response"]["header"]["resultCode"] != "0000": raise SystemExit(f"API 오류: {j['response']['header']}")
    cache.write_text(json.dumps(j, ensure_ascii=False))
    time.sleep(1)
    return j, True

j, _ = fetch(1)
total = j["response"]["body"]["totalCount"]
pages = -(-total // a.rows)
print(f"자연({a.lcls1}) 관광지 중 대표이미지 있는 장소 totalCount={total}, 페이지 {pages}개 → 필요 호출 {pages}회"
      f" (오늘 이미 사용한 기록 {calls_today()}건; 시험 호출 1건은 로그 이전에 별도로 사용 — 합산 {calls_today()+1}건 이상)")
if a.plan: raise SystemExit

items = list(j["response"]["body"]["items"]["item"])
for pg in range(2, pages + 1):
    j2, _ = fetch(pg)
    items += j2["response"]["body"]["items"]["item"]
df = pd.DataFrame(items)
lic = df["cpyrhtDivCd"].value_counts(dropna=False).to_dict()
t1 = df[df["cpyrhtDivCd"] == "Type1"].drop_duplicates("contentid")
stats = {"fetched_total": len(df), "license_counts": lic, "type1_unique": len(t1),
         "natural_code": a.lcls1, "api_calls_logged_today": calls_today()}
(OUT / "collect_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1))
cards = pd.DataFrame({
    "place_id": t1["contentid"], "name": t1["title"],
    "region": t1["addr1"].str.split().str[:2].str.join(" "),  # 주소 앞 두 단어(시도 시군구). 원문은 addr1
    "latitude": t1["mapy"], "longitude": t1["mapx"], "overview": "",
    "image_urls": t1["firstimage"].map(lambda u: json.dumps([u], ensure_ascii=False)),  # JSON 배열 문자열
    "license_type": t1["cpyrhtDivCd"], "image_caption": "",
    "lcls1": t1["lclsSystm1"], "lcls2": t1["lclsSystm2"], "lcls3": t1["lclsSystm3"], "addr1": t1["addr1"]})
cards.to_csv(OUT / "place_cards_all.csv", index=False)  # Type1 전체
order_f = OUT / "sample_order.csv"
if not order_f.exists():
    cards.sample(frac=1, random_state=0)[["place_id"]].to_csv(order_f, index=False)
# shared/place_cards.csv는 여기서 쓰지 않는다 → data/collect_details.py --publish 가 한 번만 교체
print(stats); print(f"Type1 전체 {len(cards)}곳 → data/outputs/place_cards_all.csv")
