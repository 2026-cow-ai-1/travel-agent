import os
import json
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))
key = os.getenv("TOURAPI_KEY")

if not key:
    raise SystemExit(".env의 TOURAPI_KEY를 확인해줘.")

url = "https://apis.data.go.kr/B551011/KorService2/areaBasedList2"

params = {
    "serviceKey": key,
    "MobileOS": "ETC",
    "MobileApp": "TourTest",
    "_type": "json",
    "numOfRows": 2,
    "pageNo": 1,
    "contentTypeId": 12,
    "lclsSystm1": "NA",
    "arrange": "Q",
}

try:
    response = requests.get(url, params=params, timeout=30)
except requests.RequestException:
    raise SystemExit("요청에 실패했어. 인터넷 연결을 확인해줘.")

# 응답에 인증키가 포함되더라도 화면에서는 가리기
text = response.text.replace(key, "***")

print("응답 상태:", response.status_code)

try:
    print(json.dumps(json.loads(text), ensure_ascii=False, indent=2))
except ValueError:
    print(text)
    
Path("result.json").write_text(
    json.dumps(json.loads(text), ensure_ascii=False, indent=2),
    encoding="utf-8"
)
print("result.json 파일로 저장했어.")