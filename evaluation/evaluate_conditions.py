# 조건 추출 평가에 필요한 JSON 처리, 환경변수, 시간 측정, 파일 경로 및 API 기능 가져오기
import json
import os
import time
from pathlib import Path
from dotenv import load_dotenv
from google import genai

# 프로젝트 최상위 폴더(travel-agent)의 경로 구하기
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 프로젝트 최상위 폴더의 .env 파일에서 환경변수 불러오기
load_dotenv(PROJECT_ROOT / ".env")
# 프롬프트 파일(조건 추출 규칙이 적힌 것)의 경로 지정
PROMPT_PATH = PROJECT_ROOT / "agent" / "prompts" / "condition_extraction.txt"
# 프롬프트 파일의 내용을 condition_prompt에 저장하기
condition_prompt = PROMPT_PATH.read_text(encoding="utf-8")

# 시험 문장과 정답이 저장된 파일의 경로 지정하기
CASES_PATH = PROJECT_ROOT / "evaluation" / "condition_cases.json"
# JSON 파일을 읽고 파이썬 리스트로 변환해 cases에 저장하기
cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))

# Gemini API 키를 가져와 api_key에 저장 (API 키가 없으면 오류 메시지를 표시하고 실행 중단)
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError(".env에 GEMINI_API_KEY가 있는지 확인하세요.")

#  API 키와 요청 시간 제한, 재시도 옵션을 설정해 Gemini 클라이언트 만들기
client = genai.Client(
    api_key=api_key,
    http_options={
        "timeout": 120_000,
        "retry_options": {
            "attempts": 0,
        },
    },
)

# 평가에 사용할 모델 이름 지정하기
MODEL_NAME = "gemini-3.8-flash"

# 평가 결과를 저장할 JSON 파일의 경로 지정하기
output_path = PROJECT_ROOT / "evaluation" / "gemini_results.json"
results = []

# cases에 담긴 시험 사례를 하나씩 꺼내 순서대로 평가하기
for case in cases:
    print(f"{case['id']} 실행 중...", flush=True)
    
    # 현재 시험 사례의 사용자 요청, 기준 날짜, 정답을 각각 저장
    user_request = case["input"]
    base_date = case["base_date"]
    expected = case["expected"]
    
    # 새 시험 사례를 시작할 때 이전 사례의 결과가 남지 않도록 초기화하기
    raw_response = None
    actual = None
    error = None
    passed = False
    # 현재 시험 사례의 API 호출에 걸리는 시간을 측정하기 위해 시작 시점 기록
    start_time = time.perf_counter()
    
    # Gemini에 조건 추출을 요청하고 원본 응답 텍스트 저장하기
    try:
        response = client.interactions.create(
            model=MODEL_NAME,
            system_instruction=condition_prompt,
            input=f"기준 날짜: {base_date}\n사용자 요청: {user_request}",
        )
        raw_response = response.output_text
        
    # 호출 중 오류가 발생하면 오류 종류와 메시지 저장하기
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    # 호출이 끝난 시점에서 시작 시점을 빼 소요 시간(초) 계산하기
    elapsed_seconds = time.perf_counter() - start_time

    # API 호출에서 오류가 없었던 경우에만 응답 검사
    if error is None:
        try:
            # 원본 응답 텍스트를 파이썬 데이터로 변환하기
            actual = json.loads(raw_response)
            
             # 응답이 딕셔너리이고, 정답과 일치하며,
            # is_round_trip이 불리언 타입이면 통과로 처리하기
            passed = (
                isinstance(actual, dict)
                and actual == expected
                and type(actual.get("is_round_trip")) is bool
            )
            
        # 응답을 JSON으로 변환할 수 없으면 오류 내용 저장하기
        except (json.JSONDecodeError, TypeError) as exc:
            error = f"JSON 변환 실패: {exc}"
            
    # 현재 사례의 입력, 정답, 실제 응답, 통과 여부, 소요 시간과 오류를 기록하기
    results.append({
        "id": case["id"],
        "model": MODEL_NAME,
        "input": user_request,
        "base_date": base_date,
        "expected": expected,
        "actual": actual,
        "raw_response": raw_response,
        "passed": passed,
        "elapsed_seconds": round(elapsed_seconds, 2),
        "error": error,
    })

    # 오류가 있으면 오류, 정답과 일치하면 통과, 그 외에는 불일치로 표시
    status = "오류" if error else ("통과" if passed else "불일치")
    
    # 현재 사례의 ID, 평가 상태, 소요 시간을 즉시 출력하기
    print(
        f"{case['id']}: {status} / {elapsed_seconds:.2f}초",
        flush=True,
    )
    # 사례 하나의 평가가 끝날 때마다 현재까지의 결과를 JSON 파일에 저장
    output_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
# 전체 평가 결과에서 통과한 사례 수 계산
passed_count = sum(result["passed"] for result in results)
# 전체 사례 수와 통과한 사례 수 출력
print(f"평가 완료: {len(results)}개 중 {passed_count}개 통과")
# 평가 결과가 저장된 파일 경로 출력
print(f"결과 파일: {output_path}")