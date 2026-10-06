# data/ — TourAPI 수집 (1번 담당)

> **데이터 출처: 한국관광공사 TourAPI (공공누리 제1유형)**
> 공공누리 **제1유형(출처표시)** 장소·사진만 사용한다. 제3유형(변경 금지)과 유형이 비어 있는 장소는 팀이 해석을 정할 때까지 **보류(제외)** 중이다.

이 폴더는 한국관광공사 TourAPI에서 **자연 관광지**(전국)의 장소 정보와 사진 주소를 모아 팀 공용 장소 카드 `shared/place_cards.csv`를 만든다.
**사진 파일 다운로드는 `search/` 담당(2번)이 `shared/place_cards.csv`의 `image_urls` 주소로 직접 한다.** (이 폴더에는 다운로드 스크립트가 없다)

## 실행 순서
모든 명령은 **저장소 맨 위 폴더(`data/`의 바로 위)** 에서 실행한다. 스크립트가 `data/`의 상위 폴더를 기준으로 경로를 잡기 때문이다.

1. **`.env` 준비** — 저장소 맨 위 폴더에 `.env` 파일을 만들고 한 줄을 넣는다. (`.env`는 git에 올리지 않는다. 키 값은 공유·출력하지 않는다.)
   ```
   TOURAPI_KEY=공공데이터포털에서_발급받은_인증키
   ```
2. **필요 패키지** — 코드가 쓰는 것은 `pandas`, `requests`. (`requirements.txt`가 아직 저장소에 없다 → **확인 필요**)
3. **장소 목록 수집** — `collect_tour_api.py`
   ```
   python data/collect_tour_api.py --plan   # 1페이지만 호출해 총 건수·예상 호출 수를 보고 종료
   python data/collect_tour_api.py          # 전체 수집 → data/outputs/place_cards_all.csv
   ```
4. **장소별 사진 주소·소개글 수집** — `collect_details.py` (아래 설명). 하루 호출 상한 때문에 며칠에 걸쳐 같은 명령을 반복해서 실행한다.
   ```
   python data/collect_details.py
   ```

`collect_details.py`는 3번이 만든 `data/outputs/place_cards_all.csv`와 `data/outputs/sample_order.csv`가 있어야 시작한다. 또 `shared/` 폴더가 이미 있어야 한다(코드가 이 폴더를 만들지 않는다).

## collect_tour_api.py — 장소 목록 수집
- API: `areaBasedList2` (`https://apis.data.go.kr/B551011/KorService2/areaBasedList2`), 한 번에 `numOfRows=1000`
- 조건: 관광지(`contentTypeId=12`) + 자연(`lclsSystm1=NA`, 기본값. 공식 분류 코드표로 자연관광임을 확인) + `arrange=Q`(수정일순)
  - `arrange=Q`는 대표 이미지가 있는 장소를 우선 정렬할 뿐 **걸러내지 않는다.** 실제로 자연 3,797곳 중 339곳은 대표 이미지가 없었다. (코드 안 설명 문구의 "대표이미지 있는 장소"는 정확하지 않다)
- 라이선스(`cpyrhtDivCd`) 장소 단위 분포: Type1 1,620 / Type3 1,838 / 빈칸 339. **Type1만** 저장 → 1,620곳. (대표 이미지가 없는 339곳은 라이선스도 빈칸이라 함께 빠진다)
- 옵션: `--plan`(호출 계획만 보기), `--rows`(한 번에 받을 건수, 기본 1000), `--lcls1`(분류 대분류 코드, 기본 `NA`). `--target`은 코드에 정의돼 있지만 쓰이지 않는다.
- 응답 원본은 `data/outputs/raw/`에 캐시한다. 캐시가 있으면 다시 실행해도 API를 호출하지 않는다. 호출 기록은 `data/outputs/api_call_log.csv`.
- `shared/place_cards.csv`는 **이 스크립트가 쓰지 않는다.** (`place_cards_all.csv`와 `sample_order.csv`, `collect_stats.json`만 만든다)
- `sample_order.csv`는 1,620곳을 `random_state=0`으로 섞은 순서이고, 파일이 없을 때만 새로 만든다. 지금은 수집 순서를 정하는 용도다.

## collect_details.py — 장소별 사진 주소와 소개글 수집
**하는 일**
- 장소마다 **사진 주소**를 `detailImage2`로, **소개글**을 `detailCommon2`로 가져온다. 두 API 모두 한 번에 장소 1개만 조회할 수 있어서 장소 수만큼 호출한다. (예: 1,620곳이면 사진 1,620회 + 소개글 1,620회 이상)
- `image_urls`는 JSON 배열 문자열이다. 맨 앞은 **대표 이미지**(목록 수집 때 받은 `firstimage`), 이어서 `detailImage2`의 추가 이미지 중 **이미지별 라이선스가 Type1인 것만** 붙인다. 완전히 같은 URL만 중복을 제거하고 URL은 바꾸지 않는다. Type3 이미지와 라이선스가 빈 이미지는 넣지 않는다.
- `overview`는 응답 텍스트를 **그대로** 넣는다(손대지 않음). 아직 받지 않은 장소는 빈칸이다.
- 사진 주소는 **전 장소 조회가 끝난 뒤에야** 소개글 수집을 시작한다. 한 번 실행 안에서 "사진 → 소개글" 순서로 진행한다.
- 사진이 하나도 없는 장소는 장소 카드에 넣지 않고 `data/outputs/excluded_no_image.csv`에 기록한다.

**호출 한도와 자동 중단**
- 하루 호출 상한은 **950회**(개발계정 한도 일 1,000건에서 여유를 둠). 로컬 호출 기록(`data/outputs/api_call_log.csv` + `api_call_log_detail.csv`)에서 **오늘 날짜** 줄 수를 세어 지킨다. **시간 초과·재시도도 호출 1회로 센다.**
- 요청 간격은 최소 0.2초, 오류는 장소당 2번까지 재시도한다.
- 아래 경우 **자동으로 멈추고**, 그때까지의 진행분은 저장한 뒤 종료한다.
  - 오늘 호출이 950회에 도달
  - 서버가 한도 초과를 응답(HTTP 429, 또는 응답에 `LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS` / 오류코드 `22`) → 시각과 응답 일부를 `data/outputs/rate_limit_events.csv`에 기록
  - 장소가 **연속 10번** 실패
- 서버의 한도 초기화 시각은 공식 매뉴얼에 없다(**확인 필요**). 로컬 카운터는 날짜가 바뀌면 0으로 시작한다.
- 오류로 실패한 장소는 `data/outputs/failed_places.csv`에 기록한다(실행할 때마다 그 실행의 실패만 새로 쓴다). 다음 실행에서 다시 시도한다.

**이어서 실행**
- 장소별 응답을 `data/outputs/raw/detailImage2/`, `raw/detailCommon2/`에 저장하고(요청 주소와 키는 저장하지 않음), 이미 받은 장소는 다시 호출하지 않는다. 그래서 **중간에 멈춰도, 다음 날도 같은 명령으로 이어받는다.**
- 진행분은 실행이 끝날 때 `data/outputs/place_cards_progress.csv`에 저장된다. (실행 중에는 갱신되지 않으니 진행 상황은 `--status`로 본다)

**`shared/place_cards.csv` 교체**
- 수집 중에는 `shared/place_cards.csv`를 건드리지 않는다.
- **사진 주소 조회가 전 장소에서 끝나면, 그 실행이 끝날 때 `shared/place_cards.csv`를 한 번만 자동으로 교체한다.** (교체 기록은 `data/outputs/.shared_published`에 남고, 이 파일이 있으면 자동 교체는 다시 일어나지 않는다) 교체 직전 기존 `shared/place_cards.csv`는 `data/outputs/place_cards_sample1000.csv`로 백업한다(백업이 이미 있으면 덮어쓰지 않는다).
- 자동 교체 시점에 **소개글은 그때까지 받은 곳만 채워져 있다.** 소개글이 더 모인 뒤 반영하려면 `--publish`로 직접 교체해야 한다.

**옵션 (코드에 있는 것만)**
| 옵션 | 설명 |
|---|---|
| (없음) | 사진 주소 → 소개글 순서로 수집(상한·중단 조건까지) |
| `--test N` | 무작위(seed 고정) N곳으로 시험. 사진 N회 + 소개글 최대 5회를 호출하고 장소당 사진 수·이미지 라이선스·소개글 상태를 출력. (사진 주소 접근 확인은 HEAD 요청이라 서버가 거절(405)할 수 있다) |
| `--status` | 진행 현황 출력(사진 주소 N곳, 소개글 N곳, 오늘 호출 수) |
| `--publish` | 진행분을 `shared/place_cards.csv`로 **수동 교체**. 기존 검색 인덱스(`search/outputs/index_map.csv`)가 있고 그 장소가 진행분에 빠져 있으면 중단 |
| `--allow-missing` | `--publish`와 함께 써서 위 경고를 무시하고 교체 |
| `--images-only` | 사진 주소만 수집하고 소개글은 시작하지 않음 |

주의: `collect_details.py`는 시작할 때 `.env`를 읽으므로 `--status`도 `.env`가 없으면 실행되지 않는다. `collect_tour_api.py`는 `api_call_log.csv`만 세고 `collect_details.py`는 두 기록을 합쳐 세므로, 같은 날 두 스크립트를 모두 돌릴 때는 하루 합계(한도 1,000건)에 주의한다.

## 생성되는 파일 (`data/outputs/`)
| 파일 | 설명 |
|---|---|
| `place_cards_all.csv` | Type1 장소 전체(대표 이미지 1장만) — `collect_tour_api.py` |
| `sample_order.csv`, `collect_stats.json`, `raw/NA_rows...json` | 수집 순서, 수집 통계, 목록 API 응답 캐시 |
| `raw/detailImage2/`, `raw/detailCommon2/` | 장소별 응답 원본 — `collect_details.py` |
| `place_cards_progress.csv`, `excluded_no_image.csv`, `failed_places.csv` | 진행분, 사진 없는 장소, 실패 장소 |
| `api_call_log.csv`, `api_call_log_detail.csv`, `rate_limit_events.csv` | 호출 기록, 한도 초과 기록 |
| `place_cards_sample1000.csv`, `.shared_published` | 자동 교체 전 shared 백업, 교체 기록 |

`data/outputs/`는 자동 생성되는 작업 파일이라 git에 올리지 않는다. 현재 저장소의 `.gitignore`에는 이 경로가 **없다**(**확인 필요** — 각자 환경에서 제외하거나 `.gitignore`에 추가).

## shared/place_cards.csv 읽을 때 주의
```python
import json, pandas as pd
df = pd.read_csv("shared/place_cards.csv", dtype=str, keep_default_na=False)
urls = json.loads(df.loc[0, "image_urls"])   # ["https://...", ...]
```
- **`keep_default_na=False` 필수**: 분류 코드 `lcls1`의 `NA`(자연관광)가 기본 설정에서는 빈 값(NaN)으로 바뀐다. `dtype=str`도 같이 써서 `place_id`가 숫자로 바뀌지 않게 한다.
- **`overview`에는 줄바꿈이 들어 있다**(HTML 태그가 섞인 소개글도 있다. 응답을 수정하지 않고 그대로 저장했기 때문). 따라서 `wc -l`이나 줄 단위로 읽으면 행 수가 틀린다. 따옴표 안의 줄바꿈을 처리하는 **pandas `read_csv`(또는 파이썬 `csv` 모듈)로 읽는다.**
- `image_urls`는 한 칸 안의 JSON 배열 문자열이라 `json.loads`로 읽는다.
- `region`은 `addr1`의 앞 두 단어로 만든 파생값이다(행정구역 코드가 아님). `lcls1~3`, `addr1`은 팀 합의 컬럼(`place_id`~`image_caption`) 뒤에 붙인 추가 컬럼이다. `image_caption`은 아직 비어 있다.

## 현황 (2026-10-06 기준, 계속 바뀜)
- 장소 카드 1,620곳, 사진 주소 수집 완료(장소당 평균 7.74장, 총 12,545장), 소개글은 일부만 채워짐(자동 교체 시점 244곳)
- 소개글이 더 채워지면 `python data/collect_details.py`로 이어서 받고, 필요할 때 `python data/collect_details.py --publish`로 shared에 반영한다.
