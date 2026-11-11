"""챗봇(희림님 travel_chatbot.py)을 화면(backend.py)이 받는 모양으로 감싸는 함수 모음.

하는 일
  1. 출발지가 있으면 후보 9곳의 자동차 이동시간을 먼저 구한다 (travel_tools.py, 성공은 캐시)
     최대 이동시간 조건이 함께 있으면 후보를 넓게(50곳, 부족하면 60곳까지) 조회해서 제한 이내인 곳 9곳만 고른다
  2. 후보 9곳(소개글 150자까지)과 이동시간을 글자로 만들어 챗봇에 보낸다 (예전에는 사진 100장을 통째로 보냈다)
  3. 답을 JSON 으로 받아 {"text", "recommendations", "question"} 으로 바꾼다
     후보에 없는 place_id 는 버리고, 추천은 한 번에 최대 MAX_RECOMMENDATIONS(5)곳까지만 쓴다 (수는 사용자 요청에 따라 프롬프트 7번이 정한다)
  4. 챗봇을 부르지 못하면(키 없음, 타임아웃 등) 화면에 오류를 띄우지 않고
     사진이 비슷한 상위 FALLBACK_COUNT(3)곳을 보여 주는 대체 답을 돌려준다

키(.env)는 travel_chatbot.py 가 읽는다. 이 파일은 키를 읽지 않는다.
대화 기록은 previous_response_id 가 아니라 화면이 가진 대화(history)를 다시 보내는 방식이다.
"""

import json
import logging
import re
import sys
from pathlib import Path

import travel_tools
import ui

FRONT_DIR = Path(__file__).resolve().parent
EMBEDDING_DIR = FRONT_DIR.parent / "embedding_all"

# 챗봇에 보내는 후보 수
CHATBOT_CANDIDATE_COUNT = travel_tools.CHATBOT_CANDIDATE_COUNT
CANDIDATE_LIMIT = CHATBOT_CANDIDATE_COUNT

# 후보 소개글을 보내는 최대 글자 수 (비용을 줄이려고 자른다)
OVERVIEW_MAX_CHARS = 150

# 챗봇에 다시 보내는 이전 대화의 최대 개수. 가정값이며 근거 없는 숫자다.
HISTORY_MAX_ITEMS = 6

# 한 번에 추천하는 최대 장소 수 (프롬프트 7번 규칙과 같다). 3 → 5: 사용자가 수를 말하면 그 수만큼(예: "가장 ~한 곳" 1곳), 말하지 않으면 보통 2~3곳
MAX_RECOMMENDATIONS = 5

# 챗봇을 부르지 못했을 때 대체 답으로 보여 주는 장소 수 (사진이 비슷한 상위 3곳. 챗봇 추천 수 상한과 따로 둔다)
FALLBACK_COUNT = 3

# 대화 기록에 남기는 이전 추천 이유의 최대 글자 수 (입력 토큰을 아끼려고 짧게 자른다)
HISTORY_REASON_CHARS = 30

# 챗봇 입력 글자 수를 셀 때 더하는 안내문 길이(chatbot_response 안의 고정 문장). 어림값이다.
WRAPPER_CHARS = 190

# 형식을 거부당했을 때(400) 한 번 더 보내면서 붙이는 JSON 지시
JSON_INSTRUCTION = (
    "\n\n답변은 설명이나 코드블록 없이 아래 모양의 JSON 글자만 출력하세요.\n"
    '{"text": "답변", "recommendations": [{"place_id": "후보의 place_id", "reason": "이유"}], "question": "질문"}\n'
    "추천할 곳이 없으면 recommendations 는 빈 목록, 질문이 없으면 question 은 빈 글자로 두세요."
)

# 답을 받을 JSON 형식 (OpenAI text.format, strict). gpt-5-mini 가 이 형식을 받아 주는지는 확인되지 않았다.
REPLY_FORMAT = {
    "type": "json_schema",
    "name": "travel_reply",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "사용자의 질문에 먼저 직접 답하는 한두 문장. 장소의 이름 · 지역 · 이동시간 · 이유는 나열하지 않는다(카드에 표시됨). 하나를 골라 달라고 했으면 '가장 ~한 곳은 ○○입니다' 한 문장으로 답한다."},
            "recommendations": {
                "type": "array",
                "description": "후보 목록 안에서 고른 장소. 사용자가 말한 수만큼(가장 ~한 곳이면 1곳), 말하지 않으면 보통 2~3곳, 최대 5곳. 고르지 못했으면 빈 목록.",
                "items": {
                    "type": "object",
                    "properties": {
                        "place_id": {"type": "string", "description": "후보 목록에 있는 place_id"},
                        "reason": {"type": "string", "description": "사용자 요청과 맞는 이유"},
                    },
                    "required": ["place_id", "reason"],
                    "additionalProperties": False,
                },
            },
            "question": {"type": "string", "description": "답에 따라 추천이 달라질 때만 묻는 질문 한 개. 본문에 쓴 질문은 반복하지 않고, 필요 없으면 빈 글자."},
        },
        "required": ["text", "recommendations", "question"],
        "additionalProperties": False,
    },
}

log = logging.getLogger("front.chat")


# travel_chatbot.py 를 불러올 수 있게 경로를 한 번 추가
def add_chatbot_path():
    path = str(EMBEDDING_DIR)
    if path not in sys.path:
        sys.path.insert(0, path)


# ── 챗봇에 보낼 글자 만들기 ───────────────────────────────────

# 글을 한 줄로 만들고, 길면 limit 글자에서 잘라 …을 붙이는 함수
def shorten_text(value, limit=OVERVIEW_MAX_CHARS):
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit] + "…"


# 후보마다 이동시간을 구해서 place_id 로 찾을 수 있게 돌려주는 함수 (출발지가 없으면 빈 딕셔너리)
def get_candidate_travel(candidates, origin):
    if origin is None:
        return {}

    picks = [{"place_id": place.get("place_id")} for place in candidates]
    items = travel_tools.add_travel_time(picks, candidates, origin, max_places=len(candidates))
    return {str(item.get("place_id")): item for item in items}


# 후보 한 곳의 이동시간을 챗봇이 읽을 글로 바꾸는 함수
def make_travel_text(item, origin):
    # 1. 출발지를 고르지 않았으면 챗봇이 출발지 선택을 안내할 수 있게 그 사실을 적는다
    if origin is None:
        return "정보 없음 (출발지를 선택하지 않음)"

    lines = []
    travels = (item or {}).get("travels") or []

    # 2. 자동차는 읽기 쉬운 시간과 분, 거리를 함께 적는다 (값 없이 구하지 못한 경우도 알려 준다)
    car = next((travel for travel in travels if travel.get("mode") == "car"), None)
    if car is not None:
        minutes = car["duration_min"]
        lines.append(f"자동차 약 {ui.format_duration(minutes)} ({round(minutes)}분), {car['distance_km']:.1f}km")
    elif (item or {}).get("travel_missing"):
        lines.append("자동차 이동시간 정보 없음 (불러오지 못함)")

    # 3. 도보는 추정값이라는 것을 적는다
    walk = next((travel for travel in travels if travel.get("mode") == "walk"), None)
    if walk is not None:
        lines.append(f"도보 약 {ui.format_duration(walk['duration_min'])} (추정)")

    return "; ".join(lines) if lines else "정보 없음"


# 후보 목록과 출발지를 챗봇에 보낼 JSON 글자로 만드는 함수
def make_candidates_text(candidates, origin, travel_by_id, condition_note=""):
    items = []
    for place in candidates[:CANDIDATE_LIMIT]:
        similarity = place.get("similarity")
        items.append({
            "place_id": str(place.get("place_id")),
            "name": place.get("name", ""),
            "region": place.get("region", ""),
            "address": place.get("address", ""),
            "similarity": None if similarity is None else round(float(similarity), 3),
            "overview": shorten_text(place.get("overview")),
            "이동시간": make_travel_text(travel_by_id.get(str(place.get("place_id"))), origin),
        })

    payload = {"출발지": None if origin is None else origin["name"], "후보": items}
    if condition_note:
        payload["이동시간 조건"] = condition_note
    return json.dumps(payload, ensure_ascii=False)


# 최대 이동시간 조건을 챗봇이 읽을 문장으로 만드는 함수 (scan 은 travel_tools.select_by_travel_time 의 결과)
def make_condition_note(max_minutes, scan):
    limit = ui.format_duration(max_minutes)

    # 1. 제한 이내인 곳이 있으면 그 곳들만 후보로 보냈다고 알린다
    if not scan["no_match"]:
        note = f"사용자가 최대 이동시간 {limit}을 골랐어요. 자동차 이동시간이 {limit} 이내인 곳만 후보로 보냈어요."
        if scan["stop"]:
            note += " (이동시간 조회를 일부만 마쳐서 더 있을 수 있어요.)"
        return note

    # 2. 조회가 중간에 멈췄으면 조건을 확인하지 못한 것이다 (없다고 단정하지 않는다)
    if scan["stop"]:
        return (f"사용자가 최대 이동시간 {limit}을 골랐지만, 이동시간 조회가 중간에 멈춰서 조건을 확인하지 못했어요. "
                "아래 후보는 사진이 비슷한 순서이고, 이동시간이 '정보 없음'인 곳은 모른다고 알려 주세요.")

    # 3. 조회했는데 제한 이내인 곳이 하나도 없다 (직선거리가 너무 멀어 조회하지 않고 뺀 곳이 있으면 함께 알린다)
    excluded = scan.get("excluded", 0)
    far = f" 직선거리가 너무 멀어 이동시간을 조회하지 않고 뺀 곳도 {excluded}곳 있어요." if excluded else ""
    return (f"사용자가 최대 이동시간 {limit}을 골랐지만, 조회한 {scan['scanned']}곳 중 자동차로 {limit} 이내인 곳이 없었어요.{far} "
            "먼저 조건에 맞는 곳이 없다고 알리고, 아래 후보(모두 제한을 넘음) 중 가까운 곳을 소개하세요.")


# 화면의 대화 기록을 챗봇에 다시 보낼 짧은 글 목록으로 바꾸는 함수 (최근 HISTORY_MAX_ITEMS 개)
def build_chat_history(messages, candidates):
    names = {str(place.get("place_id")): place.get("name", "") for place in candidates}

    history = []
    for message in messages[-HISTORY_MAX_ITEMS:]:
        if message.get("role") == "user":
            history.append({"role": "user", "text": str(message.get("text", ""))})
            continue

        # 챗봇의 이전 답은 글과 추천한 장소 이름(+ 이유 앞 HISTORY_REASON_CHARS 글자), 질문만 남긴다 (HTML 이나 이동시간 값은 보내지 않음)
        # 이유를 남기는 것은 다음 답이 이전 설명을 반복하거나 모순되지 않게 하려는 것이다
        parts = [str(message.get("text", ""))]
        picked = []
        for item in message.get("recommendations") or []:
            name = names.get(str(item.get("place_id")), "")
            if name:
                reason = " ".join(str(item.get("reason", "")).split())[:HISTORY_REASON_CHARS]
                picked.append(f"{name}({reason})" if reason else name)
        if picked:
            parts.append("추천: " + ", ".join(picked))
        if message.get("question"):
            parts.append(str(message["question"]))
        history.append({"role": "assistant", "text": " ".join(part for part in parts if part)})

    return history


# ── 챗봇 답 읽기 ──────────────────────────────────────────────

# 챗봇의 글에서 JSON 을 꺼내는 함수 (코드블록이나 앞뒤 설명이 붙어도 읽는다). 못 읽으면 None
def extract_json(output_text):
    text = (output_text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)

    for candidate_text in (text, text[text.find("{"):text.rfind("}") + 1] if "{" in text else ""):
        try:
            data = json.loads(candidate_text)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data

    return None


# 챗봇 답(글자)을 화면이 받는 모양으로 바꾸는 함수. (답, 읽은 결과 정보)를 돌려줌
def parse_chatbot_reply(output_text, candidates):
    info = {"parsed": False, "dropped": 0, "trimmed": 0}
    data = extract_json(output_text)

    # 1. JSON 이 아니면 챗봇의 글을 추천 카드 없이 그대로 보여 준다
    if data is None:
        text = (output_text or "").strip()
        if not text:
            raise ValueError("챗봇 답이 비어 있어요.")
        return {"text": text, "recommendations": [], "question": ""}, info

    info["parsed"] = True
    known_ids = {str(place.get("place_id")) for place in candidates}

    # 2. 후보에 없는 place_id, 같은 장소 반복은 버린다 (몇 개 버렸는지 기록)
    recommendations = []
    seen = set()
    for item in data.get("recommendations") or []:
        if not isinstance(item, dict):
            info["dropped"] += 1
            continue

        place_id = str(item.get("place_id", "")).strip()
        if place_id not in known_ids or place_id in seen:
            info["dropped"] += 1
            continue

        seen.add(place_id)
        reason = item.get("reason")
        recommendations.append({"place_id": place_id, "reason": reason.strip() if isinstance(reason, str) else ""})

    # 3. 한 번에 MAX_RECOMMENDATIONS(5)곳까지만
    if len(recommendations) > MAX_RECOMMENDATIONS:
        info["trimmed"] = len(recommendations) - MAX_RECOMMENDATIONS
        recommendations = recommendations[:MAX_RECOMMENDATIONS]

    text = data.get("text") if isinstance(data.get("text"), str) else ""
    question = data.get("question") if isinstance(data.get("question"), str) else ""
    if not text.strip() and not recommendations and not question.strip():
        raise ValueError("챗봇 답이 비어 있어요.")

    return {"text": text.strip(), "recommendations": recommendations, "question": question.strip()}, info


# 후보에 구해 둔 이동시간 값을 추천 항목에 옮겨 담는 함수 (추천 때 네이버를 다시 부르지 않으려고)
def copy_travel_fields(recommendation, travel_item):
    new_item = dict(recommendation)
    for key in travel_tools.TRAVEL_KEYS:
        if travel_item and key in travel_item:
            new_item[key] = travel_item[key]
    return new_item


# 챗봇을 부르지 못했을 때 보여 줄 대체 답을 만드는 함수 (사진이 비슷한 상위 3곳)
def make_fallback_reply(candidates, travel_by_id, no_match=False):
    recommendations = []
    for place in candidates[:FALLBACK_COUNT]:
        similarity = place.get("similarity")
        reason = "사진 분위기가 비슷한 장소예요." if similarity is None else f"사진 분위기가 비슷한 장소예요 (유사도 {round(similarity * 100)}%)."
        recommendations.append(copy_travel_fields({"place_id": str(place.get("place_id")), "reason": reason}, travel_by_id.get(str(place.get("place_id")))))

    return {
        "text": ("챗봇을 불러오지 못했어요. 최대 이동시간 안에 갈 수 있는 곳은 찾지 못해서, 사진이 비슷한 순서대로 보여 드려요."
                 if no_match else "챗봇을 불러오지 못해서, 사진이 비슷한 순서대로 장소를 보여 드려요."),
        "recommendations": recommendations,
        "question": "",
    }


# ── 한 번의 대화 ──────────────────────────────────────────────

# 지금 어느 단계("travel" 이동시간 계산, "chat" 추천 고르기)인지 화면에 알리는 함수
# 화면 표시용이라 콜백에서 오류가 나도 대화에는 영향이 없게 한다
def notify_progress(progress, phase):
    if progress is None:
        return
    try:
        progress(phase)
    except Exception:
        pass


# 챗봇을 부르고 답을 읽어 화면이 받는 모양으로 돌려주는 함수. (답, 상태 정보)를 돌려줌
# progress: 단계가 바뀔 때 부르는 함수 (없어도 됨). 화면의 "입력 중" 표시를 바꾸는 데 쓴다
# max_minutes: 최대 이동시간(분). 출발지와 함께 있으면 후보를 이동시간으로 거른다. 없으면 candidates 앞쪽 9곳을 그대로 쓴다
# selection: backend.refresh_candidates 가 이미 돌려준 결과. 있으면 다시 조회하지 않고 그 후보와 이동시간을 그대로 쓴다
#            (화면의 후보 카드, 챗봇 입력, 추천 카드가 같은 값을 쓰게 하려는 것)
def ask_chatbot(message, candidates, messages, origin, progress=None, max_minutes=None, selection=None):
    pool = list(candidates)
    scan = None
    condition_note = ""

    if selection is not None and origin is not None:
        # 1-0. 이미 고른 후보를 그대로 쓴다 (네이버, 단계 알림 없음)
        candidates = list(selection["chosen"])
        travel_by_id = selection["travel_by_id"]
        if selection.get("mode") == "limit":
            scan = selection
            condition_note = make_condition_note(max_minutes or 0, scan) if max_minutes else ""
    elif origin is not None and max_minutes:
        # 1-a. 후보를 넓게 훑어서 제한 이내인 곳만 고른다 (이때 구한 이동시간을 챗봇 입력과 추천 카드에 그대로 쓴다)
        notify_progress(progress, "scan")
        try:
            scan = travel_tools.select_by_travel_time(pool, origin, max_minutes)
            candidates = scan["chosen"]
            travel_by_id = scan["travel_by_id"]
            condition_note = make_condition_note(max_minutes, scan)
        except Exception:  # 예상 못 한 오류: 거르지 않고 유사도 상위 후보로 진행 (화면은 이어진다)
            scan = None

    if scan is None and not (selection is not None and origin is not None):
        # 1-b. 출발지가 있으면 후보 9곳의 이동시간을 먼저 구함 (성공은 캐시, 실패해도 챗봇은 계속 부름)
        candidates = pool[:CANDIDATE_LIMIT]
        if origin is not None:
            notify_progress(progress, "travel")
        travel_by_id = get_candidate_travel(candidates, origin)

    info = {"path": "", "chars": 0, "dropped": 0, "trimmed": 0, "error": "", "scan": scan,
            "travel": travel_tools.summarize_travel_sources(list(travel_by_id.values()))}

    # 2. 챗봇에 보낼 글 만들기 (보내는 글자 수는 내용 없이 숫자만 기록)
    candidates_text = make_candidates_text(candidates, origin, travel_by_id, condition_note)
    history = build_chat_history(messages, pool)

    try:
        add_chatbot_path()
        import travel_chatbot as bot

        info["chars"] = len(bot.TRAVEL_PROMPT) + len(candidates_text) + len(message) + sum(len(item["text"]) for item in history) + WRAPPER_CHARS
        log.info("OpenAI 입력 글자 수 약 %d (후보 %d곳, 대화 %d개)", info["chars"], len(candidates), len(history))

        # 3. JSON 형식으로 요청. 서버가 형식을 거부하면(400) JSON 지시를 붙여 한 번 더 보냄
        notify_progress(progress, "chat")
        try:
            result = bot.chatbot_response(message, candidates_text, history=history, text_format=REPLY_FORMAT)
            info["path"] = "json_schema"
        except Exception as error:
            from openai import BadRequestError

            if not isinstance(error, BadRequestError):
                raise
            result = bot.chatbot_response(message + JSON_INSTRUCTION, candidates_text, history=history)
            info["path"] = "json_prompt"

        # 4. 답 읽기 (JSON 이 아니면 글만, 후보에 없는 place_id 는 버림)
        reply, parsed = parse_chatbot_reply(result.output_text, candidates)
        info["dropped"], info["trimmed"] = parsed["dropped"], parsed["trimmed"]
        if not parsed["parsed"]:
            info["path"] = "text_only"
        reply["recommendations"] = [copy_travel_fields(item, travel_by_id.get(item["place_id"])) for item in reply["recommendations"]]
    except Exception as error:  # 키 없음, 타임아웃, 요금·한도, 빈 답 등: 오류 종류만 기록하고 대체 답
        info["path"] = "fallback"
        info["error"] = type(error).__name__
        reply = make_fallback_reply(candidates, travel_by_id, no_match=bool(scan and scan["no_match"]))

    return reply, info


# ── 후보 하나 골라서 보기 ─────────────────────────────────────

# 후보 카드에서 한 곳을 골랐을 때 보여 줄 답을 만드는 함수 (챗봇은 부르지 않는다)
# 이름, 지역, 이동시간(자동차, 가까우면 도보 추정), 소개글을 한 카드로 보여 주려고 추천 카드 모양으로 돌려준다
def describe_place(place_id, candidates, origin, progress=None):
    place = next((item for item in candidates if str(item.get("place_id")) == str(place_id)), None)
    if place is None:
        raise ValueError("고른 장소가 후보에 없어요.")

    # 1. 출발지가 있으면 이 장소의 이동시간을 구함 (같은 요청은 캐시, 실패하면 값 없음)
    if origin is not None:
        notify_progress(progress, "travel")
    travel_by_id = get_candidate_travel([place], origin)

    # 2. 카드 한 장 (이유 칸은 비우고, 소개글은 화면에서 전체를 보여 줌)
    pid = str(place.get("place_id"))
    card = copy_travel_fields({"place_id": pid, "reason": ""}, travel_by_id.get(pid))

    text = f"{place.get('name', '')}에 대해 알려 드릴게요."
    if origin is None:
        text += " 출발지를 고르면 이동시간도 알려 드려요."

    return {
        "text": text,
        "recommendations": [card],
        "question": "",
        "detail": True,
        "data_source": "dummy" if place.get("data_source") == "dummy" else "real",
    }
