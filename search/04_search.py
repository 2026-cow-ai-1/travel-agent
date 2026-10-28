"""FAISS 인덱스 만들기 + search_by_image(image_path, top_k=5).

사진 단위로 검색한 뒤, 같은 장소의 사진이 여러 장 걸리면 장소별 최고 점수 하나로 합쳐 돌려준다.

실행:
  python search/04_search.py build              # embeddings.npy + index_map.csv → index.faiss (저장·재로딩 검증)
  python search/04_search.py search 사진.jpg    # 터미널에서 검색
"""
import argparse, json, re, sys
from pathlib import Path

import faiss
import numpy as np
import pandas as pd
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = str(ROOT / "search" / "outputs")
CARDS = ROOT / "shared" / "place_cards.csv"
_cache = {}


def build_index(out_dir=OUT_DIR):
    out = Path(out_dir)
    emb = np.load(out / "embeddings.npy").astype("float32")
    imap = pd.read_csv(out / "index_map.csv", dtype=str)
    assert len(imap) == len(emb), "임베딩 개수와 index_map 행 수가 다릅니다 (03_embed.py를 다시 실행하세요)"
    index = faiss.IndexFlatIP(emb.shape[1])  # 길이 1로 정규화됨 → 내적 = 코사인 유사도
    index.add(emb)
    faiss.write_index(index, str(out / "index.faiss"))
    re_ = faiss.read_index(str(out / "index.faiss"))  # 저장 후 재로딩 검증
    s1, i1 = index.search(emb[:5], 5)
    s2, i2 = re_.search(emb[:5], 5)
    assert (i1 == i2).all() and np.allclose(s1, s2), "저장 후 재로딩 결과가 다릅니다"
    print(f"벡터(사진) {index.ntotal}개, 장소 {imap.place_id.nunique()}곳, "
          f"index.faiss {(out / 'index.faiss').stat().st_size / 1024:.0f}KB, 재로딩 검증 통과")


def _load(out_dir):
    if out_dir in _cache:
        return _cache[out_dir]
    out = Path(out_dir)
    if not (out / "index.faiss").exists():
        build_index(out_dir)
    import importlib
    from sentence_transformers import SentenceTransformer
    sys.path.insert(0, str(Path(__file__).parent))
    emb_mod = importlib.import_module("03_embed")
    model = SentenceTransformer("clip-ViT-B-32", device=emb_mod.device())
    imap = pd.read_csv(out / "index_map.csv", dtype=str)
    # keep_default_na=False 필수: 분류 코드 "NA"가 빈 값(NaN)으로 바뀌는 것을 막는다
    meta = pd.read_csv(CARDS, dtype=str, keep_default_na=False).set_index("place_id")
    _cache[out_dir] = (faiss.read_index(str(out / "index.faiss")), model, imap, meta, emb_mod.to_rgb)
    return _cache[out_dir]


def _photo_url(meta, place_id, file):
    n = int(re.match(r"^\d+_(\d+)\.", file).group(1))  # 파일명 {place_id}_{번호} → image_urls[번호-1]
    urls = json.loads(meta.at[place_id, "image_urls"])
    return urls[n - 1] if 0 < n <= len(urls) else (urls[0] if urls else "")


def search_by_image(image_path, top_k=5, out_dir=OUT_DIR):
    """image_path: 파일 경로 또는 PIL 이미지(디스크에 저장하지 않고 검색).
    → [{"place_id", "name", "region", "image_url", "score", "file"}, ...]  점수 높은 순, 장소 top_k곳
    장소 단위 합치기: 사진 단위로 넉넉히 찾은 뒤 같은 장소는 가장 높은 점수의 사진 1장만 남긴다.
    image_url/file은 그 가장 비슷했던 사진의 주소/파일명이다."""
    index, model, imap, meta, to_rgb = _load(out_dir)
    img = image_path.convert("RGB") if isinstance(image_path, Image.Image) else to_rgb(image_path)
    q = model.encode([img], normalize_embeddings=True).astype("float32")
    k = min(index.ntotal, max(top_k * 10, 30))
    while True:
        scores, ids = index.search(q, k)
        best = {}  # place_id -> (점수, 파일). 점수 내림차순이라 처음 나온 사진이 그 장소의 최고점
        for sc, j in zip(scores[0], ids[0]):
            r = imap.iloc[int(j)]
            best.setdefault(r["place_id"], (float(sc), r["file"]))
        if len(best) >= top_k or k >= index.ntotal:
            break
        k = min(index.ntotal, k * 3)
    res = []
    for pid, (sc, file) in list(best.items())[:top_k]:
        c = meta.loc[pid]
        res.append({"place_id": pid, "name": c["name"], "region": c["region"],
                    "image_url": _photo_url(meta, pid, file), "score": sc, "file": file})
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "search"])
    ap.add_argument("image", nargs="?")
    ap.add_argument("--out-dir", default=OUT_DIR)
    ap.add_argument("--top-k", type=int, default=5)
    a = ap.parse_args()
    if a.cmd == "build":
        build_index(a.out_dir)
    else:
        for r in search_by_image(a.image, a.top_k, a.out_dir):
            print(r)
