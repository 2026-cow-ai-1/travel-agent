import torch
import torch.nn.functional as F
from PIL import Image, ImageOps
from transformers import AutoImageProcessor, SiglipVisionModel

MODEL_ID = "google/siglip-base-patch16-224"





# 임베딩 모델 불러오기
def load_embedding_model():
    device = "mps" if torch.backends.mps.is_available() else "cpu"

    processor = AutoImageProcessor.from_pretrained(MODEL_ID)
    model = SiglipVisionModel.from_pretrained(MODEL_ID)
    model.to(device).eval()

    return processor, model, device









# 사진들을 임베딩 벡터로 변환
@torch.no_grad()
def embed_images(image_paths, processor, model, device):
    images = []

    for image_path in image_paths:
        with Image.open(image_path) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            images.append(image)

    inputs = processor(images=images, return_tensors="pt")
    inputs = {
        key: value.to(device)
        for key, value in inputs.items()
    }

    outputs = model(**inputs)
    vectors = F.normalize(outputs.pooler_output, p=2, dim=1)

    return vectors.cpu().float().numpy()