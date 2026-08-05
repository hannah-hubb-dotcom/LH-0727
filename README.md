# 서울 행정동별 출동건수 지도

Streamlit과 Plotly를 이용해 행정동별 출동건수를 흰색-빨간색 단계구분도로 표시합니다.

## 실행 방법

```bash
pip install -r requirements.txt
streamlit run app.py
```

`dong_emergency_count.geojson` 파일은 `app.py`와 같은 폴더에 있어야 합니다.

## Streamlit Community Cloud 배포

1. 이 폴더의 `app.py`, `requirements.txt`, `dong_emergency_count.geojson`을 GitHub 저장소에 올립니다.
2. Streamlit Community Cloud에서 저장소와 브랜치를 선택합니다.
3. Main file path에 `app.py`를 입력하고 배포합니다.
