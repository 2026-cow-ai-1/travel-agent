"""개인 테스트용 검색 화면. 실행: python search/05_demo.py  (http://127.0.0.1:7860, 내 컴퓨터에서만 열림)"""
import atexit, importlib.util, os, shutil, signal, sys, tempfile
from pathlib import Path

# Gradio는 업로드/표시 파일을 임시 폴더에 캐시한다 → 전용 임시 폴더로 지정하고 종료 시 삭제
TMP = tempfile.mkdtemp(prefix="gradio_tmp_")
os.environ["GRADIO_TEMP_DIR"] = TMP
os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
for _s in (signal.SIGTERM, signal.SIGHUP):  # kill·터미널 창 닫기로 종료해도 정리가 돌도록
    signal.signal(_s, lambda *_: sys.exit(0))

import gradio as gr
import pandas as pd

spec = importlib.util.spec_from_file_location("search", Path(__file__).with_name("04_search.py"))
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)
ROOT = Path(__file__).resolve().parents[1]
# keep_default_na=False: 분류 코드 "NA"가 빈 값으로 바뀌는 것을 막는다
CARDS = pd.read_csv(ROOT / "shared" / "place_cards.csv", dtype=str, keep_default_na=False).set_index("place_id")
IMG_DIR = ROOT / "search" / "images"
K = 5


def run(img):
    if img is None:
        return [None, ""] * K
    out = []
    for r in S.search_by_image(img, K):
        c = CARDS.loc[r["place_id"]]
        out += [str(IMG_DIR / r["file"]),
                f"**{r['name']}**  \n점수 {r['score']:.3f}  \n지역: {r['region']}  \n라이선스: {c.license_type}  \n출처: 한국관광공사 TourAPI"]
    return out


with gr.Blocks(title="사진 기반 여행지 검색 (개인 테스트)") as demo:
    gr.Markdown("사진을 올리면 비슷한 한국 관광지 5곳을 보여줍니다. (개인 테스트용 · 올린 사진은 코드에서 저장하지 않음)")
    inp = gr.Image(type="pil", label="사진 업로드")
    outs = []
    with gr.Row():
        for i in range(K):
            with gr.Column():
                outs += [gr.Image(label=f"{i + 1}위", interactive=False), gr.Markdown()]
    inp.change(run, inp, outs)

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", share=False)
