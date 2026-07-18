import pandas as pd
import streamlit as st

st.title("Статистика симуляций")

data = pd.DataFrame(
    {
        "Игрок": [
            "Игрок 1",
            "Игрок 2",
            "Игрок 3",
            "Игрок 4",
            "Игрок 5",
        ],
        "Сумма перевода": [
            50_000,
            150_000,
            700_000,
            30_000,
            250_000,
        ],
        "AML-риск": [
            20,
            45,
            90,
            10,
            65,
        ],
        "Результат": [
            "Пройдено",
            "Проверка",
            "Блокировка",
            "Пройдено",
            "Проверка",
        ],
    }
)

col1, col2, col3 = st.columns(3)

with col1:
    st.metric(
        "Всего симуляций",
        len(data),
    )

with col2:
    st.metric(
        "Средний риск",
        f"{data['AML-риск'].mean():.1f}%",
    )

with col3:
    blocked_count = (data["Результат"] == "Блокировка").sum()
    st.metric(
        "Заблокировано",
        blocked_count,
    )

st.divider()

st.subheader("Таблица результатов")

st.dataframe(
    data,
    use_container_width=True,
    hide_index=True,
)

st.subheader("Распределение AML-риска")

chart_data = data.set_index("Игрок")[["AML-риск"]]
st.bar_chart(chart_data)

st.subheader("Фильтрация")

minimum_risk = st.slider(
    "Минимальный риск",
    min_value=0,
    max_value=100,
    value=40,
)

filtered_data = data[data["AML-риск"] >= minimum_risk]

st.dataframe(
    filtered_data,
    use_container_width=True,
    hide_index=True,
)