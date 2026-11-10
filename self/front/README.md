# self/front — 화면 (더미 데이터)

사진 한 장 → 비슷한 장소 후보 카드 → 대화로 조건 입력 → 추천 결과.
검색 · 길찾기 · 챗봇 함수가 아직 없어서 **전부 가짜(예시) 데이터**로 돈다.

## 실행

```
cd self/front
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

브라우저에서 http://localhost:8501 이 열린다. (`streamlit` 명령을 못 찾는 PC가 있어서 `python -m` 으로 적었다.)

`self/front` 안에서 실행해야 `.streamlit/config.toml`(각진 모서리, 흰 바탕, 업로드 10MB 제한)이 적용된다.
`.env` 와 API 키는 필요 없다. 이 폴더의 코드는 키를 읽지 않는다.

## 파일

| 파일 | 하는 일 |
|---|---|
| `app.py` | 화면 3단계(사진 올리기 / 후보 보기 / 대화로 추천)와 화면 전환 |
| `ui.py` | 카드 · 대화 HTML 조각. 값이 빠진 데이터를 여기서 걸러 그린다 |
| `style.css` | 색 · 글꼴 · 선. 맨 위 변수만 바꾸면 전체에 적용된다 |
| `backend.py` | 화면이 부르는 함수 3개. **실제 함수가 생기면 여기 본문만 바꾼다** |
| `dummy_data.py` | 예시 후보 6곳, 예시 추천, 예시 출발지 |

## 화면이 받는 데이터

후보 1개 (`backend.search_places()` 가 돌려주는 list 의 원소):

| 키 | 없을 때 화면 |
|---|---|
| `place_id`, `name` | 필수 |
| `region` | "지역 정보 없음" |
| `similarity` (0~1) | 유사도 표시를 숨김 |
| `image_url` | 회색 칸 + "사진을 불러오지 못했어요" (주소가 있는데 안 열리면 단색 칸에 같은 문구) |
| `overview` | "소개글 준비 중". HTML 태그 · 줄바꿈은 걷어내고 한 줄로 자른다 |
| `latitude`, `longitude` | 지금 화면에서는 쓰지 않는다 |
| `distance_km`, `duration_min` | **둘 다 있을 때만** "차로 약 1시간 15분 · 62km" 줄을 보여 준다 |

추천 답 (`backend.recommend()`): `text`, `recommendations`(`place_id`, `reason`, 선택으로 `distance_km`, `duration_min`), `question`.
추천의 `place_id` 는 후보 목록 안에 있어야 그려진다.

## 지키는 것

- 사진은 `image_url` 원본 주소로만 보여 준다. 이 폴더에 사진 파일을 두지 않는다.
- 올린 사진은 메모리에만 있고 디스크에 저장하지 않는다.
- 예시 후보 6곳은 `shared/place_cards.csv` 의 실제 행이다 (출처: 한국관광공사 TourAPI, 공공누리 제1유형). 유사도 · 추천 이유 · 거리 · 시간은 지어낸 값이다.

## 실제 함수와 연결할 때 정할 것

1. `search_images()` 결과는 `score` / `filename` 이다 → `similarity` / `image_url` 로 맞추기
2. 검색 결과가 사진 단위다 → `place_id` 로 묶어 장소 단위로 (어느 쪽에서 묶을지)
3. `get_origin_coordinates()` 가 터미널 `input()` 을 쓴다 → 화면에서는 후보 목록만 받아야 한다
4. 카드로 보여 줄 후보 수 (지금 6)
