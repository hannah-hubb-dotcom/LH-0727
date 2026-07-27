import streamlit as st

st.title('두 숫자 더하기 앱')

st.write("두 개의 숫자를 입력하면 합계를 계산해 드립니다.")

# 숫자 입력 받기
number1 = st.number_input('첫 번째 숫자', value=0.0)
number2 = st.number_input('두 번째 숫자', value=0.0)

# 숫자 더하기
sum_numbers = number1 + number2

# 결과 표시
st.write(f"두 숫자의 합계는: {sum_numbers}")
