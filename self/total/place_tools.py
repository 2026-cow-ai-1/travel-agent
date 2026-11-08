### 장소 관련 기능 함수를 모아둔 파일
from pathlib import Path
import json
import pandas as pd

#장소정보를 읽는 함수
def load_place_cards():
    # total 폴더 밖의 place_cards.csv 위치
    csv_path = (
        Path(__file__).resolve().parent.parent
        / "place_cards.csv"
    )

    # CSV 읽기
    df = pd.read_csv(
        csv_path,
        dtype={"place_id": str},
    ).fillna("")

    # 사진 URL을 문자열에서 실제 리스트로 변환
    df["image_urls"] = df["image_urls"].apply(
        lambda value: json.loads(value) if value else []
    )

    # 장소마다 하나의 딕셔너리가 되도록 변환
    return df.to_dict(orient="records")



# 장소 검색 함수
def search_places(photo_path, top_k):
    """
    photo_path: 사용자 사진 경로
    top_k: 검색할 장소 후보 수
    """

    # 지금은 연결 연습을 위해 가상 장소를 반환한다.
    # 나중에 이 부분을 실제 이미지 검색 코드로 바꾼다.
    candidates = [
        {"place_id": "101", "name": "장소 A", "score": 0.89},
        {"place_id": "205", "name": "장소 B", "score": 0.86},
        {"place_id": "309", "name": "장소 C", "score": 0.83},
    ]

    return candidates[:top_k]