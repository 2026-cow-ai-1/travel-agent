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


def travel_line(place):
    """ "차로 약 1시간 15분 · 62km". distance_km 과 duration_min 이 둘 다 있어야 만든다."""
    km = get_number(place, "distance_km")
    minutes = get_number(place, "duration_min")
    if km is None or minutes is None or km < 0 or minutes < 0:
        return ""
    hours, rest = divmod(round(minutes), 60)
    if hours and rest:
        duration = f"{hours}시간 {rest}분"
    elif hours:
        duration = f"{hours}시간"
    else:
        duration = f"{rest}분"
    return f"차로 약 {duration} · {km:.0f}km"


def image_url(place):
    """http(s) 주소만 쓴다. 따옴표 · 괄호 · 공백은 %XX 로 바꿔 CSS url() 안에서도 안전하게."""
    url = get_text(place, "image_url")
    if not re.match(r"https?://", url, re.IGNORECASE):
        return ""
    return quote(url, safe=":/?&=%#.-_~+,;@")


# ── 2. 작은 조각 ─────────────────────────────────────────────

def header_info(step=""):
    """머리글 오른쪽: 단계 표시와 더미 데이터 표시. (왼쪽 서비스 이름은 app.py 에서 버튼으로 그린다)"""
    step_html = f'<span class="tf-step">{esc(step)}</span>' if step else ""
    return f'<div class="tf-header-info">{step_html}<span class="tf-tag">더미 데이터</span></div>'


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


def overview_html(place):
    line = overview_line(place)
    if not line:
        return f'<p class="tf-overview tf-overview--empty">{NO_OVERVIEW}</p>'
    return f'<p class="tf-overview">{esc(line)}</p>'


# ── 3. 장소 카드 ─────────────────────────────────────────────

def card(place, index):
    percent = similarity_percent(place)
    travel = travel_line(place)
    similarity_html = f"<span>유사도 {percent}</span>" if percent else ""
    travel_html = f'<span class="tf-travel">{esc(travel)}</span>' if travel else ""
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


def candidate_list(places):
    """대화 화면 왼쪽에 두는 작은 목록: 이름과 유사도만."""
    rows = "".join(
        f"<li><span>{esc(get_text(place, 'name') or NO_NAME)}</span>"
        f"<span>{similarity_percent(place)}</span></li>"
        for place in places
    )
    return f'<ol class="tf-list">{rows}</ol>'


# ── 4. 대화 ──────────────────────────────────────────────────

def recommendation(place, rank, index):
    """추천 한 곳. place 는 후보 정보에 추천 정보(reason, distance_km, duration_min)를 합친 dict."""
    percent = similarity_percent(place)
    facts = [f"유사도 {percent}" if percent else "", travel_line(place)]
    facts_html = "".join(f"<span>{esc(fact)}</span>" for fact in facts if fact)
    reason = get_text(place, "reason")
    reason_html = f'<p class="tf-reason">{esc(reason)}</p>' if reason else ""
    return (
        '<article class="tf-rec">'
        f"{place_photo(place, index)}"
        '<div class="tf-rec-body">'
        f'<span class="tf-rank">추천 {rank}</span>'
        '<div class="tf-rec-title">'
        f'<div class="tf-rec-name" role="heading" aria-level="3">{esc(get_text(place, "name") or NO_NAME)}</div>'
        f'<span class="tf-region">{esc(get_text(place, "region") or NO_REGION)}</span>'
        "</div>"
        f"{overview_html(place)}"
        f"{reason_html}"
        f'<div class="tf-facts">{facts_html}</div>'
        "</div>"
        "</article>"
    )


def turn(message, candidates_by_id):
    """대화 한 차례. 추천은 place_id 로 후보에서 찾아 그리고, 후보에 없는 장소는 건너뛴다."""
    parts = []
    if message.get("text"):
        parts.append(f"<p>{esc(message['text'])}</p>")

    rank = 0
    for item in message.get("recommendations") or []:
        found = candidates_by_id.get(str(item.get("place_id")))
        if found is None:
            continue
        index, place = found
        rank += 1
        parts.append(recommendation({**place, **item}, rank, index))

    if message.get("question"):
        parts.append(f'<p class="tf-question">{esc(message["question"])}</p>')

    is_me = message.get("role") == "user"
    turn_class = "tf-turn tf-turn--me" if is_me else "tf-turn"
    speaker = "나" if is_me else "안내"
    return (
        f'<div class="{turn_class}">'
        f'<span class="tf-who">{speaker}</span>'
        f'<div class="tf-say">{"".join(parts)}</div>'
        "</div>"
    )


def transcript(messages, candidates):
    candidates_by_id = {
        str(place.get("place_id")): (index, place) for index, place in enumerate(candidates)
    }
    turns = "".join(turn(message, candidates_by_id) for message in messages)
    return f"<div>{turns}</div>"
