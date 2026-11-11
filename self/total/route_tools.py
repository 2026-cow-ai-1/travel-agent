### 이동 거리와 이동시간 관련 함수를 모아둔 파일
### 도보는 직선거리 기반 추정값으로, 자동차는 네이버 클라우드 Directions 5 API로 구한다.
### 자동차 API가 일시적으로 실패하면 몇 번 다시 시도한다. 그래도 실패하면
### 기본(fallback_to_estimate=True)은 추정값으로 대체하고, False 로 부르면 DrivingTimeError 를 낸다.
### 파일 저장은 하지 않는다.
###
### 네이버 Directions 5 확인 내용 (공식 문서 api.ncloud-docs.com, 2026-11-10 확인)
### - 주소: https://maps.apigw.ntruss.com/map-direction/v1/driving (GET)
###   신규 VPC 문서(application-maps-directions5)의 주소이다.
###   이전 문서(ai-naver-mapsdirections-driving)에는 naveropenapi.apigw.ntruss.com 으로 나와 있다.
###   이전 주소가 지금도 동작하는지, 언제까지 쓸 수 있는지는 미확인이다.
### - 헤더 이름: x-ncp-apigw-api-key-id, x-ncp-apigw-api-key (값은 .env에서만 읽는다)
### - start, goal: "경도,위도" 순서 (위도,경도가 아님)
### - 응답: code가 0이면 성공, route.traoptimal[0].summary 안에
###   distance는 미터, duration은 밀리초
### - 무료 한도, 요금, 약관: 문서에서 미확인 (사람이 직접 확인해야 함)
import math
import os
import time
from numbers import Real
from pathlib import Path

import requests
from dotenv import load_dotenv


# self 폴더에 있는 .env 읽기
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_PATH)


# 한국 좌표 범위 (위도 33~39, 경도 124~132)
MIN_LATITUDE = 33.0
MAX_LATITUDE = 39.0
MIN_LONGITUDE = 124.0
MAX_LONGITUDE = 132.0

# 지구 평균 반지름(km), 하버사인 계산에 사용
EARTH_RADIUS_KM = 6371.0

# 자동차 평균 속도(km/h)
# 가정값이며 실제 도로·교통 상황과의 오차는 확인되지 않았다.
CAR_SPEED_KMH = 60

# 도보 평균 속도(km/h)
# 가정값이며 실제 보행 속도와의 오차는 확인되지 않았다.
WALK_SPEED_KMH = 4

# 직선거리 대비 실제 보행 경로가 길어지는 비율
# 가정값이며 실제 길과의 오차는 확인되지 않았다.
WALK_DETOUR_FACTOR = 1.3

# 지금 계산할 수 있는 이동 수단 (대중교통은 아직 지원하지 않음)
SUPPORTED_MODES = ("car", "walk")

# 네이버 Directions 5 (자동차 길찾기) 주소
# 가정값이 아니라 공식 문서의 주소이며, 이전 주소와의 차이는 파일 맨 위 설명에 적었다.
DIRECTIONS_URL = "https://maps.apigw.ntruss.com/map-direction/v1/driving"

# 한 번의 요청에서 API 응답을 기다리는 최대 시간(초)
# 아래 재시도 숫자(5초, 2번, 0.5초, 12초, 2초)는 모두 제안값이며 근거 없는 가정이다.
# 5초가 네이버의 정상 응답을 자르지 않는지는 확인되지 않았다 (응답 시간을 재지 않았다).
REQUEST_TIMEOUT_SECONDS = 5

# 일시적 오류(타임아웃, 연결 오류, HTTP 5xx)에서만 다시 시도하는 최대 횟수 (처음 시도는 제외)
MAX_RETRIES = 2

# 다시 시도하기 전에 기다리는 시간(초)
RETRY_WAIT_SECONDS = 0.5

# 첫 요청부터 마지막 시도가 끝날 때까지의 전체 마감(초)
# 계산: 시도 3번 x 타임아웃 5초 + 대기 2번 x 0.5초 = 16초라서 약 12초를 넘는다.
# 그래서 마감을 두고, 다음 시도를 시작할 때 남은 시간이 MIN_ATTEMPT_SECONDS 미만이면 더 시도하지 않는다.
#   - 계속 타임아웃이면: 5 + 0.5 + 5 = 10.5초에서 멈춘다 (2번 시도, 세 번째는 남은 1초라 건너뜀)
#   - 빨리 실패하면(HTTP 5xx 등): 3번 모두 시도한다 (대기 합계 1초)
# requests 의 timeout 은 연결, 읽기 각 단계별 제한이라 전체가 정확히 12초 이내라는 보장은 아니다.
TOTAL_DEADLINE_SECONDS = 12

# 다시 시도하려면 남아 있어야 하는 최소 시간(초)
MIN_ATTEMPT_SECONDS = 2


# 위도와 경도가 한국 범위 안의 숫자인지 확인하는 함수
def is_valid_coordinate(latitude, longitude):
    # 1. 숫자가 아니면 False (True/False도 숫자로 보지 않음)
    for value in (latitude, longitude):
        if isinstance(value, bool) or not isinstance(value, Real):
            return False

    # 2. 한국 범위 안인지 확인 (NaN은 비교가 모두 False라서 여기서 걸러짐)
    return (
        MIN_LATITUDE <= latitude <= MAX_LATITUDE
        and MIN_LONGITUDE <= longitude <= MAX_LONGITUDE
    )


# 두 좌표 사이의 직선거리(km)를 하버사인 공식으로 계산하는 함수
def haversine_km(origin, destination):
    # 1. 출발지와 도착지가 올바른 좌표 딕셔너리인지 확인
    for label, point in (("출발지", origin), ("도착지", destination)):
        if (
            not isinstance(point, dict)
            or "latitude" not in point
            or "longitude" not in point
        ):
            raise ValueError(
                f"{label} 좌표를 latitude, longitude가 있는 딕셔너리로 입력해 주세요."
            )

        if not is_valid_coordinate(point["latitude"], point["longitude"]):
            raise ValueError(
                f"{label} 좌표를 한국 범위(위도 33~39, 경도 124~132) 안의 숫자로 입력해 주세요."
            )

    # 2. 각도를 라디안으로 바꾸기
    lat1 = math.radians(origin["latitude"])
    lat2 = math.radians(destination["latitude"])
    delta_lat = lat2 - lat1
    delta_lon = math.radians(destination["longitude"] - origin["longitude"])

    # 3. 하버사인 공식으로 두 점 사이의 각도 계산
    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    # 계산 오차로 a가 1을 아주 조금 넘는 경우를 막기 위해 min 사용
    angle = 2 * math.asin(math.sqrt(min(1.0, a)))

    # 4. 지구 반지름을 곱해서 km로 반환
    return EARTH_RADIUS_KM * angle


# 직선거리와 평균 속도로 이동시간을 추정하는 함수 (실제 길찾기 결과가 아님)
def estimate_travel_time(origin, destination, mode="car"):
    # 1. 지원하는 이동 수단인지 확인
    if mode not in SUPPORTED_MODES:
        raise ValueError("이동 수단(mode)을 'car' 또는 'walk'로 입력해 주세요.")

    # 2. 직선거리 계산 (좌표가 잘못되면 haversine_km에서 ValueError)
    distance_km = haversine_km(origin, destination)

    # 3. 도보는 직선거리에 우회 계수를 곱하고, 이동 수단별 평균 속도 고르기
    if mode == "walk":
        distance_km = distance_km * WALK_DETOUR_FACTOR
        speed_kmh = WALK_SPEED_KMH
    else:
        speed_kmh = CAR_SPEED_KMH

    # 4. 거리 ÷ 평균 속도 = 시간, 분 단위로 바꾸기
    duration_min = distance_km / speed_kmh * 60

    # 5. 추정값이라는 표시와 함께 반환
    return {
        "distance_km": round(distance_km, 1),
        "duration_min": round(duration_min, 1),
        "mode": mode,
        "source": "추정",
    }


# 자동차 이동시간을 구하지 못했을 때(fallback_to_estimate=False) 던지는 오류. 키나 응답 내용은 담지 않는다.
class DrivingTimeError(Exception):
    def __init__(self, transient):
        super().__init__("자동차 이동시간을 불러오지 못했어요.")
        # True 이면 일시적 오류(타임아웃, 연결 오류, HTTP 5xx)라서 잠시 뒤 다시 시도해 볼 만하다
        self.transient = transient


# 다시 시도해 볼 만한 일시적 오류인지 알려 주는 함수 (타임아웃, 연결 오류, HTTP 5xx)
def is_retryable_error(error):
    # 1. 인증서 오류는 다시 해도 낫지 않아서 제외 (SSLError 는 ConnectionError 의 하위 클래스)
    if isinstance(error, requests.exceptions.SSLError):
        return False

    # 2. 타임아웃, 연결 오류
    if isinstance(error, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
        return True

    # 3. HTTP 5xx 만 (401, 403, 429, 그 밖의 4xx 는 다시 해도 같다)
    if isinstance(error, requests.exceptions.HTTPError):
        status = getattr(error.response, "status_code", None)
        return isinstance(status, int) and status >= 500

    return False


# 네이버에 요청을 보내고, 일시적 오류면 전체 마감 안에서 몇 번 다시 시도하는 함수
def send_driving_request(headers, params):
    started = time.monotonic()
    attempt = 0

    while True:
        attempt += 1

        # 1. 남은 시간 안에서만 기다림 (한 번의 타임아웃은 REQUEST_TIMEOUT_SECONDS 까지)
        remaining = TOTAL_DEADLINE_SECONDS - (time.monotonic() - started)
        timeout = min(REQUEST_TIMEOUT_SECONDS, remaining)

        try:
            response = requests.get(DIRECTIONS_URL, headers=headers, params=params, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.RequestException as error:
            # 2. 일시적 오류가 아니거나, 재시도 횟수를 다 썼으면 그대로 실패
            if not is_retryable_error(error) or attempt > MAX_RETRIES:
                raise

            # 3. 기다린 뒤에도 남은 시간이 부족하면 대기 없이 실패
            elapsed = time.monotonic() - started
            if TOTAL_DEADLINE_SECONDS - (elapsed + RETRY_WAIT_SECONDS) < MIN_ATTEMPT_SECONDS:
                raise

            time.sleep(RETRY_WAIT_SECONDS)


# 네이버 Directions 5 API에 자동차 길찾기를 요청해서 거리와 시간을 가져오는 함수
def request_naver_driving(origin, destination):
    # 1. 좌표 확인 (좌표가 잘못되면 haversine_km에서 ValueError)
    haversine_km(origin, destination)

    # 2. 키 읽기 (값은 헤더에만 쓰고 URL, 에러 메시지, 반환값에는 넣지 않음)
    client_id = os.getenv("NAVER_MAPS_CLIENT_ID")
    client_secret = os.getenv("NAVER_MAPS_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise ValueError(
            ".env에 NAVER_MAPS_CLIENT_ID 또는 NAVER_MAPS_CLIENT_SECRET이 없어요."
        )

    # 3. 네이버 API 호출 (start, goal은 경도,위도 순서). 일시적 오류만 다시 시도함
    response = send_driving_request(
        headers={
            "x-ncp-apigw-api-key-id": client_id,
            "x-ncp-apigw-api-key": client_secret,
        },
        params={
            "start": f"{origin['longitude']},{origin['latitude']}",
            "goal": f"{destination['longitude']},{destination['latitude']}",
            "option": "traoptimal",
        },
    )

    # 4. 응답 확인 (code가 0이 아니면 길찾기 실패)
    try:
        data = response.json()
        code = data["code"]
        summary = data["route"]["traoptimal"][0]["summary"]
        distance_m = summary["distance"]
        duration_ms = summary["duration"]
    except (KeyError, IndexError, TypeError, ValueError):
        raise RuntimeError("네이버 길찾기 응답 형식이 올바르지 않아요.") from None

    if code != 0:
        raise RuntimeError("네이버 길찾기에 실패했어요.")

    for value in (distance_m, duration_ms):
        if isinstance(value, bool) or not isinstance(value, Real) or value < 0:
            raise RuntimeError("네이버 길찾기 응답 형식이 올바르지 않아요.")

    # 5. 미터는 km로, 밀리초는 분으로 바꿔서 반환
    return {
        "distance_km": round(distance_m / 1000, 1),
        "duration_min": round(duration_ms / 1000 / 60, 1),
        "mode": "car",
        "source": "네이버",
    }


# 이동 거리와 시간을 구하는 함수 (자동차는 네이버 API, 도보는 추정값)
def get_travel_time(origin, destination, mode="car", fallback_to_estimate=True):
    """
    이동 거리(km)와 이동시간(분)을 구하는 함수.

    car: 네이버 Directions 5 API로 실제 값을 가져온다. (source "네이버")
         일시적 오류(타임아웃, 연결 오류, HTTP 5xx)는 전체 마감 안에서 몇 번 다시 시도한다.
         그래도 실패하거나 키가 없으면
           fallback_to_estimate=True(기본값)이면 추정값으로 대체한다. (source "추정(API 실패)")
           fallback_to_estimate=False 이면 DrivingTimeError 를 낸다. (transient 로 일시적 오류인지 알 수 있음)
         가까운 도심 구간에서는 직선거리 추정이 실제보다 훨씬 짧게 나올 수 있어서,
         틀린 값을 보여 주고 싶지 않은 쪽(화면)은 False 로 부른다.
    walk: 네이버 Directions는 자동차 전용이라 호출하지 않고
          직선거리 기반 추정값을 돌려준다. (source "추정", fallback_to_estimate 와 상관없음)
    그 밖의 mode, 올바르지 않은 좌표는 ValueError.
    """
    # 1. 추정값 먼저 계산 (mode나 좌표가 잘못되면 여기서 ValueError)
    estimate = estimate_travel_time(origin, destination, mode)

    # 2. 도보는 API를 부르지 않고 추정값 그대로 반환
    if mode == "walk":
        return estimate

    # 3. 자동차는 네이버 API로 실제 값 가져오기
    try:
        return request_naver_driving(origin, destination)
    except (requests.RequestException, RuntimeError, ValueError) as error:
        # 4. 실패하면 옵션에 따라 추정값으로 대체하거나 오류를 냄 (예외 내용에 키가 들어갈 수 있어 담지 않음)
        if fallback_to_estimate:
            estimate["source"] = "추정(API 실패)"
            return estimate

        raise DrivingTimeError(is_retryable_error(error)) from None
