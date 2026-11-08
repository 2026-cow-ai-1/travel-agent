from pathlib import Path
import json

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from transformers import AutoImageProcessor, SiglipVisionModel


TOTAL_DIR = Path(__file__).resolve().parent
IMAGE_DIR = TOTAL_DIR / "images"
OUTPUT_DIR = TOTAL_DIR / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

MODEL_NAME = "google/siglip-base-patch16-224"

# 사용 가능한 장치 선택
if torch.cuda.is_available():
    device = "cuda"
elif torch.backends.mps.is_available():
    device = "mps"
else:
    device = "cpu"

print("사용 장치:", device)

# 사진 전처리 도구와 모델 준비
processor = AutoImageProcessor.from_pretrained(MODEL_NAME)

model = SiglipVisionModel.from_pretrained(
    MODEL_NAME
).to(device)

model.eval()

# 사진과 장소 연결 목록 읽기
mapping = json.loads(
    (TOTAL_DIR / "image_mapping.json").read_text(
        encoding="utf-8"
    )
)

vectors = []
embedding_mapping = []

for item in mapping:
    image_path = IMAGE_DIR / item["file_name"]

    # 아직 다운로드하지 않은 사진은 건너뛰기
    if not image_path.is_file():
        continue

    # 사진을 모델에 넣을 수 있는 형태로 변환
    with Image.open(image_path) as image:
        inputs = processor(
            images=image.convert("RGB"),
            return_tensors="pt",
        )

    inputs = {
        key: value.to(device)
        for key, value in inputs.items()
    }

    # 실제 임베딩
    with torch.inference_mode():
        output = model(**inputs)
        vector = output.pooler_output

        # 나중에 코사인 유사도를 계산하기 위해 정규화
        vector = F.normalize(vector, p=2, dim=-1)

    vector = vector[0].cpu().numpy()

    # 벡터와 연결 정보를 같은 순서로 추가
    vector_id = len(vectors)
    vectors.append(vector)

    embedding_mapping.append({
        "vector_id": vector_id,
        **item,
    })

    print("임베딩 완료:", item["file_name"])

if not vectors:
    raise SystemExit("임베딩할 사진이 없어요.")

# 사진별 벡터를 하나의 배열로 저장
embeddings = np.stack(vectors).astype(np.float32)

np.save(
    OUTPUT_DIR / "embeddings.npy",
    embeddings,
)

# 실제 임베딩한 사진의 연결 정보만 저장
(OUTPUT_DIR / "embedding_mapping.json").write_text(
    json.dumps(
        embedding_mapping,
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)

print("저장 완료!")
print("벡터 배열 크기:", embeddings.shape)