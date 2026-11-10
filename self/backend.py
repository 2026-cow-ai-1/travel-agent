"""화면(app.py)이 부르는 함수 세 개.

지금은 전부 dummy_data.py 의 가짜 값을 돌려준다.
실제 검색 · 길찾기 · 챗봇 함수가 완성되면 **이 파일의 함수 본문만** 바꾸면 되고,
app.py 와 ui.py 는 손대지 않아도 된다.

API 키(.env)는 이 폴더에서 읽지 않는다.
키가 필요한 처리는 실제 함수를 만드는 쪽(검색 · 길찾기 담당)의 모듈 안에서 한다.
"""

from dummy_data import DUMMY_CANDIDATES, DUMMY_ORIGIN, DUMMY_RECOMMENDATIONS


def search_places(photo_bytes, top_k=6):
    """사진 한 장 → 비슷한 장소 후보 목록 (장소 단위, 유사도 높은 순).

    photo_bytes: 올린 사진의 내용(bytes). 예시 사진으로 해보기일 때는 None.
    돌려주는 값: 후보 dict 의 list. 후보 1개의 키는
        place_id, name, region, similarity, image_url,
        latitude, longitude, overview
        (+ 길찾기가 붙으면 distance_km, duration_min)

    TODO(실제 연결): self/embedding_all/search_images.py 의 search_images() 결과는
      - 사진 단위라 같은 place_id 가 여러 번 나온다 → 장소 단위로 묶기
      - 키 이름이 score / filename 이다 → similarity / image_url 로 맞추기
    """
    return [dict(place) for place in DUMMY_CANDIDATES[:top_k]]


def find_origin(query):
    """출발지 이름 → {name, address, latitude, longitude} 또는 None.

    TODO(실제 연결): self/total/map_tools.py 의 get_origin_coordinates().
    지금 그 함수는 터미널 input() 으로 번호를 고르게 돼 있어서,
    화면에서 쓰려면 후보 목록만 돌려주는 형태가 필요하다.
    """
    query = (query or "").strip()
    if not query:
        return None
    origin = dict(DUMMY_ORIGIN)
    origin["name"] = query
    return origin


def recommend(message, candidates, history, origin=None):
    """사용자 조건 + 후보 목록 → 챗봇 답.

    message:    방금 사용자가 입력한 문장
    candidates: search_places() 가 돌려준 후보 목록
    history:    지금까지의 대화 [{"role": "user" | "assistant", "text": ...}, ...]
    origin:     find_origin() 결과 또는 None

    돌려주는 값:
        {
          "text": 추천 앞에 붙는 문장,
          "recommendations": [
              {"place_id": ..., "reason": ..., "distance_km": ..., "duration_min": ...},
              ...                       # distance_km / duration_min 은 없어도 된다
          ],
          "question": 이어서 물어볼 질문 (없으면 "")
        }

    TODO(실제 연결): self/embedding_all/travel_chatbot.py 의 chatbot_response().
    """
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

    return {
        "text": "(예시 답변) 후보 중에서 조건에 맞는 곳을 %d곳 골랐어요." % len(picks),
        "recommendations": picks,
        "question": "걷는 길이 긴 곳과 짧은 곳 중 어느 쪽이 좋으세요?",
    }
