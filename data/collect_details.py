"""장소별 추가 사진 주소(detailImage2)와 소개글(detailCommon2) 수집. 이어받기 가능, 하루 호출 상한 950.

실행 (프로젝트 루트, .env에 TOURAPI_KEY):
  python data/collect_details.py --test 20     # 20곳 시험(호출 25회 이내)
  python data/collect_details.py               # 사진 주소 → 소개글 순서로 수집 (상한까지, 내일 같은 명령으로 이어받기)
  python data/collect_details.py --status      # 진행 현황
  python data/collect_details.py --publish [--allow-missing]  # 진행분을 shared/place_cards.csv로 교체(수동)

수집 중에는 shared/place_cards.csv를 건드리지 않고 data/outputs/place_cards_progress.csv에만 저장한다.
사진 주소 조회가 전부 끝나면 shared를 한 번만 교체한다. 키는 로그·저장 파일에 남기지 않는다(응답 body만 저장).
"""
import argparse, csv, json, sys, time
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from urllib.parse import unquote

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "outputs"
RAW_IMG, RAW_OV = OUT / "raw" / "detailImage2", OUT / "raw" / "detailCommon2"
LOG_OLD, LOG = OUT / "api_call_log.csv", OUT / "api_call_log_detail.csv"
PROGRESS, EXCLUDED = OUT / "place_cards_progress.csv", OUT / "excluded_no_image.csv"
FAILED, RATE_EVENTS = OUT / "failed_places.csv", OUT / "rate_limit_events.csv"
PUBLISHED_MARK = OUT / ".shared_published"
SHARED, BACKUP = ROOT / "shared" / "place_cards.csv", OUT / "place_cards_sample1000.csv"
BASE = "https://apis.data.go.kr/B551011/KorService2/"
DAILY_CAP, MIN_GAP, RETRIES, MAX_CONSEC_FAIL, IMG_ROWS = 950, 0.2, 2, 10, 100
COLS = ["place_id", "name", "region", "latitude", "longitude", "overview", "image_urls", "license_type",
        "image_caption", "lcls1", "lcls2", "lcls3", "addr1"]


class Stop(Exception):
    pass


def read_key():
    for l in open(ROOT / ".env"):
        if l.startswith("TOURAPI_KEY="):
            return l.split("=", 1)[1].strip().strip("\"'")
    raise SystemExit(".env에 TOURAPI_KEY가 없습니다")


KEY = read_key()


def mask(text):
    for k in {KEY, unquote(KEY)}:
        if k:
            text = text.replace(k, "***")
    return text


def calls_today():
    n, today = 0, str(date.today())
    for f in (LOG_OLD, LOG):
        if f.exists():
            n += sum(1 for r in csv.DictReader(open(f)) if r["date"] == today)
    return n


def log_call(endpoint, cid, http, result):
    new = not LOG.exists()
    with open(LOG, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["date", "time", "endpoint", "content_id", "http", "result"])
        w.writerow([date.today(), time.strftime("%H:%M:%S"), endpoint, cid, http, result])


def rate_limit_event(endpoint, http, body):
    new = not RATE_EVENTS.exists()
    with open(RATE_EVENTS, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["datetime", "endpoint", "http", "local_calls_today", "response_head"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), endpoint, http, calls_today(), mask(body)[:300]])


_last = [0.0]


def call(endpoint, cid, extra=None):
    """1회 호출(재시도 포함, 시도마다 한 건으로 센다). 성공하면 응답 JSON, 실패하면 예외 문자열 반환 대신 raise."""
    params = dict(serviceKey=unquote(KEY), MobileOS="ETC", MobileApp="AppTest", _type="json", contentId=cid)
    params.update(extra or {})
    why = ""
    for attempt in range(RETRIES + 1):
        if calls_today() >= DAILY_CAP:
            raise Stop(f"로컬 일일 상한 {DAILY_CAP}회 도달")
        time.sleep(max(0, MIN_GAP - (time.time() - _last[0])))
        _last[0] = time.time()
        try:
            r = requests.get(BASE + endpoint, params=params, timeout=30)
        except requests.RequestException as e:
            log_call(endpoint, cid, "ERR", type(e).__name__)
            why = f"{type(e).__name__}: {mask(str(e))[:120]}"
            continue
        body = r.text
        if r.status_code == 429 or "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS" in body or "<returnReasonCode>22<" in body:
            log_call(endpoint, cid, r.status_code, "RATE_LIMIT")
            rate_limit_event(endpoint, r.status_code, body)
            raise Stop(f"서버 한도 초과 응답(HTTP {r.status_code}) — 중단")
        try:
            j = r.json()
            code = j["response"]["header"]["resultCode"]
        except Exception:
            log_call(endpoint, cid, r.status_code, "BAD_BODY")
            why = f"HTTP {r.status_code} 응답 해석 실패: {mask(body)[:100]}"
            continue
        log_call(endpoint, cid, r.status_code, code)
        if r.status_code == 200 and code == "0000":
            return j
        why = f"HTTP {r.status_code} resultCode {code}"
    raise RuntimeError(why)


def items_of(j):
    it = j["response"]["body"].get("items")
    if not it:
        return []
    it = it.get("item", []) if isinstance(it, dict) else []
    return [it] if isinstance(it, dict) else it


def fetch_images(cid):
    """장소의 모든 이미지 페이지를 받아 {"pages":[...]}로 반환(numOfRows=100, totalCount 초과 시 추가 페이지)."""
    pages, p = [], 1
    while True:
        j = call("detailImage2", cid, dict(numOfRows=IMG_ROWS, pageNo=p, imageYN="Y"))
        pages.append(j)
        total = int(j["response"]["body"].get("totalCount", 0) or 0)
        if p * IMG_ROWS >= total:
            return {"place_id": cid, "pages": pages}
        p += 1


def load_cards():
    c = pd.read_csv(OUT / "place_cards_all.csv", dtype=str, keep_default_na=False)
    order = pd.read_csv(OUT / "sample_order.csv", dtype=str).place_id
    return c.set_index("place_id").loc[order].reset_index()  # sample_order 순서(기존 1,000곳 표본 먼저)


def raw_items(cid):
    f = RAW_IMG / f"{cid}.json"
    if not f.exists():
        return None
    out = []
    for pg in json.loads(f.read_text())["pages"]:
        out += items_of(pg)
    return out


def overview_of(cid):
    f = RAW_OV / f"{cid}.json"
    if not f.exists():
        return None
    it = items_of(json.loads(f.read_text()))
    return it[0].get("overview", "") if it else ""


def build_rows(cards):
    """이미지 조회가 끝난 장소로 장소 카드 행 생성. 대표 이미지(장소 Type1) 먼저 + Type1 추가 이미지, 완전 일치 중복만 제거."""
    rows, excluded, stat = [], [], Counter()
    for r in cards.itertuples():
        items = raw_items(r.place_id)
        if items is None:
            continue
        urls = []
        rep = json.loads(r.image_urls)[0] if r.image_urls else ""
        for u in [rep] + [i.get("originimgurl", "") for i in items if i.get("cpyrhtDivCd") == "Type1"]:
            if u and u not in urls:
                urls.append(u)
        stat["type3_dropped"] += sum(1 for i in items if i.get("cpyrhtDivCd") == "Type3")
        stat["blank_license_dropped"] += sum(1 for i in items if i.get("cpyrhtDivCd") not in ("Type1", "Type3"))
        if not urls:
            excluded.append((r.place_id, r.name))
            continue
        ov = overview_of(r.place_id)
        rows.append(dict(place_id=r.place_id, name=r.name, region=r.region, latitude=r.latitude, longitude=r.longitude,
                         overview=ov or "", image_urls=json.dumps(urls, ensure_ascii=False),
                         license_type=r.license_type, image_caption="", lcls1=r.lcls1, lcls2=r.lcls2,
                         lcls3=r.lcls3, addr1=r.addr1))
    return pd.DataFrame(rows, columns=COLS), excluded, stat


def save_progress(cards):
    df, excluded, stat = build_rows(cards)
    df.to_csv(PROGRESS, index=False)
    pd.DataFrame(excluded, columns=["place_id", "name"]).to_csv(EXCLUDED, index=False)
    return df, excluded, stat


def publish(cards, allow_missing=False, auto=False):
    df, _, _ = save_progress(cards)
    idx = ROOT / "search" / "outputs" / "index_map.csv"
    missing = []
    if idx.exists():
        ids = set(pd.read_csv(idx, dtype=str).place_id)
        missing = sorted(ids - set(df.place_id))
    if missing and not allow_missing:
        print(f"[중단] 기존 검색 인덱스 장소 {len(missing)}곳이 진행분에 없어 교체하면 검색/데모가 KeyError 날 수 있음. "
              f"그래도 올리려면 --publish --allow-missing")
        return False
    if SHARED.exists() and not BACKUP.exists():
        BACKUP.write_bytes(SHARED.read_bytes())
        print(f"기존 shared 백업 → {BACKUP.relative_to(ROOT)}")
    df.to_csv(SHARED, index=False)
    PUBLISHED_MARK.write_text(datetime.now().isoformat(timespec="seconds"))
    print(f"shared/place_cards.csv 교체: {len(df)}곳 ({'자동' if auto else '수동'}), 인덱스 장소 누락 {len(missing)}곳")
    return True


def status(cards):
    n_img = sum(1 for p in cards.place_id if (RAW_IMG / f"{p}.json").exists())
    n_ov = sum(1 for p in cards.place_id if (RAW_OV / f"{p}.json").exists())
    print(f"사진 주소 {n_img}/{len(cards)}곳, 소개글 {n_ov}/{len(cards)}곳, 오늘 호출 {calls_today()}/{DAILY_CAP}")
    return n_img, n_ov


def run_collect(cards, endpoint, raw_dir, fetcher, limit_places=None):
    todo = [p for p in cards.place_id if not (raw_dir / f"{p}.json").exists()]
    if limit_places is not None:
        todo = todo[:limit_places]
    fails, consec, done = [], 0, 0
    stop_reason = None
    try:
        for cid in todo:
            try:
                data = fetcher(cid)
                consec = 0
            except RuntimeError as e:
                fails.append((cid, endpoint, str(e)))
                consec += 1
                if consec >= MAX_CONSEC_FAIL:
                    raise Stop(f"연속 오류 {MAX_CONSEC_FAIL}회 — 중단")
                continue
            raw_dir.mkdir(parents=True, exist_ok=True)
            (raw_dir / f"{cid}.json").write_text(json.dumps(data, ensure_ascii=False))
            done += 1
    except Stop as e:
        stop_reason = str(e)
    return done, fails, stop_reason


def write_failed(fails):
    pd.DataFrame(fails, columns=["place_id", "endpoint", "reason"]).to_csv(FAILED, index=False)


def test_report(sample_ids, n_ov):
    per, lic, dup_within, rep_in_list = [], Counter(), 0, 0
    cards = load_cards().set_index("place_id")
    shapes = None
    for cid in sample_ids:
        items = raw_items(cid) or []
        urls = [i.get("originimgurl", "") for i in items]
        per.append(len(items)); lic.update(i.get("cpyrhtDivCd", "(없음)") for i in items)
        dup_within += len(urls) - len(set(urls))
        rep = json.loads(cards.at[cid, "image_urls"])[0]
        rep_in_list += rep in urls
        if shapes is None and items:
            shapes = sorted(items[0].keys())
    s = pd.Series(per)
    print(f"[이미지] 장소 {len(per)}곳, 장소당 사진 수 평균 {s.mean():.1f} / 최소 {s.min()} / 최대 {s.max()}")
    print(f"[이미지별 라이선스] {dict(lic)}")
    print(f"[중복] 장소 내 중복 URL {dup_within}건, 대표이미지가 추가목록에 이미 포함된 장소 {rep_in_list}/{len(per)}")
    print(f"[응답 형태] item 필드: {shapes}")
    tc = []
    for cid in sample_ids:
        pg = json.loads((RAW_IMG / f"{cid}.json").read_text())["pages"]
        tc.append((int(pg[0]["response"]["body"]["totalCount"]), len(pg)))
    print(f"[totalCount 대비] 페이지 수 최대 {max(p for _, p in tc)} (numOfRows={IMG_ROWS}), totalCount 최대 {max(t for t, _ in tc)}")
    ov = [(cid, overview_of(cid)) for cid in sample_ids[:n_ov]]
    ov = [(c, o) for c, o in ov if o is not None]
    if ov:
        txt = [o for _, o in ov]
        nl = sum("\n" in t for t in txt)
        html = sum(("<" in t and ">" in t) for t in txt)
        print(f"[소개글] {len(txt)}곳, 빈 값 {sum(1 for t in txt if not t)}, 줄바꿈 포함 {nl}, "
              f"HTML 태그(<br> 등) 포함 {html}, 평균 길이 {sum(map(len, txt))/len(txt):.0f}자")
    # 샘플 5개 주소 접근 확인(파일 본문은 받지 않음)
    urls = [u for cid in sample_ids for u in [json.loads(cards.at[cid, 'image_urls'])[0]]][:2]
    extra = [i.get("originimgurl") for cid in sample_ids for i in (raw_items(cid) or [])][2:5]
    for u in urls + extra:
        try:
            r = requests.head(u, timeout=10, allow_redirects=True)
            print(f"[접근] {r.status_code} {u.split('/cms/')[-1][:60]}")
        except requests.RequestException as e:
            print(f"[접근] 실패 {type(e).__name__} {u.split('/cms/')[-1][:60]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", type=int, help="무작위(seed 고정) N곳 시험: 사진 N회 + 소개글 최대 5회")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--allow-missing", action="store_true")
    ap.add_argument("--images-only", action="store_true")
    a = ap.parse_args()
    cards = load_cards()

    if a.status:
        status(cards); return
    if a.publish:
        publish(cards, a.allow_missing); return
    if a.test:
        sample = cards.sample(n=a.test, random_state=0)
        sub = sample.place_id.tolist()
        before = calls_today()
        fails, stop = [], None
        for fetcher, endpoint, raw_dir, ids in ((fetch_images, "detailImage2", RAW_IMG, sub),
                                               (lambda c: call("detailCommon2", c), "detailCommon2", RAW_OV, sub[:5])):
            for cid in ids:
                if (raw_dir / f"{cid}.json").exists():
                    continue
                try:
                    data = fetcher(cid)
                except RuntimeError as e:
                    fails.append((cid, endpoint, str(e))); continue
                except Stop as e:
                    stop = str(e); break
                raw_dir.mkdir(parents=True, exist_ok=True)
                (raw_dir / f"{cid}.json").write_text(json.dumps(data, ensure_ascii=False))
            if stop:
                break
        write_failed(fails)
        print(f"시험 호출 {calls_today() - before}회 사용, 실패 {len(fails)}곳, 중단 사유: {stop}")
        if not fails and not stop:
            test_report(sub, 5)
        print(f"오늘 누적 호출 {calls_today()}/{DAILY_CAP}")
        save_progress(cards)
        return

    # 전체 수집: 사진 주소 → 소개글
    all_fails, stop = [], None
    d1, f1, stop = run_collect(cards, "detailImage2", RAW_IMG, fetch_images)
    all_fails += f1
    print(f"사진 주소 이번 실행 신규 {d1}곳, 실패 {len(f1)}곳")
    n_img, _ = status(cards)
    if n_img == len(cards) and not stop and not a.images_only:
        d2, f2, stop = run_collect(cards, "detailCommon2", RAW_OV, lambda c: call("detailCommon2", c))
        all_fails += f2
        print(f"소개글 이번 실행 신규 {d2}곳, 실패 {len(f2)}곳")
    write_failed(all_fails)
    df, excluded, stat = save_progress(cards)
    n_img, n_ov = status(cards)
    print(f"progress {len(df)}곳 저장, 사진 없어 제외 {len(excluded)}곳, 제외된 이미지(Type3) {stat['type3_dropped']}장, "
          f"라이선스 빈 값 이미지 {stat['blank_license_dropped']}장")
    if stop:
        print(f"[중단] {stop}")
    if n_img == len(cards) and not PUBLISHED_MARK.exists():
        publish(cards, auto=True)
    elif n_img < len(cards):
        print(f"shared는 건드리지 않음. 이어서 실행: python data/collect_details.py")


if __name__ == "__main__":
    main()
