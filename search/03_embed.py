"""search/images/ 의 사진을 clip-ViT-B-32로 임베딩(512개 숫자, 길이 1로 정규화).
파일명 규칙: {place_id}_{번호}.jpg — 장소당 사진이 1장이든 여러 장이든 동작한다.
출력(search/outputs/): embeddings.npy, index_map.csv(vector_idx, file, place_id), embed_skipped.csv, embed_timing.json

실행: python search/03_embed.py
"""
import argparse, json, re, time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from PIL import Image
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

NAME_RE = re.compile(r"^(\d+)_(\d+)\.(jpg|jpeg|png|webp|gif|bmp)$", re.I)


def to_rgb(path):
    img = Image.open(path)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    return img.convert("RGB")  # 흑백(L), CMYK 등도 RGB로


def device():
    return "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"


if __name__ == "__main__":
    ROOT = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser()
    ap.add_argument("--images-dir", default=str(ROOT / "search" / "images"))
    ap.add_argument("--out-dir", default=str(ROOT / "search" / "outputs"))
    ap.add_argument("--batch", type=int, default=32)
    a = ap.parse_args()
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in Path(a.images_dir).iterdir() if NAME_RE.match(p.name))
    if not files:
        raise SystemExit(f"{a.images_dir}에 {{place_id}}_{{번호}}.jpg 사진이 없습니다. 먼저 download_images.py를 실행하세요.")
    dev = device()
    model = SentenceTransformer("clip-ViT-B-32", device=dev)

    vecs, kept, skipped = [], [], []
    t0 = time.time()
    for s in tqdm(range(0, len(files), a.batch)):
        imgs, names = [], []
        for p in files[s:s + a.batch]:
            try:
                imgs.append(to_rgb(p))
                names.append(p.name)
            except Exception as e:
                skipped.append((p.name, f"{type(e).__name__}: {e}"))
        if imgs:
            vecs.append(model.encode(imgs, batch_size=a.batch, normalize_embeddings=True))
            kept += names
    sec = time.time() - t0
    emb = np.vstack(vecs).astype("float32")
    np.save(out / "embeddings.npy", emb)
    pd.DataFrame({"vector_idx": range(len(kept)), "file": kept,
                  "place_id": [NAME_RE.match(f).group(1) for f in kept]}).to_csv(out / "index_map.csv", index=False)
    pd.DataFrame(skipped, columns=["file", "reason"]).to_csv(out / "embed_skipped.csv", index=False)
    n_places = len({NAME_RE.match(f).group(1) for f in kept})
    info = {"device": dev, "n_photos": len(kept), "n_places": n_places, "n_skipped": len(skipped),
            "seconds": round(sec, 2), "sec_per_photo": round(sec / max(1, len(kept)), 4)}
    (out / "embed_timing.json").write_text(json.dumps(info, ensure_ascii=False, indent=1))
    print(emb.shape, "길이(노름) 확인:", float(np.linalg.norm(emb, axis=1).mean()))
    print(info)
