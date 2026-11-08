import csv
import json
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageDraw, ImageOps
from transformers import AutoImageProcessor, SiglipVisionModel

BASE = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / "outputs"
OUT.mkdir(exist_ok=True)

MODEL_ID = "google/siglip-base-patch16-224"
QUERY = BASE / "query/test5.jpeg"

device = "cuda" if torch.cuda.is_available() else (
    "mps" if torch.backends.mps.is_available() else "cpu"
)

processor = AutoImageProcessor.from_pretrained(MODEL_ID)
model = SiglipVisionModel.from_pretrained(MODEL_ID)
model.to(device).eval()


def read_image(path):
    with Image.open(path) as image:
        return ImageOps.exif_transpose(image).convert("RGB")


def embed(paths):
    images = [read_image(path) for path in paths]
    inputs = processor(images=images, return_tensors="pt")

    with torch.inference_mode():
        outputs = model(
            pixel_values=inputs["pixel_values"].to(device)
        )
        vectors = outputs.pooler_output

    return F.normalize(vectors.float(), dim=-1).cpu()


with (BASE / "sample_200/metadata.csv").open(
    encoding="utf-8-sig", newline=""
) as file:
    records = list(csv.DictReader(file))

if not records:
    raise ValueError("검색 대상 사진이 없습니다.")

paths = [
    BASE / "sample_200" / row["image_path"]
    for row in records
]

batches = []

for start in range(0, len(paths), 8):
    batch = paths[start:start + 8]
    batches.append(embed(batch))
    print(f"{start + len(batch)}/{len(paths)}")

vectors = torch.cat(batches)
query_vector = embed([QUERY])

scores = (query_vector @ vectors.T).squeeze(0)
values, indices = scores.topk(min(5, len(records)))

np.save(OUT / "embeddings.npy", vectors.numpy())
np.save(OUT / "query_embedding.npy", query_vector.numpy())

with (OUT / "metadata.json").open("w", encoding="utf-8") as file:
    json.dump(
        {
            "model_id": MODEL_ID,
            "images": [
                {"vector_index": i, **row}
                for i, row in enumerate(records)
            ],
        },
        file,
        ensure_ascii=False,
        indent=2,
    )

results = []

for rank, (score, index) in enumerate(
    zip(values.tolist(), indices.tolist()), 1
):
    row = {"rank": rank, "score": score, **records[index]}
    results.append(row)
    print(f"{rank}위 {row['name']} {score:.4f}")

with (OUT / "results.csv").open(
    "w", encoding="utf-8-sig", newline=""
) as file:
    writer = csv.DictWriter(file, fieldnames=list(results[0]))
    writer.writeheader()
    writer.writerows(results)

preview = Image.new("RGB", (960, 540), "white")
draw = ImageDraw.Draw(preview)

preview_paths = [QUERY] + [
    BASE / "sample_200" / row["image_path"]
    for row in results
]
labels = ["Query"] + [
    f"Top {row['rank']}: {row['score']:.4f}"
    for row in results
]

for i, (path, label) in enumerate(zip(preview_paths, labels)):
    x, y = (i % 3) * 320, (i // 3) * 270
    image = ImageOps.contain(read_image(path), (300, 230))
    preview.paste(image, (x + (320 - image.width) // 2, y + 30))
    draw.text((x + 10, y + 8), label, fill="black")

preview.save(OUT / "top5.jpg")
print(f"저장 완료: {OUT}")