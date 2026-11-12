"""추천된 장소에 이동시간을 붙이는 함수 모음.

자동차: self/total/route_tools.py 의 get_travel_time(mode="car", fallback_to_estimate=False) (네이버 Directions 5)
        가까운 도심 구간에서는 직선거리 추정이 실제보다 훨씬 짧게 나와서(예: 46.5분 대신 11.9분),
        틀린 값을 보여 주지 않으려고 구하지 못하면 비워 둔다. 화면이 "이동시간을 불러오지 못했어요"를 보여 준다.
도보:   직선거리 3km 이내인 장소에만 estimate_travel_time(mode="walk") 추정값을 함께 담는다.

같은 (출발지, 장소) 요청은 한 번만 보낸다 (st.cache_data, 성공한 것만).
실패 처리는 세 단계다.
  1. route_tools.py 가 일시적 오류(타임아웃, 연결 오류, HTTP 5xx)에서만 요청 안에서 몇 번 다시 시도한다 (전체 약 12초).
  2. 그래도 실패하면 같은 (출발지, 장소)는 WAIT_AFTER_FAILURE_SECONDS 동안 다시 보내지 않는다.
     대기 중에는 재시도 없이 바로 값 없음으로 처리한다.
  3. 일시적 오류로 끝내 실패하면 같은 추천 묶음의 나머지 장소는 API 를 부르지 않는다.
     (장소마다 최대 약 12초씩 기다리면 추천 3곳에 약 36초가 걸리기 때문. 다음 메시지에서는 다시 시도한다)

최대 이동시간 조건이 있으면 select_by_travel_time 이 후보를 넓게 훑어서 거른다.
  흐름: 사진 1,500장 → 장소 500곳(app.POOL_SIZE) → 직선거리 반경 밖 제외(반경 = 최대 이동시간 × PREFILTER_KMH, 2시간이면 170km) → 남은 곳 중 사진 유사도 상위 SCAN_PLACE_COUNT(50)곳의 자동차 이동시간을 네이버로 조회
  - 반경 선제외는 이동시간 조회를 아끼려는 것이다. 이전에는 "오차가 커서" 쓰지 않았지만, 실호출 실험(서울역·부산역 각 60곳, 직선 50~400km)에서
    관측 최대 직선 속도가 72.6 km/h 였고 반경 밖인데 120분 이내인 곳은 0곳이어서(150km, 200km 모두) 여유 15%를 둔 85 km/h 로 켰다.
    출발지 없음 · 최대 이동시간 없음일 때는 쓰지 않는다.
  - 동시에 MAX_PARALLEL_CALLS 건씩 조회한다 (st.cache_data 는 스레드에서 써도 된다: 같은 요청은 한 번만 실행되고 결과가 공유된다)
  - 제한 이내인 곳이 MIN_ADOPTED_PLACES 곳보다 적으면 SCAN_EXTRA_COUNT 곳을 더 조회한다 (전체 조회는 MAX_TRAVEL_CALLS 건까지)
  - 일시적 오류 · 429(속도 제한) · 인증 오류가 나면 새 요청을 멈추고 지금까지 구한 값으로 진행한다
  - 구한 이동시간은 그대로 챗봇 입력과 추천 카드에 쓴다 (다시 부르지 않는다)
"""

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import streamlit as st

FRONT_DIR = Path(__file__).resolve().parent
TOTAL_DIR = FRONT_DIR.parent / "total"

# 이동시간을 붙이는 추천 장소 수 (최대)
MAX_TRAVEL_PLACES = 3

# 직선거리 반경으로 먼 곳을 미리 뺀다. 반경(km) = 최대 이동시간(시간) × PREFILTER_KMH (2시간이면 170km).
# 85 = 실험 관측 최대 직선 속도 72.6 km/h × 1.15(여유) 를 올림한 값. None 이면 미리 빼지 않는다.
# 근거는 서울역 · 부산역 두 곳, 사진 한 장, 한 시점의 측정이다. 다른 출발지(섬이 많은 지역 등)에서도 맞는지는 확인하지 않았다(미확인).
PREFILTER_KMH = 85

# ── 최대 이동시간 조건으로 후보를 거를 때의 값 (모두 제안한 값이며 근거 있는 숫자가 아니다) ──
# 처음 조회하는 장소 수 (사진 유사도 순). 30 → 50 (후보를 더 넓게 본다. 조회가 늘어 후보 갱신이 약 4~5초 → 8~10초로 늘 것으로 어림, 50곳 실측은 미확인)
SCAN_PLACE_COUNT = 50

# 제한 이내인 곳이 이 수보다 적으면 더 조회한다
MIN_ADOPTED_PLACES = 3

# 더 조회하는 장소 수 (SCAN_PLACE_COUNT 50 + 20 이지만 MAX_TRAVEL_CALLS 가 60 이라 실제로는 최대 10곳)
SCAN_EXTRA_COUNT = 20

# 한 번의 선정에서 조회하는 장소 수의 상한. 이 수에 이르면 부족해도 그대로 진행한다. 50 → 60 (후보 모음 app.POOL_SIZE 60 과 같다)
MAX_TRAVEL_CALLS = 60

# 동시에 보내는 네이버 요청 수
MAX_PARALLEL_CALLS = 4

# 챗봇에 보내는 후보 수. 6 → 9 (화면에 보이는 후보 수 app.TOP_K 와 같아야 한다. 입력 토큰이 약 +25% 늘 것으로 어림)
CHATBOT_CANDIDATE_COUNT = 9

# 직선거리가 이 값(km) 이내인 장소에는 도보 추정도 함께 담는다.
# 이 3km 는 제안한 값이며 근거 없는 가정이다. 걷기 좋은 거리의 기준으로 확인된 것이 없다.
WALK_NEAR_KM = 3

# 성공한 자동차 결과를 기억해 두는 시간(초). 가정값이며 도로 상황 변화는 반영하지 않는다.
CACHE_TTL_SECONDS = 3600

# 재시도까지 모두 실패한 뒤, 같은 요청을 다시 보내기까지 기다리는 시간(초). 가정값이다.
# (route_tools.py 의 요청 안 재시도와는 별개다. 이 시간 동안은 재시도 없이 바로 값 없음으로 처리한다)
WAIT_AFTER_FAILURE_SECONDS = 60

# 추천 한 곳에 붙이는 이동시간 키 (다시 붙이기 전에 지우는 데도 쓴다)
# travel_missing: 자동차 이동시간을 구하지 못했다는 표시 (화면이 "이동시간을 불러오지 못했어요"를 보여 준다)
TRAVEL_KEYS = ("distance_km", "duration_min", "mode", "source", "travels", "travel_missing")

# 네이버 호출이 실패한 시각 (요청 키 -> 시각)
failed_at = {}

# failed_at 에 429(속도 제한)가 난 시각을 적는 특별한 키. 이 시각에서 WAIT_AFTER_FAILURE_SECONDS 동안은 캐시에 없는 요청을 새로 보내지 않는다.
# (장소 단위 대기와 달리 모든 장소에 적용된다. failed_at 안에 있어서 failed_at.clear() 로 함께 초기화된다)
RATE_LIMIT_KEY = "rate_limit"

# 네이버에 실제로 보낸 요청 수 (캐시에 없어서 함수가 실행된 횟수). 여러 스레드가 함께 올리므로 잠금을 쓴다.
api_call_counter = {"count": 0}
api_call_lock = threading.Lock()


# 같은 묶음에서 일시적 오류가 이미 나서 API 를 부르지 않았다는 신호 (오류라서 캐시에 저장되지 않는다)
class CarTimeSkipped(Exception):
    pass


# route_tools.py 를 불러올 수 있게 경로를 한 번 추가
def add_route_path():
    path = str(TOTAL_DIR)
    if path not in sys.path:
        sys.path.insert(0, path)


# 위도, 경도를 route_tools.py 가 받는 딕셔너리로 만드는 함수
def make_point(latitude, longitude):
    return {"latitude": latitude, "longitude": longitude}


# 네이버로 자동차 이동시간을 구하고, 성공한 결과만 캐시에 남기는 함수
# 앞에 밑줄이 붙은 _allow_api 는 캐시 키에 들어가지 않는다 (캐시에 값이 있으면 이 값과 상관없이 그대로 꺼낸다)
@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def get_cached_car_time(origin_latitude, origin_longitude, place_latitude, place_longitude, _allow_api=True):
    # 1. 같은 묶음에서 일시적 오류가 났으면 API 는 부르지 않음
    if not _allow_api:
        raise CarTimeSkipped()

    # 2. 실패하면 추정값 대신 DrivingTimeError 가 난다 (오류는 캐시에 저장되지 않는다)
    add_route_path()
    import route_tools

    with api_call_lock:
        api_call_counter["count"] += 1

    return route_tools.get_travel_time(
        make_point(origin_latitude, origin_longitude),
        make_point(place_latitude, place_longitude),
        mode="car",
        fallback_to_estimate=False,
    )


# 실패한 오류가 속도 제한(429)이나 인증 오류(401, 403)인지 알려 주는 함수. 아니면 빈 글자
# route_tools 는 오류를 DrivingTimeError 로 바꿔 던지지만 원래 오류가 __context__ 에 남아 있어서 상태 코드만 읽는다
# (이 방식은 route_tools 내부 구현에 기대는 것이라, 읽지 못하면 일반 실패로 본다)
def failure_reason(error):
    status = getattr(getattr(error.__context__, "response", None), "status_code", None)
    if status == 429:
        return "rate_limit"
    if status in (401, 403):
        return "auth"
    return ""


# 자동차 이동시간 한 건을 구하는 함수. (결과 또는 None, 일시적 오류로 실패했는지)를 돌려줌
def get_car_time(origin, place, allow_api=True):
    car, transient, _ = lookup_car_time(origin, place, allow_api)
    return car, transient


# get_car_time 과 같지만 실패 이유(rate_limit / auth / "")도 함께 돌려주는 함수
def lookup_car_time(origin, place, allow_api=True):
    key = (
        round(origin["latitude"], 5), round(origin["longitude"], 5),
        round(place["latitude"], 5), round(place["longitude"], 5),
    )

    # 1. 얼마 전에 실패했다면 네이버를 부르지 않고 재시도도 없이 바로 값 없음
    if time.time() - failed_at.get(key, 0) < WAIT_AFTER_FAILURE_SECONDS:
        return None, False, ""

    add_route_path()
    import route_tools

    # 2. 캐시에 있으면 그대로, 없으면 네이버 호출
    # 429 가 난 지 얼마 안 됐으면 새 요청은 보내지 않고(캐시 값만 쓴다) 속도 제한으로 멈췄다고 알린다
    cooling = allow_api and time.time() - failed_at.get(RATE_LIMIT_KEY, 0) < WAIT_AFTER_FAILURE_SECONDS

    try:
        return get_cached_car_time(*key, _allow_api=allow_api and not cooling), False, ""
    except CarTimeSkipped:
        # 3. 같은 묶음에서 건너뛴 것이라 실패로 기록하지 않음 (다음 메시지에서 다시 시도)
        return None, False, ("rate_limit" if cooling else "")
    except route_tools.DrivingTimeError as error:
        # 4. 실패 시각을 기록하고 값 없음 (일시적 오류인지, 속도 제한인지 함께 알림, 예외 내용은 쓰지 않음)
        failed_at[key] = time.time()
        reason = failure_reason(error)
        if reason == "rate_limit":
            failed_at[RATE_LIMIT_KEY] = time.time()
        return None, error.transient, reason


# 직선거리가 가까운 장소에만 도보 추정값을 구하는 함수 (멀면 None)
def get_walk_time(origin, place):
    add_route_path()
    import route_tools

    if route_tools.haversine_km(origin, place) > WALK_NEAR_KM:
        return None

    return route_tools.estimate_travel_time(origin, place, mode="walk")


# 한 장소의 이동시간을 만드는 함수. (이동시간 목록, 자동차 값이 없는지, 일시적 오류로 실패했는지)를 돌려줌
def build_travels(origin, place, allow_api=True):
    travels, car_missing, transient, _ = build_travels_with_reason(origin, place, allow_api)
    return travels, car_missing, transient


# build_travels 와 같지만 실패 이유(rate_limit / auth / "")도 함께 돌려주는 함수
def build_travels_with_reason(origin, place, allow_api=True):
    add_route_path()
    import route_tools

    # 1. 좌표가 올바르지 않으면 이동시간 없이 넘어감 (자동차 값이 없다는 표시도 하지 않는다)
    #    (CSV 에 범위 밖 좌표가 있어도 그 장소를 후보에서 빼지 않고, 이동시간 줄만 생략해서 화면이 끊기지 않게 한다)
    for point in (origin, place):
        if not isinstance(point, dict) or not route_tools.is_valid_coordinate(
            point.get("latitude"), point.get("longitude")
        ):
            return [], False, False, ""

    # 2. 자동차 먼저 (구하지 못하면 비워 둠)
    origin_point = make_point(origin["latitude"], origin["longitude"])
    place_point = make_point(place["latitude"], place["longitude"])
    car, transient, reason = lookup_car_time(origin_point, place_point, allow_api)
    travels = [car] if car is not None else []

    # 3. 직선거리가 가까우면 도보 추정도 함께 (자동차 값이 없어도 담음)
    walk = get_walk_time(origin_point, place_point)
    if walk is not None:
        travels.append(walk)

    return travels, car is None, transient, reason


# 한 장소에 붙일 이동시간 값을 만드는 함수. (값 딕셔너리, 일시적 오류인지, 실패 이유)를 돌려줌
# 값 딕셔너리는 추천 카드에 그대로 합쳐지는 키들이다 (travels, distance_km 등, 자동차 값을 못 구했으면 travel_missing)
def make_travel_fields(origin, place, allow_api=True):
    # 한 장소의 계산이 ValueError 로 실패해도 그 장소의 이동시간만 생략한다
    # (오류가 밖으로 나가면 다른 추천의 이동시간까지 더미 값으로 되돌아가기 때문)
    try:
        travels, car_missing, transient, reason = build_travels_with_reason(origin, place, allow_api)
    except ValueError:
        travels, car_missing, transient, reason = [], False, False, ""

    fields = {}
    if travels:
        fields["travels"] = travels

    # 자동차 값은 맨 위 키에도 둠 (distance_km 등)
    car = next((travel for travel in travels if travel.get("mode") == "car"), None)
    if car is not None:
        fields.update(car)

    if car_missing:
        fields["travel_missing"] = True

    return fields, transient, reason


# 추천 목록의 앞쪽 max_places 곳(기본 3곳)에 이동시간을 붙이는 함수
# allow_api=False 이면 캐시에 있는 값만 쓰고 네이버는 부르지 않는다
def add_travel_time(recommendations, candidates, origin, max_places=MAX_TRAVEL_PLACES, allow_api=True):
    # 1. 후보를 place_id 로 찾을 수 있게 (좌표는 후보에 있음)
    places_by_id = {str(place.get("place_id")): place for place in candidates}

    # 일시적 오류로 한 장소가 끝내 실패하면 False 가 되어, 같은 묶음의 나머지 장소는 API 를 부르지 않는다
    api_allowed = allow_api

    result = []
    for index, item in enumerate(recommendations):
        # 2. 이전 이동시간 값(더미 포함)은 지우고 새로 붙임
        new_item = {key: value for key, value in item.items() if key not in TRAVEL_KEYS}

        # 3. 출발지가 있고 앞쪽 max_places 곳이면 이동시간 붙이기
        place = places_by_id.get(str(item.get("place_id")))
        if origin is not None and place is not None and index < max_places:
            fields, transient, reason = make_travel_fields(origin, place, api_allowed)
            if transient or reason == "rate_limit":  # 일시적 오류 · 429 일 때 멈춘다 (401 같은 오류는 예전처럼 장소마다 시도)
                api_allowed = False
            new_item.update(fields)

        result.append(new_item)

    return result


# 화면에 보이는 후보들의 이동시간을 순서대로 구하는 함수 (최대 이동시간 조건이 없을 때). (장소별 이동시간 값, 멈춘 이유)를 돌려줌
# 일시적 오류나 429 가 나면 나머지 후보는 새로 조회하지 않는다 (멈춘 이유: "transient" / "rate_limit", 없으면 "")
def travel_for_places(places, origin):
    travel_by_id = {}
    stop = ""
    allow_api = True

    for place in places:
        fields, transient, reason = make_travel_fields(origin, place, allow_api)
        travel_by_id[str(place.get("place_id"))] = fields
        if not stop and (transient or reason == "rate_limit"):
            stop = "rate_limit" if reason == "rate_limit" else "transient"
            allow_api = False

    return travel_by_id, stop


# ── 최대 이동시간으로 후보 거르기 ─────────────────────────────

# 좌표가 올바른 장소인지 알려 주는 함수
def has_valid_coordinates(place):
    add_route_path()
    import route_tools

    return route_tools.is_valid_coordinate(place.get("latitude"), place.get("longitude"))


# 장소들의 자동차 이동시간을 동시에(MAX_PARALLEL_CALLS 건씩) 조회하는 함수
# state: 스레드들이 함께 보는 값 {"stop": 멈춘 이유("" 이면 계속), "lock": 잠금, "fields": {place_id: 값}, "skipped": 건너뛴 수}
# 새 요청은 멈춘 뒤에는 보내지 않는다. 이미 보낸 요청은 끝까지 기다린다.
def scan_places(places, origin, state):
    def lookup(place):
        place_id = str(place.get("place_id"))

        # 1. 이미 멈췄으면 새 요청을 보내지 않음 (구하지 못한 것으로 둔다)
        if state["stop"]:
            with state["lock"]:
                state["skipped"] += 1
            return

        fields, transient, reason = make_travel_fields(origin, place, True)

        # 2. 값은 장소별로 따로 담고, 멈출 이유가 생기면 기록 (속도 제한이 일시적 오류보다 우선)
        with state["lock"]:
            state["fields"][place_id] = fields
            if reason == "rate_limit" or (not state["stop"] and (reason or transient)):
                state["stop"] = reason or "transient"

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CALLS) as executor:
        list(executor.map(lookup, places))


# 출발지에서 직선거리가 반경 밖인 장소를 빼는 함수 (이동시간을 조회하기 전에 쓴다). (남은 장소, 뺀 장소 수, 반경 km 또는 None)을 돌려줌
# 반경(km) = max_minutes / 60 × PREFILTER_KMH. PREFILTER_KMH 가 None 이면 아무것도 빼지 않는다.
# places 는 좌표가 올바른 장소여야 한다 (has_valid_coordinates 로 거른 뒤에 부른다)
def prefilter_by_radius(places, origin, max_minutes):
    if not PREFILTER_KMH:
        return list(places), 0, None

    add_route_path()
    import route_tools

    radius_km = max_minutes / 60 * PREFILTER_KMH
    near = [place for place in places if route_tools.haversine_km(origin, place) <= radius_km]
    return near, len(places) - len(near), radius_km


# 자동차 이동시간이 max_minutes 이내인 후보만 골라서 돌려주는 함수 (출발지가 있을 때 사용)
# pool: 사진 유사도 순 후보 목록 / origin: {"latitude", "longitude", ...} / max_minutes: 제한(분)
# 돌려주는 값: {"chosen": 챗봇에 보낼 후보(최대 CHATBOT_CANDIDATE_COUNT 곳), "travel_by_id": {place_id: 이동시간 값},
#             "adopted": 제한 이내인 곳 수, "scanned": 조회한 곳 수, "api_calls": 네이버에 보낸 요청 수(캐시 제외),
#             "failed": 값을 구하지 못한 곳 수, "stop": "" / "transient" / "rate_limit" / "auth", "extra": 추가 조회를 했는지,
#             "seconds": 걸린 시간, "no_match": 제한 이내인 곳이 없는지,
#             "excluded": 직선거리 반경 밖이라 조회하지 않고 뺀 곳 수, "radius_km": 그 반경(PREFILTER_KMH 가 None 이면 None)}
def select_by_travel_time(pool, origin, max_minutes):
    started = time.monotonic()
    calls_before = api_call_counter["count"]

    # 1. 좌표가 이상한 곳은 뺀다. 이어서 직선거리 반경 밖은 미리 뺀다(PREFILTER_KMH). 남은 곳이 유사도 순으로 조회 대상이 된다
    valid = [place for place in pool if has_valid_coordinates(place)]
    eligible, excluded, radius_km = prefilter_by_radius(valid, origin, max_minutes)
    state = {"stop": "", "lock": threading.Lock(), "fields": {}, "skipped": 0}

    def adopted_places():
        found = []
        for place in eligible:
            fields = state["fields"].get(str(place.get("place_id")))
            if fields and fields.get("duration_min") is not None and fields["duration_min"] <= max_minutes:
                found.append(place)
        return found

    # 2. 처음 SCAN_PLACE_COUNT 곳을 동시에 조회
    first = eligible[:min(SCAN_PLACE_COUNT, MAX_TRAVEL_CALLS)]
    scan_places(first, origin, state)

    # 3. 제한 이내인 곳이 부족하면 SCAN_EXTRA_COUNT 곳을 더 조회 (전체 MAX_TRAVEL_CALLS 곳까지). 멈췄으면 하지 않는다
    extra = False
    if len(adopted_places()) < MIN_ADOPTED_PLACES and not state["stop"]:
        more = eligible[len(first):min(len(first) + SCAN_EXTRA_COUNT, MAX_TRAVEL_CALLS)]
        if more:
            extra = True
            scan_places(more, origin, state)

    # 4. 제한 이내인 곳을 유사도 순으로 CHATBOT_CANDIDATE_COUNT 곳. 하나도 없으면 유사도 상위 후보로 넘긴다
    adopted = adopted_places()
    chosen = adopted[:CHATBOT_CANDIDATE_COUNT] if adopted else (eligible or valid or list(pool))[:CHATBOT_CANDIDATE_COUNT]
    travel_by_id = {str(place.get("place_id")): state["fields"][str(place.get("place_id"))]
                    for place in chosen if str(place.get("place_id")) in state["fields"]}

    scanned = len(state["fields"])
    return {
        "chosen": chosen,
        "travel_by_id": travel_by_id,
        "adopted": len(adopted),
        "scanned": scanned,
        "api_calls": api_call_counter["count"] - calls_before,
        "failed": sum(1 for fields in state["fields"].values() if fields.get("travel_missing")),
        "skipped": state["skipped"],
        "stop": state["stop"],
        "extra": extra,
        "seconds": round(time.monotonic() - started, 2),
        "no_match": not adopted,
        "excluded": excluded,
        "radius_km": radius_km,
    }


# 선정 결과를 내부 확인용 짧은 글로 만드는 함수 (장소 이름이나 좌표는 담지 않는다)
STOP_TEXT = {"transient": "일시적 오류로 중단", "rate_limit": "429 속도 제한으로 중단", "auth": "인증 오류로 중단"}


def summarize_scan(scan):
    text = f"조회 {scan['scanned']}곳(네이버 요청 {scan['api_calls']}건) / 채택 {scan['adopted']}곳 / {scan['seconds']}초"
    if scan.get("excluded"):
        text += f" / 반경 {round(scan['radius_km'])}km 밖 {scan['excluded']}곳 제외"
    if scan["extra"]:
        text += " / 추가 조회"
    if scan["stop"]:
        text += " / " + STOP_TEXT.get(scan["stop"], scan["stop"])
    return text


# 붙은 이동시간이 어떤 상태인지 짧게 요약하는 함수 (내부 확인용)
def summarize_travel_sources(recommendations):
    sources = {
        travel.get("source")
        for item in recommendations
        for travel in item.get("travels", [])
        if travel.get("mode") == "car"
    }
    if "네이버" in sources:
        return "네이버"
    if any(item.get("travel_missing") for item in recommendations):
        return "불러오지 못함"
    return "없음"
