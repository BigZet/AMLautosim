import streamlit as st

st.title("AML Simulator")
st.subheader("Симулятор поведения банковского клиента")

st.write(
    """
    Задача игрока — выполнить заданную финансовую операцию,
    не превысив порог срабатывания AML-модели.
    """
)

col1, col2, col3 = st.columns(3)

with col1:
    st.metric(
        label="Участников",
        value="600",
    )

with col2:
    st.metric(
        label="Доступных действий",
        value="8",
    )

with col3:
    st.metric(
        label="Порог модели",
        value="70%",
    )

st.divider()

st.markdown(
    """
    ### Как играть

    1. Откройте страницу **«Симулятор»**.
    2. Настройте поведение клиента.
    3. Отправьте сценарий на проверку.
    4. Посмотрите оценку AML-модели.
    """
)

if st.button("Начать игру", type="primary"):
    st.switch_page("pages/simulator_page.py")