"""사진 한 장 → 비슷한 장소 후보 → 대화로 추천. (화면 틀, 더미 데이터)

실행:  cd self/front  &&  streamlit run app.py

이 파일은 "어떤 순서로 무엇을 보여 줄지"만 정한다.
  - 데이터는 backend.py 의 함수 3개에서 받는다.
  - HTML 조각은 ui.py, 모양은 style.css 에 있다.
"""

import streamlit as st

import backend
import ui

TOP_K = 6
QUICK_CONDITIONS = ["조용한 곳", "아이랑 걷기 좋은 곳", "2시간 안에 갈 수 있는 곳", "모르겠어요"]
GREETING = "사진 검색이 끝났어요. 어떤 분위기나 특징을 가장 중요하게 생각하시나요?"

state = st.session_state


def initial_state():
    """화면이 기억하는 값과 처음 값. 부를 때마다 새로 만든다(목록이 서로 섞이지 않게)."""
    return {
        "stage": "upload",    # "upload" → "candidates" → "chat"
        "photo": None,        # 올린 사진(bytes). 메모리에만 두고 저장하지 않는다
        "photo_name": "",
        "candidates": [],     # backend.search_places() 결과
        "messages": [],       # 대화 기록
        "origin_query": "",   # 출발지 입력 칸의 글자
    }


def show(html_text):
    st.markdown(html_text, unsafe_allow_html=True)


# ── 동작 ─────────────────────────────────────────────────────

def start_search(photo_bytes, photo_name):
    state.photo = photo_bytes
    state.photo_name = photo_name
    state.candidates = backend.search_places(photo_bytes, top_k=TOP_K)
    state.messages = [{"role": "assistant", "text": GREETING}]
    state.stage = "candidates"


def start_over():
    state.update(initial_state())


def send(text):
    """사용자 문장을 대화에 넣고, 챗봇 답을 받아 붙인 뒤 대화 화면으로 넘어간다."""
    text = (text or "").strip()
    if not text:
        return
    history = list(state.messages)
    origin = backend.find_origin(state.origin_query)
    reply = backend.recommend(text, state.candidates, history, origin=origin)
    state.messages.append({"role": "user", "text": text})
    state.messages.append({"role": "assistant", **reply})
    state.stage = "chat"


# ── 화면 ─────────────────────────────────────────────────────

def render_header(step=""):
    """머리글. 왼쪽 서비스 이름을 누르면 처음(사진 올리기) 화면으로 돌아간다."""
    with st.container(key="top_bar"):
        brand, info = st.columns(2, vertical_alignment="center")
        if brand.button(ui.BRAND, type="tertiary", key="brand"):
            start_over()
            st.rerun()
        with info:
            show(ui.header_info(step))
    show(ui.SOURCE_LINE)


def render_my_photo(size):
    show('<span class="tf-label">내가 올린 사진</span>')
    if state.photo:
        st.image(state.photo, use_container_width=True)
        show(f'<span class="tf-note">{ui.esc(state.photo_name)}</span>')
    else:
        show(ui.my_photo_placeholder(size))


def render_upload():
    render_header()
    intro, dropzone = st.columns(2, gap="large")

    # 네모 칸 하나 안에 "사진 고르기"와 "올린 사진"을 함께 둔다 (칸 모양은 style.css 의 .st-key-photo_box)
    with dropzone.container(key="photo_box"):
        uploaded = st.file_uploader(
            "사진을 여기로 끌어오거나 눌러서 고르세요",
            type=["jpg", "jpeg", "png"],
            help="사진은 저장하지 않아요.",
        )
        if uploaded is not None:
            show(ui.COMPACT_DROPZONE)
            st.image(uploaded, use_container_width=True)

    with intro:
        show(
            '<span class="tf-kicker">첫째. 사진 올리기</span>'
            '<div class="tf-title" role="heading" aria-level="1">마음에 드는 풍경 사진 한 장을 올려 주세요</div>'
            '<p class="tf-lead">분위기가 비슷한 국내 자연 여행지를 찾아 드려요.</p>'
        )
        search_column, sample_column = st.columns(2)
        search_clicked = search_column.button("비슷한 장소 찾기", type="primary", use_container_width=True)
        sample_clicked = sample_column.button("예시 사진으로 해보기", use_container_width=True)

        if search_clicked and uploaded is None:
            show('<p class="tf-note">먼저 오른쪽에 사진을 한 장 올려 주세요.</p>')
        elif search_clicked:
            start_search(uploaded.getvalue(), uploaded.name)
            st.rerun()
        elif sample_clicked:
            start_search(None, "")
            st.rerun()

    show('<p class="tf-flow">예시사진 올리기 -&gt; 유사한 후보 보기 -&gt; 챗봇과 대화로 상세정보 입력</p>')


def render_candidates():
    render_header("2 / 3 · 후보 보기")
    side, main = st.columns([1, 3], gap="large")

    with side:
        render_my_photo("tall")
        if st.button("다른 사진 올리기", type="tertiary"):
            start_over()
            st.rerun()

    with main:
        count = len(state.candidates)
        show(
            '<div class="tf-row">'
            f'<div class="tf-title tf-title--small" role="heading" aria-level="1">분위기가 비슷한 장소 {count}곳</div>'
            '<span class="tf-note">정렬:유사도 순</span>'
            "</div>"
        )
        show(ui.card_grid(state.candidates))

    show('<p class="tf-ask">추가로 원하는 조건을 말해 주세요</p>')
    picked = None
    for column, label in zip(st.columns(len(QUICK_CONDITIONS)), QUICK_CONDITIONS):
        if column.button(label, type="tertiary"):
            picked = label
    typed = st.chat_input("예) 서울에서 출발해서 바다 보이는 산책길이면 좋겠어요")

    if picked or typed:
        send(picked or typed)
        st.rerun()


def render_chat():
    render_header("3 / 3 · 대화로 추천")
    side, main = st.columns([1, 3], gap="large")

    with side:
        render_my_photo("short")

        show('<span class="tf-label tf-label--spaced">출발지 (이동시간 계산용)</span>')
        # key 로 묶지 않고 직접 옮겨 담는다: 다른 화면에 다녀와도 입력한 출발지가 남게 하려고
        state.origin_query = st.text_input(
            "출발지", value=state.origin_query, placeholder="예) 서울역", label_visibility="collapsed"
        )
        origin = backend.find_origin(state.origin_query)
        if origin:
            show(f'<span class="tf-note">{ui.esc(origin["address"])} · 더미 좌표</span>')
        else:
            show('<span class="tf-note">비워 두면 이동시간 없이 추천해요.</span>')

        show(f'<span class="tf-label tf-label--spaced">사진 후보 {len(state.candidates)}곳</span>')
        show(ui.candidate_list(state.candidates))
        if st.button("후보 카드 다시 보기", type="tertiary"):
            state.stage = "candidates"
            st.rerun()

    with main:
        show(ui.transcript(state.messages, state.candidates))

    typed = st.chat_input("조건을 더 말하거나 후보끼리 비교해 달라고 해 보세요")
    if typed:
        send(typed)
        st.rerun()


# ── 시작 ─────────────────────────────────────────────────────

st.set_page_config(page_title=ui.BRAND, layout="wide")
show(ui.load_css())

for key, value in initial_state().items():
    state.setdefault(key, value)

RENDERERS = {"upload": render_upload, "candidates": render_candidates, "chat": render_chat}
RENDERERS[state.stage]()
