# data/ — 수집·다운로드 (1번)

## 실행 순서 (프로젝트 루트에서, `.env`에 `TOURAPI_KEY=...` 필요)
```
source .venv/bin/activate
python data/collect_tour_api.py --plan   # 1회 호출로 총 건수·예상 호출 수 확인
python data/collect_tour_api.py          # data/outputs/place_cards_all.csv 생성 (shared는 건드리지 않음)
python data/02_download.py --limit 1000  # 사진 → data/images/{place_id}.확장자
```
`data/01_inspect_excel.py`는 샘플 엑셀용이었고 현재 쓰지 않는다.

## 수집 조건
- API: TourAPI 국문 `areaBasedList2` (`https://apis.data.go.kr/B551011/KorService2/areaBasedList2`), 한 번에 1,000건(`numOfRows=1000`), 호출 4회
- 관광지(`contentTypeId=12`) + 자연(`lclsSystm1=NA`, 연계 정의서로 확인) + `arrange=Q`(수정일순, 대표 이미지 우선 정렬 — **대표 이미지 없는 장소도 걸러지지 않고 같이 온다**: 자연 3,797곳 중 339곳은 `firstimage`가 빈칸이고 장소 라이선스도 빈칸)
- 자연(NA) 관광지 총 3,797곳(장소 단위 라이선스: Type1 1,620 / Type3 1,838 / 빈칸 339) → **Type1만** 1,620곳 사용 (Type3 변경금지 1,838곳, 빈칸 339곳 제외)
- **무작위 표본**: 1,620곳을 `random_state=0`으로 섞은 순서(`data/outputs/sample_order.csv`)의 앞 1,000곳 → `shared/place_cards.csv`. 앞 300곳 ⊂ 앞 1,000곳
- 1,620곳 전체는 `data/outputs/place_cards_all.csv`(shared와 같은 컬럼), 소개글(`overview`)은 호출하지 않았다
- `region` = `addr1` 앞 두 단어로 만든 파생값(예: "인천광역시 남동구"). 행정구역 코드가 아니다
- API 응답 원본 캐시: `data/outputs/raw/` (캐시가 있으면 재실행해도 API를 호출하지 않는다), 호출 기록: `data/outputs/api_call_log.csv` (개발계정 하루 1,000건)

## 다운로드
- 워커 4개, 요청 간격 0.2초, 타임아웃 10초, 재시도 2회. 이미 받은 파일은 건너뜀. 실패는 `data/outputs/failed_urls.csv`
- 1,000장 실측: 실패 0, 평균 약 151KB, 합계 약 150MB. 서버 허용 속도는 미확인
- 사진은 분석용이며 git에 올리지 않고 재배포하지 않는다

## 장소별 사진 주소·소개글 수집 (`data/collect_details.py`) — 현황 (2026-10-05)
- **사진 주소 945/1,620곳 완료, 소개글 5/1,620곳 완료**, 사진이 없어 제외된 장소 0곳(`excluded_no_image.csv`), 실패 0곳(`failed_places.csv`)
- 진행분은 `data/outputs/place_cards_progress.csv`에 저장된다(945곳, 장소당 사진 평균 7.8장, 총 7,341장). **`shared/place_cards.csv`는 아직 기존 1,000곳(대표 이미지 1장)이다.** 사진 주소 조회가 1,620곳 전부 끝나면 한 번만 자동 교체(교체 전 기존 파일은 `data/outputs/place_cards_sample1000.csv`로 백업), 중간에 올리려면 `--publish`
- API: 사진 `detailImage2`, 소개글 `detailCommon2` (둘 다 장소 1개씩만 조회 가능). 이미지별 라이선스(`cpyrhtDivCd`)가 응답에 있어 **Type1 이미지만** 넣고 Type3(변경 금지)는 제외(현재 563장 제외). `image_urls` 맨 앞은 대표 이미지, 이어서 추가 이미지, 완전히 같은 URL만 중복 제거(URL은 변형 없음). 소개글은 응답 그대로
- 하루 호출 상한 950회(개발계정 한도 일 1,000건, 로컬 카운터 `data/outputs/api_call_log*.csv`). 서버 한도 초과 응답이 오면 즉시 중단하고 시각을 `data/outputs/rate_limit_events.csv`에 기록한다. **서버의 초기화 시각은 매뉴얼에 없음(미확인)**
- 장소별 응답 원본은 `data/outputs/raw/detailImage2/`, `raw/detailCommon2/`(요청 주소·키는 저장하지 않음). 이미 받은 장소는 다시 호출하지 않아서 **같은 명령으로 다음 날 이어받는다**

```
python data/collect_details.py            # 이어서 수집 (사진 주소 → 소개글, 하루 950회까지)
python data/collect_details.py --status   # 진행 현황
python data/collect_details.py --publish  # 진행분을 shared로 수동 교체 (기존 인덱스 장소가 빠지면 중단, 강제는 --allow-missing)
```
남은 호출: 사진 675곳 + 소개글 1,615곳 = 약 2,290회 → 하루 950회 기준 **3일** (사진은 2일차에 끝남)
