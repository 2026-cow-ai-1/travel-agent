from map_tools import get_origin_coordinates


def main():
    origin = input("출발지를 입력하세요: ").strip()

    if not origin:
        print("출발지를 입력해 주세요.")
        return

    # 카카오 API로 출발지 검색
    origins = get_origin_coordinates(origin)

    if not origins:
        print("검색 결과가 없어요. 더 구체적인 장소명으로 다시 실행해 주세요.")
        return

    # 검색 결과 보여주기
    print("\n출발지를 선택하세요.")

    for number, place in enumerate(origins, start=1):
        print(f"{number}. {place['name']} — {place['address']}")

    # 올바른 번호를 입력할 때까지 기다리기
    while True:
        choice = input("\n출발지 번호를 입력하세요: ")

        try:
            number = int(choice)
        except ValueError:
            print("숫자로 입력해 주세요.")
            continue

        if 1 <= number <= len(origins):
            selected_origin = origins[number - 1]
            break

        print(f"1부터 {len(origins)} 사이의 번호를 입력해 주세요.")

    # 선택한 출발지 확인
    print("\n선택한 출발지:", selected_origin["name"])
    print("주소:", selected_origin["address"])
    print("위도:", selected_origin["latitude"])
    print("경도:", selected_origin["longitude"])


if __name__ == "__main__":
    main()