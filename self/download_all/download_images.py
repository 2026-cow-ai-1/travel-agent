import csv
import json
import os
from urllib.request import urlopen

CSV_PATH = "../place_cards.csv"
IMAGE_DIR = "images"
FAILED_PATH = "download_failed.csv"

os.makedirs(IMAGE_DIR, exist_ok=True)

# CSV의 장소 정보를 읽기
with open(CSV_PATH, encoding="utf-8-sig", newline="") as file:
    places = list(csv.DictReader(file))

# 사진마다 장소 ID와 URL을 연결하기
photos = []

for place in places:
    image_urls = json.loads(place["image_urls"])

    for index, image_url in enumerate(image_urls):
        photos.append({
            "place_id": place["place_id"],
            "image_index": index,
            "image_url": image_url,
        })

total = len(photos)
downloaded = 0
skipped = 0
failed = 0

print(f"전체 사진 수: {total}장", flush=True)

# 실패한 사진은 별도 CSV에 기록
with open(FAILED_PATH, "w", encoding="utf-8-sig", newline="") as file:
    writer = csv.DictWriter(
        file,
        fieldnames=["place_id", "image_index", "image_url", "error"],
    )
    writer.writeheader()

    for number, photo in enumerate(photos, start=1):
        filename = f"{photo['place_id']}_{photo['image_index']}.jpg"
        image_path = os.path.join(IMAGE_DIR, filename)
        temp_path = image_path + ".part"

        # 다운로드가 끝난 사진은 건너뛰기
        if os.path.exists(image_path) and os.path.getsize(image_path) > 0:
            skipped += 1
            print(f"[{number}/{total}] 이미 저장됨: {filename}", flush=True)
            continue

        try:
            with urlopen(photo["image_url"], timeout=30) as response:
                image_data = response.read()

            if not image_data:
                raise ValueError("빈 파일이 반환됨")

            # 임시 파일에 저장한 뒤 완료된 파일명으로 변경
            with open(temp_path, "wb") as image_file:
                image_file.write(image_data)

            os.replace(temp_path, image_path)
            downloaded += 1
            print(f"[{number}/{total}] 저장 완료: {filename}", flush=True)

        except (OSError, ValueError) as error:
            failed += 1

            if os.path.exists(temp_path):
                os.remove(temp_path)

            writer.writerow({**photo, "error": str(error)})
            file.flush()
            print(f"[{number}/{total}] 실패: {filename} — {error}", flush=True)

print()
print(f"이번에 다운로드: {downloaded}장")
print(f"이미 저장된 사진: {skipped}장")
print(f"다운로드 실패: {failed}장")