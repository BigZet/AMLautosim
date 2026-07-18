import streamlit as st

st.title("Симулятор поведения клиента")

st.write(
    """
    Измените параметры поведения клиента.
    После отправки будет рассчитан условный AML-риск.
    """
)

with st.form("simulation_form"):
    transaction_amount = st.number_input(
        "Сумма перевода, ₽",
        min_value=0,
        max_value=1_000_000,
        value=50_000,
        step=5_000,
    )

    transaction_count = st.slider(
        "Количество переводов за день",
        min_value=1,
        max_value=50,
        value=5,
    )

    unique_recipients = st.slider(
        "Количество уникальных получателей",
        min_value=1,
        max_value=30,
        value=3,
    )

    account_age_days = st.number_input(
        "Возраст счёта, дней",
        min_value=0,
        max_value=5000,
        value=365,
    )

    has_salary = st.checkbox(
        "На счёт поступает зарплата",
        value=True,
    )

    cash_withdrawal = st.checkbox(
        "Есть снятие наличных после перевода",
        value=False,
    )

    night_activity = st.checkbox(
        "Операции выполняются ночью",
        value=False,
    )

    submitted = st.form_submit_button(
        "Проверить сценарий",
        type="primary",
    )

if submitted:
    risk_score = 0.0

    if transaction_amount > 100_000:
        risk_score += 0.20

    if transaction_amount > 500_000:
        risk_score += 0.20

    if transaction_count > 10:
        risk_score += 0.15

    if unique_recipients > 7:
        risk_score += 0.15

    if account_age_days < 30:
        risk_score += 0.15

    if not has_salary:
        risk_score += 0.05

    if cash_withdrawal:
        risk_score += 0.20

    if night_activity:
        risk_score += 0.10

    risk_score = min(risk_score, 1.0)
    risk_percent = round(risk_score * 100)

    st.divider()
    st.subheader("Результат")

    st.progress(risk_score)
    st.metric("AML-риск", f"{risk_percent}%")

    if risk_score >= 0.7:
        st.error("Высокий риск: сценарий будет направлен на проверку.")
    elif risk_score >= 0.4:
        st.warning("Средний риск: требуется дополнительный анализ.")
    else:
        st.success("Низкий риск: сценарий не вызвал срабатывание.")

    with st.expander("Показать параметры сценария"):
        st.json(
            {
                "transaction_amount": transaction_amount,
                "transaction_count": transaction_count,
                "unique_recipients": unique_recipients,
                "account_age_days": account_age_days,
                "has_salary": has_salary,
                "cash_withdrawal": cash_withdrawal,
                "night_activity": night_activity,
                "risk_score": risk_score,
            }
        )