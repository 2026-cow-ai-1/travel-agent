import csv
from pathlib import Path

import numpy as np

from embedding_tools import load_embedding_model, embed_images





BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "outputs"






# 장소 ID로 정보를 찾을 수 있는 딕셔너리를 만드는 함수
def load_place_cards():
    csv_path = BASE_DIR.parent / "place_cards.csv"

    with open(csv_path, encoding="utf-8-sig", newline="") as file:
        rows = csv.DictReader(file)

        places = {
            row["place_id"]: {
                "name": row["name"],
                "region": row["region"],
                "overview": row["overview"],
                "address": row["addr1"],
            }
            for row in rows
        }

    return places








# 사용자 입력 사진과 비슷한 사진 후보를 100개 뽑아 장소 정보와 함께 반환하는 함수
def search_images(photo_path, top_k=100):
    if top_k < 1:
        raise ValueError("top_k는 1 이상이어야 합니다.")

    # 저장된 DB 임베딩 불러오기
    embeddings = np.load(OUTPUT_DIR / "embeddings.npy")

    # 벡터 번호와 사진 정보를 연결하는 표 불러오기
    with open(
        OUTPUT_DIR / "mapping.csv",
        encoding="utf-8-sig",
        newline=""
    ) as file:
        mapping = list(csv.DictReader(file))

    mapping_by_id = {
        int(row["vector_id"]): row
        for row in mapping
    }

    # 장소 정보 불러오기
    places = load_place_cards()

    # 사용자 사진 임베딩
    processor, model, device = load_embedding_model()
    query_vector = embed_images(
        [photo_path], processor, model, device
    )

    # 코사인 유사도 계산
    db_norms = np.linalg.norm(embeddings, axis=1)
    query_norm = np.linalg.norm(query_vector[0])

    scores = (embeddings @ query_vector[0]) / np.maximum(
        db_norms * query_norm, 1e-12
    )

    # 유사도가 높은 사진 top_k개 선택
    top_indices = np.argsort(scores)[::-1][:top_k]

    results = []

    for index in top_indices:
        result = mapping_by_id[int(index)].copy()
        result["score"] = float(scores[index])

        # 사진의 장소 ID로 장소 정보 찾기
        place_info = places.get(result["place_id"])

        if place_info is None:
            raise ValueError(
                f"장소 정보가 없습니다: {result['place_id']}"
            )

        # 이름, 지역, 설명, 주소 추가
        result.update(place_info)
        results.append(result)

    return results