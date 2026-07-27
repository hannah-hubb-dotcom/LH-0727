import streamlit as st
import pandas as pd
import plotly.express as px
import kagglehub
import os

# Streamlit 앱 제목
st.title('COVID-19 시계열 데이터 시각화')

# 데이터 로드 (KaggleHub에서 직접 데이터셋 다운로드)
@st.cache_data
def load_data():
    path = kagglehub.dataset_download('imdevskp/corona-virus-report')
    file_name = 'covid_19_clean_complete.csv'
    full_file_path = os.path.join(path, file_name)
    df = pd.read_csv(full_file_path, parse_dates=['Date'])
    
    # 'Active' 케이스 계산
    df['Active'] = df['Confirmed'] - df['Deaths'] - df['Recovered']
    
    # 필요한 열만 선택
    df_cleaned = df[['Date', 'Country/Region', 'Confirmed', 'Deaths', 'Recovered', 'Active']]
    
    # 국가별, 날짜별로 집계 (중복 데이터 처리 및 NaN 값 처리)
    df_agg = df_cleaned.groupby(['Date', 'Country/Region']).sum().reset_index()
    
    return df_agg

df_covid = load_data()

# 국가 선택 사이드바
countries = ['Global'] + sorted(df_covid['Country/Region'].unique().tolist())
selected_country = st.sidebar.selectbox('국가를 선택하세요:', countries)

if selected_country == 'Global':
    # 전 세계 데이터 집계
    df_plot = df_covid.groupby('Date')[['Confirmed', 'Deaths', 'Recovered', 'Active']].sum().reset_index()
    title_text = '전 세계 COVID-19 케이스 추이'
else:
    # 선택된 국가 데이터 필터링
    df_plot = df_covid[df_covid['Country/Region'] == selected_country]
    title_text = f'{selected_country} COVID-19 케이스 추이'

# 시계열 그래프 생성
fig = px.line(
    df_plot,
    x='Date',
    y=['Confirmed', 'Deaths', 'Recovered', 'Active'],
    title=title_text,
    labels={
        'Date': '날짜',
        'value': '환자 수',
        'variable': '케이스 유형'
    },
    hover_data={
        'Date': '|%Y-%m-%d',
        'value': ':,',
        'variable': False
    }
)

fig.update_layout(hovermode='x unified')
st.plotly_chart(fig, use_container_width=True)
