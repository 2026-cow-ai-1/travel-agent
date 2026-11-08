from pathlib import Path
from io import BytesIO
import json
import requests
from PIL import Image


TOTAL_DIR = Path(__file__).resolve().parent
IMAGE_DIR = TOTAL_DIR / "images"
IMAGE_DIR.mkdir(exist_ok=True)

# 만들어 둔 사진 목록 읽기
mapping = json.loads(
    (TOTAL_DIR / "image_mapping.json").read_text(
        encoding="utf-8"
    )
)

#사진 다운로드
targets = mapping

for item in targets:
    save_path = IMAGE_DIR / item["file_name"]

    try:
        # URL에서 사진 가져오기
        response = requests.get(item["url"], timeout=30)
        response.raise_for_status()

        # 실제 이미지인지 확인하고 JPG로 저장
        with Image.open(BytesIO(response.content)) as image:
            image.convert("RGB").save(save_path, format="JPEG")

        print("저장 완료:", save_path.name)

    except Exception as error:
        print("다운로드 실패:", item["file_name"], error)