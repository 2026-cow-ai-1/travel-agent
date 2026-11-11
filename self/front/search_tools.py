"""사진 검색(희림님 search_images)을 화면(backend.py)이 받는 모양으로 감싸는 함수 모음.

search_images.py 는 고치지 않는다. 여기서 하는 일은 세 가지다.
  1. 모델은 한 번만 불러오게 한다 (st.cache_resource)
  2. 사진 단위 결과를 place_id 로 묶어 장소 단위로 만든다 (group_photos_by_place)
  3. shared/place_cards.csv 에서 위도, 경도, 사진 주소를 붙인다 (add_place_fields)

키(.env)는 필요 없다. 모델은 처음 한 번 인터넷에서 내려받는다 (google/siglip-base-patch16-224).
"""

import csv
import json
import os
import sys
import tempfile
from pathlib import Path

import streamlit as st

FRONT_DIR = Path(__file__).resolve().parent
SELF_DIR = FRONT_DIR.parent
EMBEDDING_DIR = SELF_DIR / "embedding_all"
PLACE_CARDS_PATH = SELF_DIR.parent / "shared" / "place_cards.csv"

# "예시 사진으로 해보기"에서 쓰는 사진 (희림님 챗봇 테스트와 같은 사진)
EXAMPLE_PHOTO_PATH = SELF_DIR / "query" / "test1.jpeg"

# 장소를 여러 곳 만들려면 사진이 여러 장 필요하다 (한 장소에 사진이 최대 39장).
# 측정(images.jpeg): 사진 200장 → 장소 약 131곳, 1,000장 → 장소 500곳. 장소 500곳(app.POOL_SIZE)을 모으려고 여유를 두어 1,500장으로 한다.
# 검색 시간은 사진 수와 거의 상관없다(측정: 200장 0.057초, 1,500장 0.059초, 모델 로딩 제외). 다른 사진에서도 500곳이 나오는지는 확인하지 않았다.
PHOTO_TOP_K = 1500


# ── 값 읽기 ──────────────────────────────────────────────────

# 숫자로 바꿀 수 있으면 float, 아니면 None
def parse_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


# shared/place_cards.csv 를 place_id 로 찾을 수 있게 한 번만 읽는 함수
@st.cache_resource(show_spinner=False)
def load_place_cards_by_id():
    # 1. CSV 읽기
    with open(PLACE_CARDS_PATH, encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    # 2. place_id 마다 필요한 값만 정리 (사진 주소는 문자열을 리스트로 바꿈)
    cards = {}
    for row in rows:
        try:
            image_urls = json.loads(row.get("image_urls") or "[]")
        except ValueError:
            image_urls = []

        cards[str(row["place_id"])] = {
            "name": row.get("name", ""),
            "region": row.get("region", ""),
            "overview": row.get("overview", ""),
            "address": row.get("addr1", ""),
            "latitude": parse_number(row.get("latitude")),
            "longitude": parse_number(row.get("longitude")),
            "image_urls": image_urls if isinstance(image_urls, list) else [],
        }

    return cards


# ── 변환 (모델 없이 단위 검증할 수 있는 순수 함수) ─────────────

# 사진 단위 검색 결과를 place_id 로 묶어 장소 단위로 만드는 함수
def group_photos_by_place(photo_results, top_k=6):
    if top_k < 1:
        raise ValueError("top_k는 1 이상이어야 해요.")

    # 1. 점수가 높은 순으로 오므로, 장소마다 처음 나온 사진이 가장 비슷한 사진
    places = []
    seen = set()

    for photo in photo_results:
        place_id = str(photo.get("place_id"))
        if place_id in seen:
            continue
        seen.add(place_id)

        # 2. score 를 similarity 로 바꾸고 0~1 안으로 맞춤 (코사인 값은 음수가 될 수 있음)
        score = parse_number(photo.get("score"))
        similarity = None if score is None else max(0.0, min(1.0, score))

        # 3. 어떤 사진이 가장 비슷했는지(image_index)는 사진 주소를 고를 때 쓴다
        image_index = parse_number(photo.get("image_index"))

        places.append({
            "place_id": place_id,
            "name": photo.get("name", ""),
            "region": photo.get("region", ""),
            "overview": photo.get("overview", ""),
            "address": photo.get("address", ""),
            "similarity": similarity,
            "image_index": None if image_index is None else int(image_index),
        })

        if len(places) == top_k:
            break

    return places


# 장소마다 CSV 에서 위도, 경도, 사진 주소(image_urls[image_index])를 붙이는 함수
def add_place_fields(places, place_cards):
    result = []

    for place in places:
        card = place_cards.get(str(place.get("place_id")), {})
        image_urls = card.get("image_urls", [])
        image_index = place.get("image_index")

        # 1. 가장 비슷했던 사진의 주소. 번호가 맞지 않으면 첫 번째 사진 주소
        if isinstance(image_index, int) and 0 <= image_index < len(image_urls):
            image_url = image_urls[image_index]
        elif image_urls:
            image_url = image_urls[0]
        else:
            image_url = ""

        # 2. 화면이 받는 키로 정리 (image_index 는 여기서 쓰고 버림)
        new_place = {key: value for key, value in place.items() if key != "image_index"}
        new_place["image_url"] = image_url
        new_place["latitude"] = card.get("latitude")
        new_place["longitude"] = card.get("longitude")
        result.append(new_place)

    return result


# ── 업로드한 사진을 임시 파일로 ───────────────────────────────

# 사진 내용(bytes)을 임시 파일로 저장하고 그 경로를 돌려주는 함수
def save_temp_photo(photo_bytes):
    if not isinstance(photo_bytes, (bytes, bytearray)) or not photo_bytes:
        raise ValueError("사진 내용이 비어 있어요.")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as file:
        file.write(photo_bytes)

    return Path(file.name)


# 임시 사진 파일을 지우는 함수 (이미 없어도 오류 없이 넘어감)
def delete_temp_photo(photo_path):
    try:
        os.remove(photo_path)
    except OSError:
        pass


# ── 검색 (희림님 search_images 를 부름) ───────────────────────

# search_images.py 와 embedding_tools.py 를 불러올 수 있게 경로를 한 번 추가
def add_embedding_path():
    path = str(EMBEDDING_DIR)
    if path not in sys.path:
        sys.path.insert(0, path)


# 임베딩 모델을 한 번만 불러오는 함수 (처음에는 인터넷에서 내려받음)
@st.cache_resource(show_spinner=False)
def load_search_model():
    add_embedding_path()
    from embedding_tools import load_embedding_model

    return load_embedding_model()


# 모델은 캐시에서 꺼내 쓰도록 바꿔서 search_images 를 부르는 함수 (사진 단위 결과)
def run_photo_search(photo_path, photo_top_k=PHOTO_TOP_K):
    # 1. 모델을 먼저 한 번 불러둠 (두 번째부터는 캐시에서 바로 나옴)
    model_parts = load_search_model()

    # 2. search_images 안의 모델 불러오기만 캐시된 값으로 바꿈 (파일은 수정하지 않음)
    add_embedding_path()
    import search_images

    search_images.load_embedding_model = lambda: model_parts

    # 3. 사진 단위로 검색
    return search_images.search_images(photo_path, top_k=photo_top_k)


# 사진 경로 하나로 장소 후보(화면이 받는 모양)를 만드는 함수
def build_places(photo_path, top_k=6):
    # 1. 사진 단위로 검색
    photo_results = run_photo_search(photo_path)

    # 2. 장소 단위로 묶고 CSV 값 붙이기
    places = group_photos_by_place(photo_results, top_k)
    return add_place_fields(places, load_place_cards_by_id())


# 예시 사진의 검색 결과를 한 번만 만들어 두는 함수 (시연 중 같은 검색을 반복하지 않게)
@st.cache_data(show_spinner=False)
def search_example_places(top_k=6):
    return build_places(EXAMPLE_PHOTO_PATH, top_k)


# 업로드한 사진(bytes) 또는 예시 사진(None)으로 비슷한 장소 후보를 찾는 함수
def search_places_by_photo(photo_bytes, top_k=6):
    # 1. 예시 사진이면 캐시된 결과 사용
    if photo_bytes is None:
        return search_example_places(top_k)

    # 2. 업로드한 사진은 임시 파일로 저장해서 검색하고, 끝나면 반드시 지움
    photo_path = save_temp_photo(photo_bytes)
    try:
        return build_places(photo_path, top_k)
    finally:
        delete_temp_photo(photo_path)
