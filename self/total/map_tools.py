import os
from pathlib import Path

import requests
from dotenv import load_dotenv


# self 폴더에 있는 .env 읽기
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_PATH)


def get_origin_coordinates(origin):

    if not isinstance(origin, str) or not origin.strip():
        raise ValueError("출발지를 입력해 주세요.")

    api_key = os.getenv("KAKAO_REST_API_KEY")

    if not api_key:
        raise ValueError(".env에 KAKAO_REST_API_KEY가 없어요.")

    # 1.카카오 API로 출발지 검색
    response = requests.get(
        "https://dapi.kakao.com/v2/local/search/keyword.json",
        headers={
            "Authorization": f"KakaoAK {api_key}"
        },
        params={
            "query": origin.strip(),
            "size": 5,
        },
        timeout=15,
    )

    response.raise_for_status()
    data = response.json()

    # 2.검색 결과 정리
    candidates = []

    for place in data["documents"]:
        candidates.append({
            "name": place["place_name"],
            "address": (
                place["road_address_name"]
                or place["address_name"]
            ),
            "latitude": float(place["y"]),
            "longitude": float(place["x"]),
        })

    if not candidates:
        print("검색된 출발지가 없어요.")
        return None

    # 3.검색 결과 표시
    print("\n출발지를 선택하세요.")

    for number, place in enumerate(candidates, start=1):
        print(f"{number}. {place['name']} — {place['address']}")

    # 4. 사용자가 번호 선택
    while True:
        choice = input("\n출발지 번호를 입력하세요: ")

        try:
            number = int(choice)
        except ValueError:
            print("숫자로 입력해 주세요.")
            continue

        if not 1 <= number <= len(candidates):
            print(f"1부터 {len(candidates)} 사이의 번호를 입력해 주세요.")
            continue

        selected = candidates[number - 1]
        break

    # 5. 선택한 출발지와 좌표 출력
    print("\n선택한 출발지:", selected["name"])
    print("주소:", selected["address"])
    print("위도:", selected["latitude"])
    print("경도:", selected["longitude"])

    # 6. 최종 좌표 반환
    return {
        "latitude": selected["latitude"],
        "longitude": selected["longitude"],
    }


###################나중에는 Main에 넣을것임
# 이 파일을 직접 실행할 때만 테스트
if __name__ == "__main__":
    origin = input("출발지를 입력하세요: ").strip()
    coordinates = get_origin_coordinates(origin)