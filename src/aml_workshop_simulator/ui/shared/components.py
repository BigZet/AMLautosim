from __future__ import annotations

import streamlit as st
from typing import Any


def render_resource_bar(
        resources: dict[str, Any], initial_resources: dict[str, Any] | None = None) -> None:
    res = resources.get(
        "resources_after",
        {}) if "resources_after" in resources else resources

    col1, col2, col3, col4, col5 = st.columns(5)

    balance_val = float(res.get("balance", 0.0))
    energy_val = int(res.get("energy", 0))
    time_val = int(res.get("time", 0))
    trust_val = int(res.get("trust", 0))
    slots_val = int(res.get("slots", 0))

    with col1:
        st.metric("Баланс", f"{balance_val:,.0f} ₽", delta=None)
    with col2:
        st.metric("Энергия", f"{energy_val} ед.")
    with col3:
        st.metric("Время", f"{time_val} ч.")
    with col4:
        st.metric("Доверие", f"{trust_val} %")
    with col5:
        st.metric("Слотов свободно", f"{slots_val}")


def render_limits_and_objectives(resources: dict[str, Any]) -> None:
    totals = resources.get("totals", {})
    obj = resources.get("objective", {})
    target = float(obj.get("target_outflow", 150_000))
    outflow = float(totals.get("gross_outflow", 0.0))

    progress = min(1.0, max(0.0, outflow / max(1.0, target)))

    st.markdown("#### Цель раунда: Расходные операции")
    st.progress(
        progress,
        text=f"Проведено: {
            outflow:,.0f} ₽ из {
            target:,.0f} ₽ ({
                progress *
            100:.0f}%)")

    if resources.get("limits"):
        st.markdown("#### Лимиты раунда")
        for lim in resources["limits"]:
            used = lim["used"]
            limit = lim["limit"]
            p = min(1.0, max(0.0, used / max(1.0, limit)))
            st.caption(f"{lim['label']}: {used:,.0f} / {limit:,.0f} ₽")
            st.progress(p)


def render_violations_box(violations: list[str]) -> None:
    if violations:
        st.error("**Обнаружены нарушения правил раунда:**")
        for v in violations:
            st.markdown(f"- {v}")
    else:
        st.success("Цепочка соответствует правилам и ограничениям раунда!")


def render_catboost_features_inspector(
        catboost_features: dict[str, Any]) -> None:
    st.markdown("### 🤖 Вектор признаков для модели CatBoost")
    st.info(
        "Ниже представлены извлеченные структурированные признаки сценария, которые подаются на вход "
        "модели машинного обучения `CatBoostClassifier / CatBoostRegressor` для предсказания риска.")

    cols = st.columns(3)
    items = list(catboost_features.items())
    chunk_size = (len(items) + 2) // 3

    for i, col in enumerate(cols):
        with col:
            chunk = items[i * chunk_size: (i + 1) * chunk_size]
            for key, val in chunk:
                st.markdown(f"**`{key}`**: `{val}`")
