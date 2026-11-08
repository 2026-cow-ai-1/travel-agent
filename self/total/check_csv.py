from place_tools import load_place_cards

places = load_place_cards()

print("장소 수:", len(places))
print("첫 번째 장소 이름:", places[0]["name"])
print("첫 번째 장소 사진 목록:", places[0]["image_urls"])
print("사진 목록 자료형:", type(places[0]["image_urls"]))