"""화면(app.py)이 부르는 함수 모음.

  search_places  사진 → 비슷한 장소 후보   실제: search_tools.py (희림님 search_images 를 감쌈)
  find_origin    출발지 이름 → 좌표        미리 정한 역 목록(origin_data.py) 또는 "내 위치", API 호출 없음
  make_my_location  브라우저 위치 → 출발지  한국 안의 좌표인지 확인하고 약 100m 로 반올림 (화면 세션 안에서만 쓴다)
  recommend      조건 → 챗봇 답            실제: chat_tools.py (희림님 travel_chatbot.py 에 묻고, 이동시간은 travel_tools.py)

실제 연결이 실패하면 더미 값(dummy_data.py)이나 대체 답으로 바꿔서 화면이 끊기지 않게 한다.
어느 쪽이 쓰였는지는 last_status 와, 후보 · 답의 data_source 키로 알 수 있다 (더미이면 머리글에 "더미 데이터"가 보인다).

API 키(.env)는 이 폴더에서 읽지 않는다.
키가 필요한 처리(OpenAI, 네이버 길찾기)는 희림님 travel_chatbot.py 와 self/total/route_tools.py 가 self/.env 에서 읽는다.
"""

from dummy_data import DUMMY_CANDIDATES, DUMMY_RECOMMENDATIONS
from origin_data import LOCATION_ROUND_DIGITS, MY_LOCATION_LABEL, NO_ORIGIN_LABEL, ORIGIN_STATIONS

# 실제 연결이 쓰였는지 더미로 대체됐는지 알려 주는 내부 표시 (화면에는 더미일 때만 머리글의 "더미 데이터" 표시로 보임)
# search: "real" 이면 실제, "dummy (오류 종류)" 이면 더미로 대체된 것. 후보마다 data_source 키에도 같은 구분이 들어간다.
# travel: "네이버"(실제 길찾기), "불러오지 못함"(자동차 값을 못 구함), "없음"(시도 안 함), "dummy (오류 종류)"(더미 값 그대로)
# chat: "openai (json_schema)" / "openai (json_prompt)"(형식을 거부당해 한 번 더 보냄) / "openai (text_only)"(JSON 이 아니어서 글만),
#       "fallback (오류 종류)"(챗봇 실패, 사진이 비슷한 상위 3곳), "dummy (오류 종류)"(더미 답), "미사용"(더미 후보 등)
# chat_chars: 챗봇에 보낸 글자 수(어림값, 내용은 기록하지 않음), chat_dropped: 후보에 없어서 버린 추천 수
# scan: 최대 이동시간으로 후보를 거른 결과 요약("조회 50곳(네이버 요청 50건) / 채택 4곳 / 8초" (예시)), 안 했으면 "미사용"
# scan_stop: 조회를 멈춘 이유 ("" 없음 / "transient" 일시적 오류 / "rate_limit" 429 속도 제한 / "auth" 인증 오류)
last_status = {"search": "미사용", "travel": "미사용", "chat": "미사용", "chat_chars": 0, "chat_dropped": 0, "scan": "미사용", "scan_stop": ""}

# 챗봇(OpenAI) 연결을 켜 두는지. False 로 바꾸면 항상 더미 답을 쓴다 (시연 중 챗봇에 문제가 있을 때의 끄는 스위치).
USE_CHATBOT = True


def search_places(photo_bytes, top_k=6):
    """사진 한 장 → 비슷한 장소 후보 목록 (장소 단위, 유사도 높은 순).

    photo_bytes: 올린 사진의 내용(bytes). 예시 사진으로 해보기일 때는 None.
    돌려주는 값: 후보 dict 의 list. 후보 1개의 키는
        place_id, name, region, similarity, image_url,
        latitude, longitude, overview, address, data_source ("real" 또는 "dummy")
        (+ 길찾기가 붙으면 distance_km, duration_min)

    실제 검색은 search_tools.py 가 한다 (희림님 search_images 를 감싸서 장소 단위로 묶고 CSV 값을 붙임).
    모델이 없거나 검색이 실패하면 더미 후보로 대체해서 화면이 끊기지 않게 한다.
    """
    try:
        import search_tools

        places = search_tools.search_places_by_photo(photo_bytes, top_k)
        if not places:
            raise ValueError("검색 결과가 비어 있어요.")
    except Exception as error:  # 어떤 오류든 화면은 이어지게 한다 (오류 종류만 기록)
        last_status["search"] = f"dummy ({type(error).__name__})"
        return [{**place, "data_source": "dummy"} for place in DUMMY_CANDIDATES[:top_k]]

    last_status["search"] = "real"
    return [{**place, "data_source": "real"} for place in places]


def origin_choices():
    """출발지 선택칸에 보여 줄 항목. 맨 앞은 "선택하지 않음", 뒤는 미리 정한 역 이름."""
    return [NO_ORIGIN_LABEL] + [station["name"] for station in ORIGIN_STATIONS]


def make_my_location(latitude, longitude):
    """브라우저 위치(좌표) → 출발지 {name: "내 위치", address, latitude, longitude} 또는 None.

    좌표가 숫자가 아니거나 한국 밖이면(route_tools.is_valid_coordinate 기준) None.
    좌표는 소수점 LOCATION_ROUND_DIGITS 자리(약 100m)로 반올림한다. 이 값이 이동시간 캐시 키와 네이버 출발 좌표로 쓰이고,
    반올림하기 전의 좌표는 어디에도 두지 않는다. 이 함수는 파일이나 로그에 아무것도 남기지 않는다.
    """
    import math

    for value in (latitude, longitude):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return None

    import travel_tools

    travel_tools.add_route_path()
    import route_tools

    if not route_tools.is_valid_coordinate(latitude, longitude):
        return None

    return {
        "name": MY_LOCATION_LABEL,
        "address": "브라우저 위치 (약 100m 단위)",
        "latitude": round(float(latitude), LOCATION_ROUND_DIGITS),
        "longitude": round(float(longitude), LOCATION_ROUND_DIGITS),
    }


def find_origin(query, my_location=None):
    """출발지 이름 → {name, address, latitude, longitude} 또는 None.

    미리 정한 목록(origin_data.py)에서 찾는다. API 를 부르지 않으므로 화면이 다시 그려질 때마다 불러도 된다.
    "내 위치"이면 my_location(화면 세션이 가진 make_my_location 결과)을 돌려준다. 이 모듈은 위치를 저장하지 않는다.
    "선택하지 않음"이거나 목록에 없는 이름이면 None.
    """
    query = (query or "").strip()
    if query == MY_LOCATION_LABEL:
        return dict(my_location) if my_location else None
    for station in ORIGIN_STATIONS:
        if station["name"] == query:
            return dict(station)
    return None


def attach_travel_time(picks, candidates, origin):
    """추천 앞쪽 최대 3곳에 이동시간(자동차, 가까우면 도보)을 붙인다. 실제 계산은 travel_tools.py.

    출발지가 없으면 그대로 돌려준다. 계산 중 오류가 나면 더미 값이 든 원래 목록을 돌려줘서 화면이 이어지게 한다.
    """
    if origin is None:
        last_status["travel"] = "없음"
        return picks

    try:
        import travel_tools

        result = travel_tools.add_travel_time(picks, candidates, origin)
    except Exception as error:  # 오류 종류만 기록
        last_status["travel"] = f"dummy ({type(error).__name__})"
        return picks

    last_status["travel"] = travel_tools.summarize_travel_sources(result)
    return result


def refresh_candidates(pool, origin, max_minutes=None, count=None):
    """출발지 · 최대 이동시간이 정해졌을 때 후보를 다시 고른다 (챗봇은 부르지 않는다). 질문을 보내기 전에 화면 후보를 바꾸는 데 쓴다.

    pool:        사진 유사도 순 장소 목록 (search_places 결과 전체, 최대 500곳)
    origin:      find_origin() 결과 또는 None
    max_minutes: 최대 이동시간(분) 또는 None(제한 없음)

    돌려주는 값 (dict):
        mode          "none" 출발지 없음 / "origin" 출발지만(제한 없음) / "limit" 출발지 + 최대 이동시간
        chosen        화면에 보일 후보(최대 count 곳, 사진 유사도 순)
        travel_by_id  {place_id: 이동시간 값}  (카드와 챗봇 입력에 같이 쓴다)
        no_match      mode 가 limit 이고 제한 이내인 곳이 없으면 True
        scanned, adopted, api_calls, seconds, extra, failed, stop  (mode 가 limit 일 때만 의미 있음. stop 은 중단 이유)
        excluded, radius_km  (mode 가 limit 일 때만: 직선거리 반경 밖이라 조회하지 않고 뺀 곳 수와 그 반경)
    출발지가 있고 제한이 있으면 travel_tools.select_by_travel_time (반경 선제외 후 남은 곳 중 상위 50곳 병렬 조회, 부족하면 최대 10곳 추가, 합계 최대 60곳),
    출발지만 있으면 보이는 후보 count 곳의 이동시간만 조회한다. 같은 요청은 캐시라서 네이버를 다시 부르지 않는다.
    """
    import travel_tools

    count = count or travel_tools.CHATBOT_CANDIDATE_COUNT   # 화면에 보일 후보 수(기본은 챗봇에 보내는 후보 수 9. 앱은 app.TOP_K 를 넘긴다)
    pool = list(pool)
    base = {"mode": "none", "chosen": pool[:count], "travel_by_id": {}, "no_match": False,
            "scanned": 0, "adopted": 0, "api_calls": 0, "seconds": 0, "extra": False, "failed": 0, "stop": "",
            "excluded": 0, "radius_km": None}

    # 1. 출발지가 없으면 그대로 (유사도 상위 후보, 이동시간 없음)
    if origin is None:
        last_status["scan"], last_status["scan_stop"] = "미사용", ""
        return base

    # 2. 출발지 + 최대 이동시간: 넓게 조회해서 제한 이내인 곳만
    if max_minutes:
        scan = travel_tools.select_by_travel_time(pool, origin, max_minutes)
        last_status["scan"] = travel_tools.summarize_scan(scan)
        last_status["scan_stop"] = scan["stop"]
        last_status["travel"] = "네이버" if scan["travel_by_id"] else "불러오지 못함"
        return {**base, **scan, "mode": "limit"}

    # 3. 출발지만: 보이는 후보의 이동시간만
    chosen = pool[:count]
    travel_by_id, stop = travel_tools.travel_for_places(chosen, origin)
    last_status["scan"], last_status["scan_stop"] = "미사용", stop
    last_status["travel"] = travel_tools.summarize_travel_sources(list(travel_by_id.values()))
    return {**base, "mode": "origin", "chosen": chosen, "travel_by_id": travel_by_id, "stop": stop, "scanned": len(chosen)}


def recommend(message, candidates, history, origin=None, progress=None, max_minutes=None, selection=None):
    """사용자 조건 + 후보 목록 → 챗봇 답.

    message:    방금 사용자가 입력한 문장
    candidates: search_places() 가 돌려준 후보 목록
    history:    지금까지의 대화 [{"role": "user" | "assistant", "text": ...}, ...]
    origin:     find_origin() 결과 또는 None
    progress:   단계가 바뀔 때 부르는 함수 ("scan" 조건에 맞는 곳 찾기, "travel" 이동시간 계산, "chat" 추천 고르기). 화면의 "입력 중" 표시용이고 없어도 된다
    max_minutes: 최대 이동시간(분). 출발지도 있으면 candidates(사진 유사도 순, 넓게) 중 자동차 이동시간이 이 안인 곳만 챗봇에 보낸다. 없으면 앞쪽 9곳(CHATBOT_CANDIDATE_COUNT)
    selection:  refresh_candidates() 가 이미 돌려준 결과. 있으면 다시 조회하지 않고 그 후보 · 이동시간을 챗봇에 보낸다 (화면 후보와 같아진다)

    돌려주는 값:
        {
          "text": 추천 앞에 붙는 문장,
          "recommendations": [
              {"place_id": ..., "reason": ..., "distance_km": ..., "duration_min": ...},
              ...                       # distance_km / duration_min 은 없어도 된다
          ],
          "question": 이어서 물어볼 질문 (없으면 "")
        }

    실제 후보(data_source 가 모두 "real")이면 chat_tools.py 를 거쳐 희림님 travel_chatbot.py 의 chatbot_response() 에 묻는다.
    챗봇을 부르지 못하면(키 없음, 타임아웃 등) 사진이 비슷한 상위 3곳을 보여 주는 대체 답을 돌려주고,
    그 밖의 예상 못 한 오류와 더미 후보일 때는 아래 더미 답을 쓴다. 어느 쪽인지는 last_status["chat"] 에 남는다.
    """
    # 1. 실제 후보이면 챗봇(OpenAI)에 묻는다
    last_status["chat"] = "미사용"
    last_status["scan"], last_status["scan_stop"] = "미사용", ""
    if USE_CHATBOT and candidates and all(place.get("data_source") == "real" for place in candidates):
        try:
            import chat_tools

            extra = {"progress": progress} if progress else {}
            if max_minutes:
                extra["max_minutes"] = max_minutes
            if selection is not None:
                extra["selection"] = selection
            reply, info = chat_tools.ask_chatbot(message, candidates, history, origin, **extra)
        except Exception as error:  # 예상 못 한 오류도 화면은 이어지게 한다 (오류 종류만 기록)
            last_status["chat"] = f"dummy ({type(error).__name__})"
        else:
            last_status["chat"] = f"fallback ({info['error']})" if info["path"] == "fallback" else f"openai ({info['path']})"
            last_status["chat_chars"] = info["chars"]
            last_status["chat_dropped"] = info["dropped"]
            last_status["travel"] = info["travel"] if origin is not None else "없음"
            if info.get("scan"):
                import travel_tools

                last_status["scan"] = travel_tools.summarize_scan(info["scan"])
                last_status["scan_stop"] = info["scan"]["stop"]
            reply["data_source"] = "fallback" if info["path"] == "fallback" else "real"  # 더미가 아니다 (머리글에 더미 표시 안 함)
            return reply

    # 2. 더미 답
    known_ids = {str(place.get("place_id")) for place in candidates}
    picks = []
    for item in DUMMY_RECOMMENDATIONS:
        if item["place_id"] not in known_ids:
            continue
        pick = dict(item)
        if origin is None:  # 출발지를 모르면 이동시간도 없다
            pick.pop("distance_km", None)
            pick.pop("duration_min", None)
        picks.append(pick)

    if origin is not None and selection is not None:
        # 이미 고른 후보의 이동시간이 있으면 그대로 붙인다 (다시 조회하지 않아서 화면 후보와 같은 값이 된다). 없는 장소만 새로 구한다
        import travel_tools

        by_id = selection["travel_by_id"]
        unknown = [pick for pick in picks if str(pick["place_id"]) not in by_id]
        filled = {str(pick["place_id"]): pick for pick in (attach_travel_time(unknown, candidates, origin) if unknown else [])}
        picks = [
            filled[str(pick["place_id"])] if str(pick["place_id"]) in filled
            else {**{key: value for key, value in pick.items() if key not in travel_tools.TRAVEL_KEYS}, **by_id[str(pick["place_id"])]}
            for pick in picks
        ]
        last_status["travel"] = travel_tools.summarize_travel_sources(picks)
    else:
        picks = attach_travel_time(picks, candidates, origin)

    return {
        "text": "(예시 답변) 후보 중에서 조건에 맞는 곳을 %d곳 골랐어요." % len(picks),
        "recommendations": picks,
        "question": "걷는 길이 긴 곳과 짧은 곳 중 어느 쪽이 좋으세요?",
        "data_source": "dummy",  # 머리글에 "더미 데이터"가 보이게 한다
    }


def describe_place(place_id, candidates, origin=None, progress=None):
    """후보 카드에서 고른 한 곳 → 이름, 지역, 이동시간(자동차, 가까우면 도보 추정), 소개글을 담은 답.

    챗봇(OpenAI)은 부르지 않는다. 이동시간은 출발지가 있을 때만 구한다(같은 요청은 캐시).
    예상 못 한 오류가 나면 이동시간 없이 카드만 보여 줘서 화면이 이어지게 한다.
    """
    try:
        import chat_tools

        return chat_tools.describe_place(place_id, candidates, origin, progress=progress)
    except Exception:
        pid = str(place_id)
        return {
            "text": "고른 장소를 보여 드릴게요.",
            "recommendations": [{"place_id": pid, "reason": ""}],
            "question": "",
            "detail": True,
            "data_source": "real",
        }
