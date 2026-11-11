"""화면에 그리는 HTML 조각.

위에서부터 순서대로
  1. 값 다듬기   — 빠졌거나 이상한 값을 화면에 쓸 수 있는 글자로 바꾼다
  2. 작은 조각   — 머리글, 사진 칸
  3. 장소 카드   — 후보 카드, 후보 목록
  4. 대화        — 추천 카드, 대화 전체

장소 dict 에서 필수는 place_id, name 뿐이다.
나머지는 없으면 대체 문구를 쓰거나 그 줄을 숨긴다. 모양(CSS)은 style.css 에 있다.
"""

import html
import math
import re
from pathlib import Path
from urllib.parse import quote

BRAND = "사진으로 여행지 찾기"
SOURCE_LINE = '<p class="tf-source">장소 정보와 사진 출처: 한국관광공사 TourAPI (공공누리 제1유형)</p>'

# 사진이 뜨기 전(또는 못 불러왔을 때) 사진 칸에 보이는 무광 단색
TINTS = ["#5F6848", "#4C5F6B", "#7D6226", "#3F6360", "#8C3F2F", "#6E5560"]

NO_NAME = "이름 없는 장소"
NO_REGION = "지역 정보 없음"
NO_OVERVIEW = "소개글 준비 중"
NO_PHOTO = "사진을 불러오지 못했어요"

# 이동 수단 이름 (travel_line 이 mode 값으로 고른다)
TRAVEL_MODE_LABELS = {"car": "차로", "walk": "도보"}

# 자동차 이동시간을 구하지 못했을 때 추천 카드에 작게 보여 주는 문구
TRAVEL_MISSING_TEXT = "이동시간을 불러오지 못했어요"

# 사진을 고른 뒤에만 넣는 CSS 한 줄: "사진 고르기" 영역을 줄여 같은 칸 안에 사진 자리를 만든다.
# (고른 뒤에만 적용해야 해서 style.css 가 아니라 여기에 둔다)
COMPACT_DROPZONE = '<style>[data-testid="stFileUploaderDropzone"] { min-height: 0; }</style>'


def load_css():
    css = Path(__file__).with_name("style.css").read_text(encoding="utf-8")
    return f"<style>{css}</style>"


# ── 1. 값 다듬기 ─────────────────────────────────────────────

def esc(value):
    """화면에 넣기 전에 HTML 특수문자를 막는다."""
    return html.escape("" if value is None else str(value), quote=True)


def get_text(place, key):
    """문자열 값. 없거나 NaN 이면 빈 문자열."""
    value = place.get(key)
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def get_number(place, key):
    """숫자 값. 없거나 숫자가 아니면 None."""
    value = place.get(key)
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def overview_line(place):
    """소개글에서 HTML 태그와 줄바꿈을 걷어낸 한 줄."""
    without_tags = re.sub(r"<[^>]*>", " ", get_text(place, "overview"))
    return re.sub(r"\s+", " ", without_tags).strip()


def similarity_percent(place):
    """0.91 → "91%". 값이 없으면 빈 문자열."""
    score = get_number(place, "similarity")
    return "" if score is None else f"{round(score * 100)}%"


def format_duration(minutes):
    """분 → "7분", "1시간", "1시간 15분"."""
    hours, rest = divmod(round(minutes), 60)
    if hours and rest:
        return f"{hours}시간 {rest}분"
    if hours:
        return f"{hours}시간"
    return f"{rest}분"


def format_distance(km):
    """10km 미만은 소수점 한 자리(1.7km)로, 그 이상은 정수(62km)로. 짧은 거리가 반올림으로 뭉개지지 않게 한다."""
    return f"{km:.1f}km" if km < 10 else f"{km:.0f}km"


def travel_line(travel):
    """ "차로 약 7분 · 1.7km", "차로 약 1시간 15분 · 62km (추정)", "도보 약 29분 (추정)".

    travel 은 distance_km, duration_min, mode, source 를 담은 dict (장소 dict 도 된다).
    distance_km 과 duration_min 이 둘 다 있어야 만든다.
    mode 가 없으면 car 로 본다. source 가 "추정"으로 시작하면(추정, 추정(API 실패)) 실제 길찾기가 아니므로
    "(추정)"을 붙이고, 도보는 늘 추정이다.
    """
    km = get_number(travel, "distance_km")
    minutes = get_number(travel, "duration_min")
    if km is None or minutes is None or km < 0 or minutes < 0:
        return ""

    mode = get_text(travel, "mode") or "car"
    label = TRAVEL_MODE_LABELS.get(mode)
    if label is None:
        return ""

    duration = format_duration(minutes)
    if mode == "walk":
        return f"{label} 약 {duration} (추정)"

    line = f"{label} 약 {duration} · {format_distance(km)}"
    return f"{line} (추정)" if get_text(travel, "source").startswith("추정") else line


def travel_lines(place):
    """한 장소의 이동시간 줄 목록. place["travels"] 가 있으면 그 목록(자동차, 도보 순), 없으면 place 자신의 값 하나."""
    travels = place.get("travels")
    items = travels if isinstance(travels, list) and travels else [place]
    return [line for line in (travel_line(item) for item in items) if line]


def image_url(place):
    """http(s) 주소만 쓴다. 따옴표 · 괄호 · 공백은 %XX 로 바꿔 CSS url() 안에서도 안전하게."""
    url = get_text(place, "image_url")
    if not re.match(r"https?://", url, re.IGNORECASE):
        return ""
    return quote(url, safe=":/?&=%#.-_~+,;@")


# ── 2. 작은 조각 ─────────────────────────────────────────────

def header_info(step="", dummy=False):
    """머리글 오른쪽: 단계 표시와, 더미 데이터가 쓰였을 때만 "더미 데이터" 표시.
    (왼쪽 서비스 이름은 app.py 에서 버튼으로 그린다. 실제 검색·챗봇으로 연결된 상태면 표시를 숨긴다)"""
    step_html = f'<span class="tf-step">{esc(step)}</span>' if step else ""
    tag_html = '<span class="tf-tag">더미 데이터</span>' if dummy else ""
    return f'<div class="tf-header-info">{step_html}{tag_html}</div>'


def place_photo(place, index):
    """장소 사진 칸. 사진 파일을 저장하지 않고 image_url 원본 주소를 그대로 불러온다."""
    url = image_url(place)
    if not url:
        return f'<div class="tf-photo tf-photo--empty">{NO_PHOTO}</div>'
    name = esc(get_text(place, "name") or NO_NAME)
    tint = TINTS[index % len(TINTS)]
    return (
        f'<div class="tf-photo" role="img" aria-label="{name} 사진" style="background-color:{tint}">'
        f"{NO_PHOTO}"
        f"<div class=\"tf-photo-img\" style=\"background-image:url('{url}')\"></div>"
        "</div>"
    )


def my_photo_placeholder(size):
    """올린 사진이 없을 때(예시로 둘러볼 때) 대신 보여 주는 칸. size: "tall" | "short" """
    return f'<div class="tf-photo tf-photo--mine tf-photo--{size}">예시 사진 (사진 없이 둘러보는 중)</div>'


def overview_html(place, full=False):
    """소개글 한 줄. full=True 이면 잘라 보여 주지 않고 전체를 보여 준다(고른 장소 카드)."""
    line = overview_line(place)
    if not line:
        return f'<p class="tf-overview tf-overview--empty">{NO_OVERVIEW}</p>'
    extra = " tf-overview--full" if full else ""
    return f'<p class="tf-overview{extra}">{esc(line)}</p>'


# ── 3. 장소 카드 ─────────────────────────────────────────────

def card(place, index):
    """후보 카드 한 장. place 에 이동시간 값(travels, distance_km, duration_min, travel_missing)이 합쳐져 있으면 이동시간도 보여 준다."""
    percent = similarity_percent(place)
    lines = travel_lines(place)
    similarity_html = f"<span>유사도 {percent}</span>" if percent else ""
    travel_html = "".join(f'<span class="tf-travel">{esc(line)}</span>' for line in lines)
    if place.get("travel_missing"):
        travel_html += f'<span class="tf-travel tf-note">{esc(TRAVEL_MISSING_TEXT)}</span>'
    return (
        '<article class="tf-card">'
        f'<div class="tf-meta"><span>No. {index + 1:02d}</span>{similarity_html}</div>'
        f"{place_photo(place, index)}"
        f'<div class="tf-name" role="heading" aria-level="3">{esc(get_text(place, "name") or NO_NAME)}</div>'
        f'<span class="tf-region">{esc(get_text(place, "region") or NO_REGION)}</span>'
        f"{overview_html(place)}"
        f"{travel_html}"
        "</article>"
    )


def card_grid(places):
    cards = "".join(card(place, index) for index, place in enumerate(places))
    return f'<div class="tf-grid">{cards}</div>'


def candidate_list(places, travel_by_id=None):
    """대화 화면 왼쪽에 두는 작은 목록: 이름과 유사도, 이동시간이 있으면 그 아래에 자동차 이동시간."""
    rows = []
    for place in places:
        travel = ""
        item = (travel_by_id or {}).get(str(place.get("place_id")))
        if item:
            line = next(iter(travel_lines(item)), "")
            if line:
                travel = f'<span class="tf-list-travel">{esc(line)}</span>'
            elif item.get("travel_missing"):
                travel = f'<span class="tf-list-travel">{esc(TRAVEL_MISSING_TEXT)}</span>'
        rows.append(
            f"<li><span>{esc(get_text(place, 'name') or NO_NAME)}</span>"
            f"<span>{similarity_percent(place)}</span>{travel}</li>"
        )
    return f'<ol class="tf-list">{"".join(rows)}</ol>'


def no_match_block(text):
    """최대 이동시간 안에 갈 수 있는 곳이 없을 때 카드 대신 보여 주는 안내."""
    return f'<div class="tf-nomatch" role="status">{esc(text)}</div>'


# ── 4. 대화 ──────────────────────────────────────────────────

def recommendation(place, rank, index, detail=False):
    """추천 한 곳. place 는 후보 정보에 추천 정보(reason, distance_km, duration_min)를 합친 dict.
    detail=True 이면 후보 카드에서 직접 고른 장소를 보여 주는 카드(순위 대신 "선택한 곳", 소개글 전체)."""
    percent = similarity_percent(place)
    # 순서: 유사도, (자동차 값이 없으면 작은 안내 문구), 이동시간 줄(자동차, 도보)
    facts = [f"유사도 {percent}" if percent else ""]
    facts_html = "".join(f"<span>{esc(fact)}</span>" for fact in facts if fact)
    if place.get("travel_missing"):
        facts_html += f'<span class="tf-note">{esc(TRAVEL_MISSING_TEXT)}</span>'
    facts_html += "".join(f"<span>{esc(line)}</span>" for line in travel_lines(place))
    reason = strip_place_ids(get_text(place, "reason"))
    reason_html = f'<p class="tf-reason">{esc(reason)}</p>' if reason else ""
    article = '<article class="tf-rec tf-rec--detail">' if detail else '<article class="tf-rec">'
    rank_label = "선택한 곳" if detail else f"추천 {rank}"
    return (
        f"{article}"
        f"{place_photo(place, index)}"
        '<div class="tf-rec-body">'
        f'<span class="tf-rank">{rank_label}</span>'
        '<div class="tf-rec-title">'
        f'<div class="tf-rec-name" role="heading" aria-level="3">{esc(get_text(place, "name") or NO_NAME)}</div>'
        f'<span class="tf-region">{esc(get_text(place, "region") or NO_REGION)}</span>'
        "</div>"
        f"{overview_html(place, full=detail)}"
        f"{reason_html}"
        f'<div class="tf-facts">{facts_html}</div>'
        "</div>"
        "</article>"
    )


def sentence_key(value):
    """문장이 같은지 비교하려고 공백과 문장부호를 지운 글자. 비어 있으면 ""."""
    return re.sub(r"[^\w]", "", str(value or ""))


def repeats_sentence(text, question):
    """질문이 답변 본문에 이미 들어 있으면 True (같은 문장을 두 번 보여 주지 않으려는 용도)."""
    key = sentence_key(question)
    return bool(key) and key in sentence_key(text)


# 챗봇 답에 섞여 나오는 place_id 번호 ("place_id: 2733833", "(place_id=2733833)" 등)
PLACE_ID_CORE = r"[\(\[（]?\s*place[_\s-]?id\s*[:=：]?\s*[\"'`]?\d+[\"'`]?\s*[\)\]）]?"
PLACE_ID_RE = re.compile(r"(?:(?<=\s)|^)[-•*]\s+" + PLACE_ID_CORE + "|" + PLACE_ID_CORE, re.IGNORECASE | re.MULTILINE)


def strip_place_ids(text):
    """본문에서 place_id 번호를 지우고, 지운 자리에 남은 목록 기호 · 쉼표 · 공백을 정리한다 (번호는 사용자가 볼 정보가 아니다)."""
    text = str(text or "")
    cleaned = PLACE_ID_RE.sub("", text)
    if cleaned != text:
        cleaned = re.sub(r"[ \t]+([.,!?。，])", r"\1", cleaned)               # 괄호를 지운 뒤 마침표 앞에 남은 공백
        cleaned = re.sub(r"([,，])\s*(?:[,，]\s*)+", r"\1 ", cleaned)         # ", ," -> ","
        cleaned = re.sub(r"[ \t]*[,，][ \t]*(?=\n|$)", "", cleaned)           # 줄 끝에 남은 쉼표
        cleaned = re.sub(r"(?m)^[ \t]*[,，][ \t]*", "", cleaned)               # 줄 앞에 남은 쉼표
        cleaned = re.sub(r"(?m)^[ \t]*[-•*][ \t]*$\n?", "", cleaned)          # 내용이 없어진 목록 줄
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


def bubble_html(text, extra_class=""):
    """말풍선 본문 HTML. place_id 는 지우고, " - " 로 이어진 목록은 줄바꿈 목록으로 보여 준다.
    (챗봇이 "- 이름: ... - 지역: ..." 을 한 문단에 이어 쓰는 경우가 있어서, 하이픈이 둘 이상이면 목록으로 본다)"""
    text = strip_place_ids(text)
    if len(re.findall(r"(?:^|\s)-\s+\S", text)) >= 2:
        text = re.sub(r"(?<=\S)\s+-\s+(?=\S)", "\n- ", text)

    blocks, items = [], []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith(("- ", "• ", "* ")):
            items.append(f"<li>{esc(stripped[2:].strip())}</li>")
            continue
        if items:
            blocks.append(f'<ul class="tf-bullets">{"".join(items)}</ul>')
            items = []
        if stripped:
            blocks.append(f"<span>{esc(stripped)}</span>")
    if items:
        blocks.append(f'<ul class="tf-bullets">{"".join(items)}</ul>')

    css_class = f"tf-bubble {extra_class}".strip()
    return f'<div class="{css_class}">{"".join(blocks)}</div>'


def turn(message, candidates_by_id):
    """대화 한 차례를 말풍선으로. 챗봇은 왼쪽, 사용자는 오른쪽(모양은 style.css).
    추천은 place_id 로 후보에서 찾아 챗봇 말풍선 아래에 그리고, 후보에 없는 장소는 건너뛴다.
    질문이 답변 본문에 이미 있는 문장이면 한 번만 보여 준다."""
    parts = []
    has_cards = False
    text = message.get("text") or ""
    if text:
        parts.append(bubble_html(text))

    rank = 0
    detail = bool(message.get("detail"))
    for item in message.get("recommendations") or []:
        found = candidates_by_id.get(str(item.get("place_id")))
        if found is None:
            continue
        index, place = found
        rank += 1
        parts.append(recommendation({**place, **item}, rank, index, detail=detail))
        has_cards = True

    question = message.get("question") or ""
    if question and not repeats_sentence(text, question):
        parts.append(bubble_html(question, "tf-question"))

    is_me = message.get("role") == "user"
    turn_class = "tf-turn tf-turn--me" if is_me else "tf-turn"
    say_class = "tf-say tf-say--cards" if has_cards else "tf-say"
    return f'<div class="{turn_class}"><div class="{say_class}">{"".join(parts)}</div></div>'


def transcript(messages, candidates):
    candidates_by_id = {
        str(place.get("place_id")): (index, place) for index, place in enumerate(candidates)
    }
    turns = "".join(turn(message, candidates_by_id) for message in messages)
    return f'<div class="tf-chat">{turns}</div>'


def typing_bubble(text, hint=""):
    """챗봇이 답을 만드는 동안 보여 주는 "입력 중" 말풍선 (점 세 개가 깜빡이고, 지금 하는 일을 글로 알려 준다)."""
    hint_html = f'<span class="tf-typing-hint">{esc(hint)}</span>' if hint else ""
    return (
        '<div class="tf-typing" role="status" aria-live="polite">'
        '<div class="tf-bubble"><span class="tf-dots" aria-hidden="true"><i></i><i></i><i></i></span>'
        f'<span class="tf-typing-text">{esc(text)}</span></div>'
        f"{hint_html}"
        "</div>"
    )


def chat_title(status=""):
    """채팅 카드 맨 위 제목줄. 오른쪽에 작은 상태 글(출발지, 답변 준비 중 등)."""
    status_html = f'<span class="tf-chat-status">{esc(status)}</span>' if status else ""
    return f'<div class="tf-chat-title"><span class="tf-chat-name">여행 도우미</span>{status_html}</div>'


# ── 메시지 영역을 맨 아래로 ───────────────────────────────────

# 새 메시지가 오면(또는 처리 중 표시가 생기거나 사라지면) 메시지 영역(.st-key-chat_scroll)을 맨 아래로 스크롤하는 아주 작은 조각.
# 같은 상태(token)에서 다시 그려질 때는 사용자가 올려 둔 스크롤 위치를 그대로 둔다. 사진이 늦게 불러와져 높이가 바뀌어도 맨 아래에 머물게 몇 번 더 맞춘다.
# 화면(Streamlit)과 같은 출처의 iframe 이라 부모 화면의 요소를 읽을 수 있다. 실패해도(오류) 아무 일도 하지 않는다.
PIN_TO_BOTTOM_HTML = """<script>
(function () {
  try {
    var win = window.parent;
    var box = win.document.querySelector('.st-key-chat_scroll');
    if (!box) { return; }
    var token = "__TOKEN__";
    if (win.__tfPinToken === token) { return; }
    win.__tfPinToken = token;
    var pin = function () { box.scrollTop = box.scrollHeight; };
    pin();
    [60, 200, 500, 1200].forEach(function (ms) { setTimeout(pin, ms); });
  } catch (error) {}
})();
</script>"""


# ── 내 위치 사용 ──────────────────────────────────────────────

# 위치를 받지 못했을 때 보여 주는 안내 (오류 화면 대신 이 문장만 보이고 역 선택으로 계속 진행한다)
LOCATION_FAILED_TEXT = "위치를 가져오지 못했어요. 아래에서 가까운 역을 골라 주세요"

# 브라우저 위치를 Python 으로 전하는 아주 작은 Streamlit 컴포넌트 (서드파티 패키지 없이 Streamlit 이 주는 declare_component 만 쓴다)
# app.py 가 이 글을 임시 폴더의 index.html 로 저장해서 컴포넌트로 등록한다. 버튼을 눌러 이 컴포넌트가 그려졌을 때만 위치를 묻는다.
#   - navigator.geolocation 으로 현재 위치를 한 번 묻는다 (브라우저가 허용 여부를 사용자에게 물어본다)
#   - 위도, 경도를 소수점 3자리(약 100m)로 반올림한 값과 상태("ok", "denied", "timeout", "unavailable", "unsupported")만 부모 화면(Streamlit)에 보낸다
#   - 네트워크 요청, 저장(localStorage, 쿠키), 로그를 하지 않는다. 정확도(accuracy)도 보내지 않는다
LOCATION_COMPONENT_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>내 위치</title></head>
<body>
<script>
(function () {
  var DIGITS = 1000;          // 소수점 3자리
  var TIMEOUT_MS = 10000;     // 위치 확인 제한 시간
  var started = false;
  var finished = false;

  function post(type, data) {
    var message = { isStreamlitMessage: true, type: type };
    for (var key in data) { message[key] = data[key]; }
    window.parent.postMessage(message, window.location.origin);
  }

  function finish(value) {
    if (finished) { return; }
    finished = true;
    post("streamlit:setComponentValue", { value: value, dataType: "json" });
  }

  function round3(number) { return Math.round(number * DIGITS) / DIGITS; }

  function start() {
    if (started) { return; }
    started = true;
    post("streamlit:setFrameHeight", { height: 0 });
    if (!navigator.geolocation) { finish({ status: "unsupported" }); return; }
    var timer = setTimeout(function () { finish({ status: "timeout" }); }, TIMEOUT_MS + 2000);
    navigator.geolocation.getCurrentPosition(
      function (position) {
        clearTimeout(timer);
        finish({ status: "ok", latitude: round3(position.coords.latitude), longitude: round3(position.coords.longitude) });
      },
      function (error) {
        clearTimeout(timer);
        var code = error && error.code;
        finish({ status: code === 1 ? "denied" : (code === 3 ? "timeout" : "unavailable") });
      },
      { enableHighAccuracy: false, timeout: TIMEOUT_MS, maximumAge: 60000 }
    );
  }

  // Streamlit 이 첫 화면 정보(streamlit:render)를 보내오면 위치를 묻는다
  window.addEventListener("message", function (event) {
    if (event.source === window.parent && event.data && event.data.type === "streamlit:render") { start(); }
  });
  post("streamlit:componentReady", { apiVersion: 1 });
})();
</script>
</body></html>
"""
