"""출발지 목록 (미리 정한 기차역 6곳). API 를 부르지 않고 여기 적힌 좌표를 쓴다.

좌표 출처: 위키백과 문서의 좌표 (2026-11-10 확인)
  - 서울역, 수원역, 대전역, 부산역: ko.wikipedia.org 문서 좌표
  - 광주송정역, 강릉역: ko 문서에는 좌표가 없어서 en.wikipedia.org 문서 좌표를 썼고,
    Wikidata(P625)의 좌표와 같은 값인 것을 확인했다.
이 값은 "역 건물을 대표하는 좌표"이다. 출구나 승강장 위치와는 수십~수백 m 차이가 날 수 있다.
카카오맵, 네이버지도, 코레일 같은 공식 지도와 직접 대조하지는 않았다 (미확인).
주소는 구·시 수준의 행정구역만 적었다 (도로명 주소가 아니다).
"""

# 선택하지 않음 항목의 글자 (이 항목을 고르면 출발지 없이 추천한다)
NO_ORIGIN_LABEL = "선택하지 않음"

# "내 위치 사용"으로 받은 위치를 출발지 선택칸에서 부르는 이름
MY_LOCATION_LABEL = "내 위치"

# 내 위치 좌표를 반올림하는 소수점 자리. 3자리는 위도 기준 약 110m 라서 같은 동네에서는 같은 값이 나와 이동시간 캐시가 효과를 낸다.
# 받은 좌표는 브라우저(위치 컴포넌트)에서 이 자리로 맞춰서 보내고, Python 에서도 한 번 더 맞춘다. 자세한 좌표는 어디에도 남기지 않는다.
LOCATION_ROUND_DIGITS = 3

ORIGIN_STATIONS = [
    # 출처: ko.wikipedia.org 서울역
    {"name": "서울역", "address": "서울 용산구", "latitude": 37.55472, "longitude": 126.97083},
    # 출처: ko.wikipedia.org 수원역 (기억하던 값과 약 418m 달라서 위키백과 값을 씀)
    {"name": "수원역", "address": "경기 수원시 팔달구", "latitude": 37.26283, "longitude": 127.00264},
    # 출처: ko.wikipedia.org 대전역
    {"name": "대전역", "address": "대전 동구", "latitude": 36.33189, "longitude": 127.43452},
    # 출처: ko.wikipedia.org 부산역
    {"name": "부산역", "address": "부산 동구", "latitude": 35.11499, "longitude": 129.04209},
    # 출처: en.wikipedia.org Gwangju Songjeong station, Wikidata Q624500 (코레일 역)
    {"name": "광주송정역", "address": "광주 광산구", "latitude": 35.13784, "longitude": 126.79023},
    # 출처: en.wikipedia.org Gangneung station, Wikidata Q983377
    {"name": "강릉역", "address": "강원 강릉시", "latitude": 37.76376, "longitude": 128.89909},
]
