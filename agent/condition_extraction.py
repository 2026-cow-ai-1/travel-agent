# 조건 추출에 필요한 환경변수, 시간측정, 날짜, 파일경로, API 기능 가져오기
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from dotenv import load_dotenv
from google import genai

# 최상위 폴더 경로 구하기
PROJECT_ROOT = Path(__file__).resolve().parent.parent
#최상위 폴더의 .env 파일에서 환경변수 불러오기
load_dotenv(PROJECT_ROOT / ".env")
# 프롬프트(조건추출 규칙) 파일의 경로 지정
PROMPT_PATH = PROJECT_ROOT / "agent" / "prompts" / "condition_extraction.txt"
# 프롬프트 파일 읽어서 저장
condition_prompt = PROMPT_PATH.read_text(encoding="utf-8")
# api키 가져오고 없으면 실행 중단
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError(".env에 GEMINI_API_KEY가 있는지 확인하세요.")

# 키를 이용해 Gemini API 요청용 클라이언트 생성
client = genai.Client(api_key=api_key)

# 사용자의 요청 입력 받음
user_request = input("여행 요청을 입력하세요: ")

# 날짜를 YYYY-MM-DD 형식으로 저장하도록 함
base_date = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
# Gemini API 호출에 걸리는 시간을 측정하기 위한 현재 시간 측정
start_time = time.perf_counter()

# Gemini에 조건 추출 프롬프트, 기준 날짜, 사용자 요청을 보내고 응답 저장
response = client.interactions.create(
    model="gemini-3.8-flash",
    system_instruction=condition_prompt,
    input=f"기준 날짜: {base_date}\n사용자 요청: {user_request}",
)

# 응답이 오면 걸린 시간 측정
elapsed_seconds = time.perf_counter() - start_time

# 응답 출력 및 걸린 시간 출력
print(response.output_text)
print(f"응답 시간: {elapsed_seconds:.2f}초")