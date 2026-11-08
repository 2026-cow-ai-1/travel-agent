from pathlib import Path
import json

from place_tools import load_place_cards


TOTAL_DIR = Path(__file__).resolve().parent
places = load_place_cards()

images = []

for place in places:
    for number, url in enumerate(place["image_urls"]):
        images.append({
            "image_id": len(images),
            "place_id": place["place_id"],
            "url": url,
            "file_name": f"{place['place_id']}_{number}.jpg",
        })

# 사진과 장소의 연결 목록 저장
output_path = TOTAL_DIR / "image_mapping.json"

output_path.write_text(
    json.dumps(images, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

print("장소 수:", len(places))
print("전체 사진 수:", len(images))
print("첫 번째 사진 정보:", images[0] if images else "사진 없음")
print("저장 위치:", output_path)