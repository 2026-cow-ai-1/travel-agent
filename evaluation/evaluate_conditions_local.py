# 로컬 모델 평가에 필요한 JSON 처리, 시간 측정, 파일 경로 및 Ollama 연결 기능 가져오기
import json
import time
from pathlib import Path
from ollama import Client

# 프로젝트 최상위 폴더(travel-agent)의 경로 구하기
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 프롬프트 파일의 경로 지정하기
PROMPT_PATH = PROJECT_ROOT / "agent" / "prompts" / "condition_extraction.txt"
# 프롬프트 파일의 내용을 읽어 condition_prompt에 저장
condition_prompt = PROMPT_PATH.read_text(encoding="utf-8")

# 시험 문장과 정답이 저장된 파일의 경로 지정
CASES_PATH = PROJECT_ROOT / "evaluation" / "condition_cases.json"
# JSON 파일을 읽고 파이썬 리스트로 변환해 cases에 저장
cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
# 불러온 시험 사례 수를 터미널에 즉시 출력
print(f"불러온 테스트 사례: {len(cases)}개", flush=True)
# Ollama 모델 이름 지정하기
MODEL_NAME = "qwen3:4b"

# # 로컬 Ollama 서버 주소와 요청 시간 제한을 설정해 클라이언트 만들기
client = Client(
    host="http://localhost:11434",
    timeout=120.0,
)
# Qwen 평가 결과를 저장할 JSON 파일의 경로 지정
output_path = PROJECT_ROOT / "evaluation" / "qwen_results.json"
results = []

# 시험 사례를 하나씩 꺼내 순서대로 평가
for case in cases:
    # 현재 실행 중인 사례의 ID를 터미널에 즉시 출력
    print(f"{case['id']} 실행 중...", flush=True)
    
    # 현재 시험 사례의 사용자 요청, 기준 날짜, 정답을 각각 저장
    user_request = case["input"]
    base_date = case["base_date"]
    expected = case["expected"]
    
    # 이전 시험 사례의 결과가 남지 않도록 변수 초기화
    raw_response = None
    actual = None
    error = None
    passed = False
    # 모델 호출에 걸리는 시간을 측정하기 위해 시작 시점 기록
    start_time = time.perf_counter()
    
    # Qwen에 조건 추출 규칙과 시험 문장을 전달
    try:
        response = client.chat(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": condition_prompt,  # 조건 추출 규칙
                },
                {
                    "role": "user",
                    "content": (
                        f"기준 날짜: {base_date}\n"
                        f"사용자 요청: {user_request}\n"
                        "/no_think"  # 추론 과정을 끔
                    ),
                },
            ],
            think=False, # 추론 과정 생성을 끄도록 설정
            stream=False, # 완성된 응답을 한 번에 받기
            format="json" # JSON 형식으로 응답하도록 설정
        )
        # 모델이 반환한 원본 응답 텍스트 저장
        raw_response = response.message.content
        
    # 호출 중 오류가 발생하면 오류 종류와 메시지 저장
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        
    # 호출이 끝난 시점에서 시작 시점을 빼 소요 시간(초) 계산하기
    elapsed_seconds = time.perf_counter() - start_time
    
    # 모델 호출에서 오류가 없었던 경우에만 응답 검사
    if error is None:
        try:
            # 원본 응답 텍스트를 파이썬 데이터로 변환
            actual = json.loads(raw_response)
            
            # 딕셔너리 형태이고 정답과 일치하며,
            # is_round_trip이 불리언 타입이면 통과로 처리
            passed = (
                isinstance(actual, dict)
                and actual == expected
                and type(actual.get("is_round_trip")) is bool
            )
            
        # JSON 변환에 실패하면 오류 내용 저장하기
        except (json.JSONDecodeError, TypeError) as exc:
            error = f"JSON 변환 실패: {exc}"
            
    # 현재 사례의 평가 결과와 모델 설정을 기록하기
    results.append({
        "id": case["id"],
        "model": MODEL_NAME,
        "think": False, # 추론 과정을 끈 설정으로 실행했음을 기록
        "input": user_request,
        "base_date": base_date,
        "expected": expected,
        "actual": actual,
        "raw_response": raw_response,
        "passed": passed,
        "elapsed_seconds": round(elapsed_seconds, 2),
        "error": error,
    })

    # 오류가 있으면 오류, 정답과 일치하면 통과, 그 외에는 불일치로 표시하기
    status = "오류" if error else ("통과" if passed else "불일치")
    # 현재 사례의 ID, 평가 상태, 소요 시간을 터미널에 즉시 출력
    print(
        f"{case['id']}: {status} / {elapsed_seconds:.2f}초",
        flush=True,
    )
    
    # 사례 하나의 평가가 끝날 때마다 누적 결과를 qwen_results.json에 저장
    output_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
# 전체 평가 결과에서 통과한 사례 수 계산
passed_count = sum(result["passed"] for result in results)
# 전체 사례 수와 통과한 사례 수 출력
print(f"평가 완료: {len(results)}개 중 {passed_count}개 통과")
# 결과가 저장된 파일 경로 출력
print(f"결과 파일: {output_path}")