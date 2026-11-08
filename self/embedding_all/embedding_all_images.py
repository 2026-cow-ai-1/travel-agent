import csv
import json
import os
import time

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageOps
from transformers import AutoImageProcessor, SiglipVisionModel

IMAGE_DIR = "/Users/yuheelim/projects/self/download_all/images"
OUTPUT_DIR = "/Users/yuheelim/projects/self/embedding_all/outputs"

MODEL_ID = "google/siglip-base-patch16-224"
BATCH_SIZE = 16

os.makedirs(OUTPUT_DIR, exist_ok=True)

device = "mps" if torch.backends.mps.is_available() else "cpu"
print("사용 장치:", device, flush=True)

# 사진 파일 목록 만들기
filenames = sorted(
    filename
    for filename in os.listdir(IMAGE_DIR)
    if filename.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
    and not filename.startswith(".")
)

if not filenames:
    raise RuntimeError("사진 폴더가 비어 있어요. IMAGE_DIR을 확인해 주세요.")

print("전체 사진 수:", len(filenames), flush=True)
print("SigLIP 모델을 불러오는 중...", flush=True)

processor = AutoImageProcessor.from_pretrained(MODEL_ID)
model = SiglipVisionModel.from_pretrained(MODEL_ID)
model.to(device).eval()

embedding_batches = []
mapping = []
failed_images = []

start_time = time.perf_counter()

for start in range(0, len(filenames), BATCH_SIZE):
    batch_filenames = filenames[start:start + BATCH_SIZE]

    images = []
    valid_filenames = []

    for filename in batch_filenames:
        image_path = os.path.join(IMAGE_DIR, filename)

        try:
            with Image.open(image_path) as image:
                image = ImageOps.exif_transpose(image).convert("RGB")

            images.append(image)
            valid_filenames.append(filename)

        except (OSError, ValueError) as error:
            failed_images.append({
                "filename": filename,
                "error": str(error),
            })
            print("사진 읽기 실패:", filename, flush=True)

    if images:
        inputs = processor(images=images, return_tensors="pt")
        inputs = {
            key: value.to(device)
            for key, value in inputs.items()
        }

        with torch.inference_mode():
            outputs = model(**inputs)
            vectors = F.normalize(outputs.pooler_output, p=2, dim=1)

        embedding_batches.append(vectors.cpu().float().numpy())

        for filename in valid_filenames:
            stem = os.path.splitext(filename)[0]
            place_id, image_index = stem.rsplit("_", 1)

            mapping.append({
                "vector_id": len(mapping),
                "place_id": place_id,
                "image_index": int(image_index),
                "filename": filename,
            })

    processed = min(start + BATCH_SIZE, len(filenames))
    elapsed = time.perf_counter() - start_time
    remaining = elapsed / processed * (len(filenames) - processed)

    print(
        f"[{processed}/{len(filenames)}] "
        f"성공 {len(mapping)}장 | "
        f"경과 {elapsed / 60:.1f}분 | "
        f"남은 시간 약 {remaining / 60:.1f}분",
        flush=True,
    )

if not embedding_batches:
    raise RuntimeError("임베딩에 성공한 사진이 없어요.")

# 사진 순서와 동일한 순서로 벡터 합치기
embeddings = np.concatenate(embedding_batches, axis=0)
assert len(embeddings) == len(mapping)

np.save(os.path.join(OUTPUT_DIR, "embeddings.npy"), embeddings)

with open(
    os.path.join(OUTPUT_DIR, "mapping.csv"),
    "w",
    encoding="utf-8-sig",
    newline="",
) as file:
    writer = csv.DictWriter(
        file,
        fieldnames=[
            "vector_id",
            "place_id",
            "image_index",
            "filename",
        ],
    )
    writer.writeheader()
    writer.writerows(mapping)

with open(
    os.path.join(OUTPUT_DIR, "failed_images.json"),
    "w",
    encoding="utf-8",
) as file:
    json.dump(failed_images, file, ensure_ascii=False, indent=2)

with open(
    os.path.join(OUTPUT_DIR, "embedding_config.json"),
    "w",
    encoding="utf-8",
) as file:
    json.dump(
        {
            "model_id": MODEL_ID,
            "feature": "pooler_output",
            "normalized": True,
            "dimension": int(embeddings.shape[1]),
        },
        file,
        indent=2,
    )

print("\n임베딩 완료!")
print("벡터 배열 크기:", embeddings.shape)
print("실패한 사진 수:", len(failed_images))
print("저장 위치:", OUTPUT_DIR)