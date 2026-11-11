"""사진 한 장 + 출발지 · 최대 이동시간 → 비슷한 장소 후보 → 대화로 추천.

실행:  cd self/front  &&  ../../.venv/bin/streamlit run app.py   (자세한 내용은 README.md)

이 파일은 "어떤 순서로 무엇을 보여 줄지"만 정한다.
  - 데이터는 backend.py 의 함수에서 받는다. (실제 검색 · 이동시간 · 챗봇에 연결돼 있고, 실패하면 더미 데이터로 대체된다)
  - HTML 조각은 ui.py, 모양은 style.css 에 있다.
  - 머리글의 "더미 데이터" 표시는 더미로 대체된 데이터가 화면에 있을 때만 나온다.

업로드 화면에서 사진과 함께 출발지(내 위치 / 역 / 선택 안 함)와 최대 이동시간을 받는다. "찾기"(또는 "예시 사진")를 누르면
  사진 검색 → (출발지가 있으면) 반경 선제외 → 이동시간 조회 → 후보 9곳까지 한 번에 처리하고(pending "search"), 처리 중에는 입력과 선택칸을 막는다.
  고른 조건은 후보 · 대화 화면과 같은 session_state 값(origin_query, my_location, max_hours)이라 단계가 바뀌어도 그대로 쓴다.
  처음으로 돌아가거나 다른 사진을 올리면 조건을 모두 지운다(start_over).

메시지를 보내면 두 번에 나눠 그린다 (챗봇처럼 바로 반응하려고).
  1. 제출: 내 말을 대화에 넣고 "답을 기다리는 중"(pending)으로 표시한 뒤 바로 다시 그린다 → 내 말풍선이 먼저 보인다
  2. 다음 실행: 챗봇 자리에 "입력 중" 말풍선을 보여 주면서 backend 를 부르고, 답이 오면 말풍선으로 바꾼다
  기다리는 동안에는 입력창과 버튼을 막아서 같은 요청이 겹치지 않게 한다.
"""

import tempfile
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

import backend
import ui
from origin_data import MY_LOCATION_LABEL

TOP_K = 9          # 후보 화면에 보여 주는 장소 수 (6 → 9. 3장씩 3줄. travel_tools.CHATBOT_CANDIDATE_COUNT 와 같아야 화면 후보와 챗봇 후보가 같다)
POOL_SIZE = 500    # 첫 검색에서 사진 유사도 순으로 모아 두는 장소 수(사진 1,500장 → 장소 500곳). 최대 이동시간이 있으면 직선거리 반경 밖을 빼고(2시간 170km) 남은 곳 중 상위 50곳을 조회한다 (조회는 최대 60곳 = travel_tools.MAX_TRAVEL_CALLS)
TIME_CHIP = "2시간 안에 갈 수 있는 곳"
QUICK_CONDITIONS = ["조용한 곳", "아이랑 걷기 좋은 곳", TIME_CHIP, "모르겠어요"]

# 최대 이동시간 선택칸의 항목 (글자, 시간). 0시간은 제한 없음. 기본은 제한 없음
HOUR_CHOICES = [("제한 없음", 0), ("1시간", 1), ("2시간", 2), ("3시간", 3), ("4시간", 4), ("5시간", 5)]
HOUR_LABELS = [label for label, _ in HOUR_CHOICES]
HOURS_BY_LABEL = dict(HOUR_CHOICES)

# 대화 시작 메시지. 질문 대신 안내만 한다 ({count} 는 찾은 후보 수)
GREETING = "비슷한 곳 {count}곳을 찾았어요. 마음에 드는 곳을 고르거나 조건을 말해 주세요."

# 후보를 다시 고르는 결과 문구 ({scanned} 는 확인한 장소 수, {origin} 출발지 이름, {hours} 최대 이동시간, {count} 후보 수)
NO_MATCH_TEXT = "조건에 맞는 곳이 없어요({detail}). 최대 이동시간을 늘려 보세요."   # detail: "확인한 N곳" 또는 "확인한 N곳, 반경 밖 M곳 제외"
LIMIT_GREETING = "{origin}에서 자동차로 {hours} 이내인 곳 {count}곳을 찾았어요. 마음에 드는 곳을 고르거나 조건을 말해 주세요."
STOPPED_TEXT = "이동시간 조회가 중간에 멈췄어요(확인한 {scanned}곳). 잠시 뒤 출발지나 최대 이동시간을 다시 골라 주세요."

# 답을 기다리는 동안 "입력 중" 말풍선에 보여 주는 글 (지금 하는 일)
PHASE_TEXT = {
    "scan": "조건에 맞는 곳을 찾는 중...",
    "travel": "이동시간을 계산하는 중...",
    "chat": "추천을 고르는 중...",
    "pick": "고른 장소를 정리하는 중...",
    "search": "비슷한 장소를 찾는 중...",       # 업로드 화면 "찾기": 사진 검색
    "check": "이동시간을 확인하는 중...",        # 업로드 화면 "찾기": 출발지가 있을 때 반경 선제외 + 이동시간 조회
}
# 걸리는 시간 안내. 한 번 실호출했을 때 약 18초였다. 근거 있는 상한은 아니고 어림값이다.
WAIT_HINT = "이동시간 계산 → 추천 고르기, 최대 50초 정도 걸려요"
# 최대 이동시간 조건이 있을 때 (후보 50~60곳 이동시간 조회 + 추천 고르기). 어림값: 조회 약 8~10초(실측은 24건 4.1초, 30건 4.5~5.5초 기준 계산) + 챗봇 15.6~30.9초(실호출 3회, 후보 9곳이면 입력이 늘어 더 걸릴 수 있음, 미확인)
WAIT_HINT_SCAN = "후보 이동시간 조회 → 추천 고르기, 최대 50초 정도 걸려요"
# 질문 없이 후보만 다시 고를 때 (후보 50~60곳 이동시간 조회만). 실측 근거: 조회 50건이 5.9초, 9.7초, 23.1초 걸렸다(요청 1건 평균 0.45~0.86초, 네이버 응답 속도에 따라 다름). 15초 → 30초
REFRESH_HINT_SCAN = "후보 이동시간을 조회하고 있어요. 최대 30초 정도 걸려요"
REFRESH_HINT = "잠시만 기다려 주세요"
PICK_HINT = "잠시만 기다려 주세요"

# 업로드 화면 "찾기" 안내. 첫 검색은 사진 검색 모델을 불러오느라 오래 걸릴 수 있다 (실측: 검색 3.1~3.2초, 이동시간 확인 5.9~23.1초. 어림값이고 모델을 처음 불러올 때의 최대 시간은 재지 않았다). 30초 → 40초
SEARCH_HINT = "처음에는 사진 검색 모델을 불러오느라 10초 정도 걸릴 수 있어요"
SEARCH_HINT_CHECK = "처음에는 모델을 불러오느라 오래 걸릴 수 있어요. 이동시간 확인까지 최대 40초 정도 걸려요"

state = st.session_state


def initial_state():
    """화면이 기억하는 값과 처음 값. 부를 때마다 새로 만든다(목록이 서로 섞이지 않게)."""
    return {
        "stage": "upload",    # "upload" → "candidates" → "chat"
        "photo": None,        # 올린 사진(bytes). 메모리에만 두고 저장하지 않는다
        "photo_name": "",
        "candidates": [],     # 후보 화면에 보여 주는 장소 (pool 의 앞쪽 TOP_K 곳)
        "pool": [],           # backend.search_places() 결과 전체 (사진 유사도 순, 최대 POOL_SIZE 곳). 최대 이동시간으로 거를 때 쓴다
        "messages": [],       # 대화 기록
        "origin_query": "",   # 고른 출발지 이름 (선택하지 않으면 "")
        "my_location": None,  # "내 위치 사용"으로 받은 출발지 {name, address, latitude(약 100m 단위), longitude}. 이 화면 세션 안에서만 쓰고 저장하지 않는다
        "locating": False,    # 위치를 묻는 중 (이때만 위치 컴포넌트가 그려진다)
        "location_request": 0,   # 위치를 묻은 횟수 (컴포넌트 key 에 써서 매번 새로 묻는다)
        "location_notice": "",   # 위치를 못 받았을 때의 안내 문구
        "applied_sig": None,  # 지금 화면의 후보에 반영된 선택 (출발지 좌표, 최대 이동시간). 이것과 달라지면 후보를 다시 고른다
        "selection": None,    # 마지막으로 후보를 고른 결과 {"sig": ..., "result": backend.refresh_candidates 결과}. 질문 때 다시 조회하지 않고 재사용한다
        "travel_by_id": {},   # 화면 후보의 이동시간 {place_id: 값} (카드와 왼쪽 목록에 보여 준다)
        "max_hours": 0,       # 최대 이동시간(시간). 0 이면 제한 없음
        "max_hours_apply": None,  # 칩이 정한 값 (다음 실행 맨 앞에서 선택칸에 반영한다. 이미 그려진 선택칸의 값은 같은 실행에서 바꿀 수 없다)
        "search_notice": "",  # 업로드 화면의 검색 실패 안내 문구
        "pending": None,      # 답을 기다리는 중이면 {"kind": "message" | "pick" | "refresh" | "search", ...}, 아니면 None
    }


def show(html_text):
    st.markdown(html_text, unsafe_allow_html=True)


def current_origin():
    """지금 고른 출발지: "내 위치"이면 받아 둔 위치, 아니면 미리 정한 역, 선택하지 않았으면 None."""
    return backend.find_origin(state.origin_query, state.my_location)


@st.cache_resource(show_spinner=False)
def location_component_dir():
    """위치 컴포넌트(ui.LOCATION_COMPONENT_HTML)를 임시 폴더의 index.html 로 한 번만 저장하고 그 폴더 경로를 돌려준다.
    들어 있는 것은 고정된 화면 코드뿐이고 위치 값은 없다. 임시 폴더는 시스템이 알아서 지운다."""
    folder = Path(tempfile.mkdtemp(prefix="front_my_location_"))
    (folder / "index.html").write_text(ui.LOCATION_COMPONENT_HTML, encoding="utf-8")
    return str(folder)


def start_location_request():
    state.locating = True
    state.location_request += 1
    state.location_notice = ""


def finish_location(value):
    """위치 컴포넌트가 돌려준 값을 읽어 출발지를 정한다.
    성공이면 출발지를 "내 위치"로 바꾼다. 거부 · 시간 초과 · 지원 안 함 · 한국 밖 · 이상한 값이면 오류 화면 없이 안내 문구만 보여 주고,
    역 선택으로 계속 진행하게 한다. 이 함수와 아래 코드는 좌표를 로그나 파일에 남기지 않는다."""
    state.locating = False
    place = None
    if isinstance(value, dict) and value.get("status") == "ok":
        place = backend.make_my_location(value.get("latitude"), value.get("longitude"))

    if place is None:
        state.location_notice = ui.LOCATION_FAILED_TEXT
        return

    state.my_location = place
    state.origin_query = MY_LOCATION_LABEL
    state.origin_choice = MY_LOCATION_LABEL   # 선택칸을 그리기 전에만 바꿀 수 있다 (render_origin_picker 안에서 이 함수가 먼저 불린다)
    state.location_notice = ""


def known_places():
    """대화에서 장소를 찾을 때 쓰는 전체 목록. 화면에 보인 후보 + 이동시간으로 고른 장소(pool)가 모두 들어 있다."""
    places = {}
    for place in list(state.candidates) + list(state.pool):
        places.setdefault(str(place.get("place_id")), place)
    return list(places.values())


def uses_dummy_data():
    """화면에 더미로 대체된 데이터(후보나 챗봇 답)가 있으면 True. 실제 연결이면 False."""
    if any(place.get("data_source") == "dummy" for place in state.candidates):
        return True
    return any(message.get("data_source") == "dummy" for message in state.messages)


# ── 동작 ─────────────────────────────────────────────────────

def request_search(photo_bytes, photo_name):
    """업로드 화면에서 "찾기"(또는 "예시 사진")를 눌렀다: 사진을 상태에 두고 "검색 중"(pending)으로 표시한 뒤 바로 다시 그린다.
    검색과 이동시간 확인은 다음 실행에서 한다(처리 중 화면에 단계별 문구를 보이고 입력 · 선택칸을 막으려고)."""
    if state.pending is not None or state.locating:
        return
    state.photo = photo_bytes
    state.photo_name = photo_name
    state.search_notice = ""
    state.pending = {"kind": "search"}


def load_pool():
    """사진 검색으로 후보 모음(pool)과 처음 후보를 만든다. 이때 후보는 "출발지 없음" 기준(유사도 순)이다.
    출발지가 정해져 있으면 이어서 refresh_selection 이 반경 선제외 → 이동시간 조회 → 후보 9곳으로 바꾼다."""
    state.pool = backend.search_places(state.photo, top_k=POOL_SIZE)
    state.candidates = state.pool[:TOP_K]
    state.travel_by_id = {}
    state.selection = None
    state.applied_sig = (None, 0)       # 지금 후보는 출발지 없음 기준. 출발지가 있으면 current_sig() 와 달라서 이어서 고른다
    state.messages = [{"role": "assistant", "text": GREETING.format(count=len(state.candidates)), "greeting": True}]


def current_sig():
    """후보에 영향을 주는 선택: (출발 좌표, 최대 이동시간). 출발지가 없으면 최대 이동시간은 영향이 없어서 (None, 0)."""
    origin = current_origin()
    if origin is None:
        return (None, 0)
    return ((round(origin["latitude"], 5), round(origin["longitude"], 5)), state.max_hours)


def selection_result():
    """지금 선택(출발지 + 최대 이동시간)에 맞는 후보 선정 결과. 아직 반영 전이거나 선택이 달라졌으면 None."""
    selection = state.selection
    if selection and selection["sig"] == current_sig():
        return selection["result"]
    return None


def greeting_text():
    """대화 시작 메시지. 최대 이동시간으로 후보를 골랐다면 그 결과를 알려 준다."""
    result = selection_result()
    origin = current_origin()
    if result and result["mode"] == "limit" and origin is not None and not result["stop"]:
        if result["no_match"]:
            return no_match_text(result)
        return LIMIT_GREETING.format(origin=origin["name"], hours=ui.format_duration(state.max_hours * 60), count=len(result["chosen"]))
    return GREETING.format(count=len(state.candidates))


def no_match_text(result):
    """채택 0곳 안내. 직선거리 반경 밖이라 조회하지 않고 뺀 곳이 있으면 "반경 밖 M곳 제외"를 덧붙인다."""
    detail = f"확인한 {result['scanned']}곳"
    if result.get("excluded"):
        detail += f", 반경 밖 {result['excluded']}곳 제외"
    return NO_MATCH_TEXT.format(detail=detail)


def apply_selection(result, sig):
    """고른 후보와 이동시간을 화면에 반영한다 (후보 화면의 카드, 대화 화면 왼쪽 목록, 시작 메시지)."""
    state.selection = {"sig": sig, "result": result}
    state.candidates = list(result["chosen"])
    state.travel_by_id = dict(result["travel_by_id"])
    state.applied_sig = sig
    if state.messages and state.messages[0].get("greeting"):
        state.messages[0] = {**state.messages[0], "text": greeting_text()}


def selection_needs_retry(result):
    """이동시간을 못 구한 후보가 있으면(일시적 오류로 건너뛴 곳 포함) 다음 질문 때 한 번 더 시도한다.
    같은 요청은 실패 후 60초 동안 다시 보내지 않고(travel_tools), 429 · 인증 오류로 멈춘 경우는 자동으로 다시 시도하지 않는다."""
    if not result or result["mode"] == "none" or result.get("stop") in ("rate_limit", "auth"):
        return False
    if result.get("stop") == "transient":  # 조회가 중간에 멈췄으면 아직 안 해 본 후보가 있다
        return True
    return any(item.get("travel_missing") for item in result["travel_by_id"].values())


def refresh_selection(show_phase=None, force=False):
    """출발지나 최대 이동시간이 바뀌었으면 후보를 다시 고른다. 이미 같은 선택이 반영돼 있으면 아무것도 하지 않는다(중복 호출 방지).
    처리가 끝난 시점의 선택(current_sig)을 기준으로 하므로, 빠르게 여러 번 바꿔도 마지막 선택만 반영된다.
    force=True 이면 같은 선택이어도 다시 고른다(못 구한 이동시간 재시도용. 이미 구한 값은 캐시라서 네이버를 다시 부르지 않는다)."""
    sig = current_sig()
    if not state.pool or (sig == state.applied_sig and not force):
        return

    origin = current_origin()
    max_minutes = state.max_hours * 60 if state.max_hours else None
    if show_phase and origin is not None:
        show_phase("scan" if max_minutes else "travel")

    try:
        result = backend.refresh_candidates(state.pool, origin, max_minutes, count=TOP_K)
    except Exception:  # 예상 못 한 오류: 후보는 그대로 두고 화면은 이어진다 (같은 선택으로 다시 시도하지 않는다)
        result = {"mode": "none", "chosen": list(state.candidates), "travel_by_id": {}, "no_match": False, "scanned": 0, "stop": ""}
    apply_selection(result, sig)


def request_refresh_if_needed():
    """출발지 · 최대 이동시간이 바뀌었으면 "후보 다시 고르기"를 요청하고 바로 다시 그린다 (처리는 다음 실행에서, 질문은 필요 없다)."""
    if state.pool and state.pending is None and current_sig() != state.applied_sig:
        state.pending = {"kind": "refresh"}
        st.rerun()


def start_over():
    """처음(사진 올리기 화면)으로 돌아간다. 사진 · 후보 · 대화와 함께 출발지, 내 위치, 최대 이동시간도 모두 지운다.
    선택칸(위젯)의 값은 이미 그려진 뒤에는 바꿀 수 없어서, 다음 실행 맨 앞(clear_widget_keys)에서 위젯 키를 지운다."""
    state.update(initial_state())
    state.clear_widget_keys = True


def submit(text):
    """사용자 문장을 대화에 바로 넣고, 답을 기다리는 중(pending)으로 표시한다. 챗봇은 다음 실행에서 부른다."""
    text = (text or "").strip()
    if not text or state.pending is not None:
        return
    if text == TIME_CHIP:  # 이 칩은 최대 이동시간을 2시간으로 정하고 질문을 보낸다
        state.max_hours_apply = 2
    state.messages.append({"role": "user", "text": text})
    # history 는 방금 넣은 내 말을 뺀 지금까지의 대화다 (예전에 챗봇에 넘기던 값과 같다)
    state.pending = {"kind": "message", "text": text, "history_len": len(state.messages) - 1}
    state.stage = "chat"


def pick(index):
    """후보 카드에서 한 곳을 골랐다: 내 말을 넣고, 그 장소를 한 카드로 보여 줄 답을 기다린다."""
    if state.pending is not None or not 0 <= index < len(state.candidates):
        return
    place = state.candidates[index]
    state.messages.append({"role": "user", "text": f"{place.get('name', '이 장소')} 알려 주세요"})
    state.pending = {"kind": "pick", "place_id": str(place.get("place_id")), "history_len": len(state.messages) - 1}
    state.stage = "chat"


def process_pending(box):
    """답을 기다리는 요청을 처리한다. box 에 "입력 중" 말풍선을 보여 주고, 답이 오면 대화에 넣는다."""
    pending = state.pending
    origin = current_origin()
    kind = pending.get("kind")
    is_pick = kind == "pick"
    is_refresh = kind == "refresh"
    max_minutes = state.max_hours * 60 if state.max_hours else None

    def show_phase(phase):
        if kind == "search":
            hint = SEARCH_HINT_CHECK if origin is not None else SEARCH_HINT
        elif is_refresh:
            hint = REFRESH_HINT_SCAN if max_minutes else REFRESH_HINT
        else:
            hint = PICK_HINT if is_pick else (WAIT_HINT_SCAN if max_minutes and origin is not None else WAIT_HINT)
        box.markdown(ui.typing_bubble(PHASE_TEXT[phase], hint), unsafe_allow_html=True)

    # 업로드 화면 "찾기": 사진 검색 → (출발지가 있으면) 반경 선제외 + 이동시간 조회 → 후보 9곳 → 후보 화면
    if kind == "search":
        show_phase("search")
        try:
            load_pool()
            refresh_selection(lambda phase: show_phase("check"))
            state.stage = "candidates"
        except Exception:  # 예상 못 한 오류: 업로드 화면에 머물고 안내만 보인다 (backend 는 검색 오류를 더미 후보로 바꿔서 보통 여기까지 오지 않는다)
            state.pool, state.candidates, state.selection = [], [], None
            state.search_notice = "사진을 검색하지 못했어요. 잠시 뒤에 다시 시도해 주세요."
        state.pending = None
        return

    # 후보 다시 고르기: 질문 없이 후보만 바꾼다 (대화에는 아무것도 추가하지 않는다)
    if is_refresh:
        refresh_selection(show_phase)
        state.pending = None
        return

    # 질문: 출발지나 최대 이동시간이 아직 후보에 반영 전이면(예: 칩이 2시간을 정한 경우) 먼저 후보를 고른다. 같은 선택이면 건너뛴다
    retry = selection_needs_retry(selection_result()) and origin is not None
    needs_refresh = bool(state.pool) and (current_sig() != state.applied_sig or retry) and not is_pick
    scanning = origin is not None and max_minutes and not is_pick
    if is_pick:
        first_phase = "pick" if origin is None else "travel"
    elif needs_refresh and origin is not None:
        first_phase = "scan" if scanning else "travel"
    else:
        first_phase = "chat"
    show_phase(first_phase)
    if needs_refresh:
        refresh_selection(show_phase, force=retry)
    history = list(state.messages[: pending.get("history_len", len(state.messages) - 1)])

    try:
        if is_pick:
            reply = backend.describe_place(pending["place_id"], state.candidates, origin, progress=show_phase)
        else:
            # 최대 이동시간 · 이미 고른 후보(selection)가 있을 때만 넘긴다 (없으면 예전과 똑같이 부른다)
            extra = {"max_minutes": max_minutes} if max_minutes else {}
            result = selection_result() if origin is not None else None
            if result is not None:
                extra["selection"] = result
            reply = backend.recommend(pending["text"], known_places(), history, origin=origin, progress=show_phase, **extra)
    except Exception:  # 예상 못 한 오류도 화면은 이어지게 한다 (backend 는 보통 여기까지 오류를 올리지 않는다)
        reply = {"text": "답을 만들지 못했어요. 잠시 뒤에 다시 말씀해 주세요.", "recommendations": [], "question": "", "data_source": "fallback"}

    # 어떤 답이 와도 "기다리는 중"은 반드시 풀린다 (답 모양이 이상해서 대화에 못 넣어도 마찬가지)
    # 화면이 중간에 끊긴 경우(BaseException)에는 풀지 않는다 → 다음 실행에서 이어서 처리
    try:
        state.messages.append({"role": "assistant", **reply})
    except Exception:
        state.messages.append({"role": "assistant", "text": "답을 만들지 못했어요. 잠시 뒤에 다시 말씀해 주세요.", "recommendations": [], "question": "", "data_source": "fallback"})
    state.pending = None


# ── 화면 ─────────────────────────────────────────────────────

def render_header(step="", busy=False):
    """머리글. 왼쪽 서비스 이름을 누르면 처음(사진 올리기) 화면으로 돌아간다."""
    with st.container(key="top_bar"):
        brand, info = st.columns(2, vertical_alignment="center")
        if brand.button(ui.BRAND, type="tertiary", key="brand", disabled=busy):
            start_over()
            st.rerun()
        with info:
            show(ui.header_info(step, dummy=uses_dummy_data()))
    show(ui.SOURCE_LINE)


def render_my_photo(size):
    show('<span class="tf-label">내가 올린 사진</span>')
    if state.photo:
        st.image(state.photo, use_container_width=True)
        show(f'<span class="tf-note">{ui.esc(state.photo_name)}</span>')
    else:
        show(ui.my_photo_placeholder(size))


def render_upload():
    busy = state.pending is not None
    render_header(busy=busy)
    intro, dropzone = st.columns(2, gap="large")

    # 네모 칸 하나 안에 "사진 고르기"와 "올린 사진"을 함께 둔다 (칸 모양은 style.css 의 .st-key-photo_box)
    with dropzone.container(key="photo_box"):
        uploaded = st.file_uploader(
            "사진을 여기로 끌어오거나 눌러서 고르세요",
            type=["jpg", "jpeg", "png"],
            help="사진은 저장하지 않아요.",
            disabled=busy,
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
        # 출발지(내 위치 / 역 / 선택 안 함)와 최대 이동시간: 후보 · 대화 화면과 같은 선택칸이고 값도 같은 session_state 에 저장된다
        render_origin_picker(busy)

        # 위치를 묻는 동안에는 검색을 시작하지 않는다 (위치가 정해진 뒤에 눌러야 그 위치로 후보를 고른다)
        search_column, sample_column = st.columns(2)
        search_clicked = search_column.button("비슷한 장소 찾기", type="primary", use_container_width=True, disabled=busy or state.locating)
        sample_clicked = sample_column.button("예시 사진으로 해보기", use_container_width=True, disabled=busy or state.locating)
        box = st.empty()   # 처리 중 단계별 문구("비슷한 장소를 찾는 중... → 이동시간을 확인하는 중...") 자리

        if state.search_notice:
            show(f'<p class="tf-note tf-note--alert" role="status">{ui.esc(state.search_notice)}</p>')
        if search_clicked and uploaded is None:
            show('<p class="tf-note">먼저 오른쪽에 사진을 한 장 올려 주세요.</p>')
        elif search_clicked:
            request_search(uploaded.getvalue(), uploaded.name)
            st.rerun()
        elif sample_clicked:
            request_search(None, "")
            st.rerun()

    show('<p class="tf-flow">예시사진 올리기, 출발지·시간 고르기 -&gt; 유사한 후보 보기 -&gt; 챗봇과 대화로 상세정보 입력</p>')

    # 검색 중이면 (화면을 다 그린 뒤에) 처리한다 → 기다리는 동안 입력 · 선택칸이 막힌 화면과 단계별 문구가 보인다
    if busy:
        process_pending(box)
        st.rerun()


def render_location_button(busy):
    """"내 위치 사용" 버튼. 누르면 이 화면에서만 브라우저에 위치를 묻는다 (컴포넌트는 묻는 동안만 그려진다)."""
    if st.button("내 위치 사용", key="use_location", use_container_width=True, disabled=busy or state.locating):
        start_location_request()
        st.rerun()

    if state.locating:
        # 컴포넌트는 안 보이게(높이 0) 그려지고, 위치를 받으면 값을 돌려주면서 화면을 다시 실행한다
        with st.container(key="geo_box"):
            component = components.declare_component("my_location", path=location_component_dir())
            value = component(key=f"my_location_{state.location_request}", default=None)
        if value is not None:
            finish_location(value)
            st.rerun()
        show('<span class="tf-note">위치를 확인하는 중이에요. 브라우저가 물어보면 "허용"을 눌러 주세요.</span>')
        if st.button("취소", key="cancel_location", type="tertiary"):
            state.locating = False
            st.rerun()
    elif state.location_notice:
        show(f'<span class="tf-note tf-note--alert" role="status">{ui.esc(state.location_notice)}</span>')


def render_origin_picker(busy=False):
    """출발지 선택칸 (후보 화면과 대화 화면에서 같이 쓴다). 첫 질문부터 이동시간을 알려 줄 수 있게 후보 화면에도 둔다."""
    show('<span class="tf-label tf-label--spaced">출발지</span>')
    render_location_button(busy)

    # 두 선택칸은 나란히 놓는다. 창이 좁아 글자가 잘리면 style.css 가 위아래로 쌓는다 (.st-key-trip_limits)
    with st.container(key="trip_limits"):
        origin_column, hours_column = st.columns([5, 4], gap="small")

    with origin_column:
        show('<span class="tf-label tf-label--spaced">또는 가까운 역</span>')
        # 목록에서 고르는 방식이라 화면이 다시 그려져도 API 를 부르지 않는다
        # 선택칸의 값은 다른 화면에 다녀오면 사라지므로, 저장해 둔 출발지(origin_query)로 다시 채운다
        # (index 를 상태로 넘기면 선택을 연달아 바꿀 때 두 번째 선택이 무시되어서 key 를 쓴다)
        choices = backend.origin_choices()  # 맨 앞 항목이 "선택하지 않음"
        if state.my_location:  # 위치를 받았으면 "내 위치"가 두 번째 항목으로 생긴다 (역으로 바꿨다가 다시 고를 수 있다)
            choices = [choices[0], MY_LOCATION_LABEL] + choices[1:]
        if state.get("origin_choice") not in choices:
            state.origin_choice = state.origin_query if state.origin_query in choices else choices[0]
        picked = st.selectbox("출발지", choices, key="origin_choice", label_visibility="collapsed", disabled=busy)
        state.origin_query = "" if picked == choices[0] else picked

    with hours_column:
        show('<span class="tf-label tf-label--spaced">최대 이동시간</span>')
        # 후보 화면과 대화 화면이 같은 값(max_hours)을 쓴다. 칩이 정한 값은 맨 앞(apply_hours_request)에서 이 선택칸에 반영된다
        if state.get("max_hours_choice") not in HOUR_LABELS:
            state.max_hours_choice = HOUR_LABELS[state.max_hours] if 0 <= state.max_hours < len(HOUR_LABELS) else HOUR_LABELS[0]
        picked_hours = st.selectbox("최대 이동시간", HOUR_LABELS, key="max_hours_choice", label_visibility="collapsed", disabled=busy)
        state.max_hours = HOURS_BY_LABEL[picked_hours]

    # 출발지(내 위치, 역)나 최대 이동시간이 바뀌었으면 질문을 기다리지 않고 바로 후보를 다시 고른다
    request_refresh_if_needed()

    origin = current_origin()
    if origin:
        place_note = "내 위치 (약 100m 단위)" if origin["name"] == MY_LOCATION_LABEL else f'{ui.esc(origin["address"])} · 역 대표 좌표'
        note = place_note
        if state.max_hours:
            note += f"<br>자동차로 {state.max_hours}시간 이내인 곳만 골라서 보여 드려요."
        elif not state.pool:  # 업로드 화면: 아직 검색 전
            note += "<br>찾기를 누르면 이동시간까지 확인해서 보여 드려요."
        else:
            note += "<br>후보의 이동시간을 바로 보여 드려요."
        show(f'<span class="tf-note">{note}</span>')
    elif state.max_hours:
        show('<span class="tf-note">최대 이동시간은 출발지를 고르면 적용돼요.</span>')
    else:
        show('<span class="tf-note">선택하지 않으면 이동시간 없이 추천해요.</span>')


def render_candidates():
    busy = state.pending is not None
    render_header("2 / 3 · 후보 보기", busy=busy)
    side, main = st.columns([1, 3], gap="large")

    with side:
        render_my_photo("tall")
        render_origin_picker(busy)
        if st.button("다른 사진 올리기", type="tertiary", disabled=busy):
            start_over()
            st.rerun()

    picked_place = None
    with main:
        box = st.empty()  # 후보를 다시 고르는 동안 "조건에 맞는 곳을 찾는 중..." 을 보여 주는 자리 (질문 없이 후보만 바꿀 때)
        result = selection_result()
        no_match = bool(result and result["mode"] == "limit" and result["no_match"] and not result["stop"])
        stopped = bool(result and result["stop"])
        count = 0 if no_match else len(state.candidates)
        origin = current_origin()
        if result and result["mode"] == "limit" and origin is not None and not no_match:
            title = f'{origin["name"]}에서 {ui.format_duration(state.max_hours * 60)} 이내 장소 {count}곳'
        else:
            title = f"분위기가 비슷한 장소 {count}곳"
        show(
            '<div class="tf-row">'
            f'<div class="tf-title tf-title--small" role="heading" aria-level="1">{ui.esc(title)}</div>'
            '<span class="tf-note">정렬:유사도 순 · 마음에 드는 곳은 "이 장소 보기"로 바로 확인해요</span>'
            "</div>"
        )
        if no_match:
            show(ui.no_match_block(no_match_text(result)))
        else:
            if stopped:
                show(f'<span class="tf-note tf-note--alert" role="status">{ui.esc(STOPPED_TEXT.format(scanned=result["scanned"]))}</span>')
            # 카드 아래에 "이 장소 보기"를 두려고 한 줄에 세 장씩 나눠서 그린다
            for start in range(0, count, 3):
                for offset, column in enumerate(st.columns(3, gap="large")):
                    index = start + offset
                    if index >= count:
                        break
                    place = state.candidates[index]
                    with column:
                        show(ui.card({**place, **state.travel_by_id.get(str(place.get("place_id")), {})}, index))
                        if st.button("이 장소 보기", key=f"pick_{index}", type="tertiary", disabled=busy):
                            picked_place = index

    show('<p class="tf-ask">추가로 원하는 조건을 말해 주세요 (말하지 않아도 괜찮아요)</p>')
    picked = None
    for column, label in zip(st.columns(len(QUICK_CONDITIONS)), QUICK_CONDITIONS):
        if column.button(label, type="tertiary", disabled=busy):
            picked = label
    typed = st.chat_input("예) 서울에서 출발해서 바다 보이는 산책길이면 좋겠어요", disabled=busy)

    if picked_place is not None:
        pick(picked_place)
        st.rerun()
    if picked or typed:
        submit(picked or typed)
        st.rerun()

    # 후보를 다시 고르는 중이면 (화면을 다 그린 뒤에) 처리한다 → 기다리는 동안 컨트롤이 막힌 화면과 진행 문구가 보인다
    if busy:
        process_pending(box)
        st.rerun()


def render_chat_card(busy, origin):
    """오른쪽 영역 전체를 둥근 채팅 카드 하나로 그린다. 입력 중 말풍선을 넣을 자리(box)를 돌려준다.

    카드 안: 제목줄 → 스크롤 메시지 영역 → 빠른 조건 칩 → 입력창(카드 안쪽 맨 아래).
    st.chat_input 은 컨테이너 안에 넣으면 화면 맨 아래에 고정되지 않고 그 자리에 그려진다 (Streamlit 소스에서 확인).
    """
    typed = None
    picked = None

    with st.container(key="chat_card"):
        status = "답변 준비 중..." if busy else (f"출발지 {origin['name']}" if origin else "출발지 선택 안 함")
        show(ui.chat_title(status))

        # 스크롤 영역은 일반 순서로 쌓고, 새 메시지가 오면 아래 pin_box 의 작은 스크립트가 맨 아래로 스크롤한다.
        with st.container(key="chat_scroll"):
            show(ui.transcript(state.messages, known_places()))
            box = st.empty()  # "입력 중" 말풍선 자리 (메시지 바로 아래, 일반 순서로 쌓이므로 맨 아래에 보인다)

        # 새 메시지가 오면 메시지 영역을 맨 아래로 스크롤한다 (token 이 바뀔 때만)
        with st.container(key="pin_box"):
            token = f"{state.stage}-{len(state.messages)}-{1 if state.pending else 0}"
            components.html(ui.PIN_TO_BOTTOM_HTML.replace("__TOKEN__", token), height=0)

        with st.container(key="chat_chips"):
            for index, (column, label) in enumerate(zip(st.columns(len(QUICK_CONDITIONS)), QUICK_CONDITIONS)):
                if column.button(label, key=f"chip_{index}", disabled=busy):
                    picked = label

        placeholder = "답을 기다리는 중이에요..." if busy else "조건을 더 말하거나 후보끼리 비교해 달라고 해 보세요"
        typed = st.chat_input(placeholder, disabled=busy)

    if picked or typed:
        submit(picked or typed)
        st.rerun()

    return box


def render_chat():
    busy = state.pending is not None
    render_header("3 / 3 · 대화로 추천", busy=busy)
    side, main = st.columns([1, 3], gap="large")

    with side:
        render_my_photo("short")
        render_origin_picker(busy)

        result = selection_result()
        limited = bool(result and result["mode"] == "limit")
        if limited and result["no_match"] and not result["stop"]:
            show('<span class="tf-label tf-label--spaced">조건에 맞는 후보 0곳</span>')
            show(ui.no_match_block(no_match_text(result)))
        else:
            label = "조건에 맞는 후보" if limited else "사진 후보"
            show(f'<span class="tf-label tf-label--spaced">{label} {len(state.candidates)}곳</span>')
            show(ui.candidate_list(state.candidates, state.travel_by_id))
        if st.button("후보 카드 다시 보기", type="tertiary", disabled=busy):
            state.stage = "candidates"
            st.rerun()

    with main:
        # 출발지는 선택칸(왼쪽)을 그린 뒤에 읽는다. 그래야 방금 바꾼 선택이 제목줄 상태에 바로 반영된다
        box = render_chat_card(busy, current_origin())

    # 화면(내 말풍선, 막힌 입력창)을 다 그린 다음에 답을 만든다 → 기다리는 동안 "입력 중" 말풍선이 보인다
    if busy:
        process_pending(box)
        st.rerun()


# ── 시작 ─────────────────────────────────────────────────────

st.set_page_config(page_title=ui.BRAND, layout="wide")
show(ui.load_css())

for key, value in initial_state().items():
    state.setdefault(key, value)

# 처음으로 돌아갔다면(start_over) 출발지 · 최대 이동시간 선택칸의 값을 지운다. 선택칸을 그리기 전이라서 지울 수 있다
if state.get("clear_widget_keys"):
    for widget_key in ("origin_choice", "max_hours_choice"):
        if widget_key in state:
            del state[widget_key]
    state.clear_widget_keys = False

# 칩("2시간 안에 갈 수 있는 곳")이 정한 최대 이동시간을 선택칸에 반영한다. 선택칸을 그리기 전이라서 값을 바꿀 수 있다
if state.max_hours_apply is not None:
    state.max_hours = state.max_hours_apply
    state.max_hours_choice = HOUR_LABELS[state.max_hours]
    state.max_hours_apply = None

RENDERERS = {"upload": render_upload, "candidates": render_candidates, "chat": render_chat}

# 단계마다 자리를 하나씩 고정해 두고, 지금 단계만 컨테이너로 그리고 나머지는 빈 요소로 둔다.
# 단계가 바뀔 때 이전 단계의 요소가 통째로 바로 지워져서, 답을 오래 기다리는 동안에도 이전 화면이 흐리게 남지 않는다.
# (같은 단계 안에서 다시 그릴 때는 같은 컨테이너를 그대로 이어 써서 깜빡이지 않는다)
# 후보 화면의 입력창도 컨테이너 안에 있어서 화면 맨 아래에 고정되지 않고 그 자리에 그려진다.
slots = {name: (st.container() if name == state.stage else st.empty()) for name in RENDERERS}
with slots[state.stage]:
    RENDERERS[state.stage]()
