# Shared UI

Общая интеграция двух Streamlit-приложений:

- `api_client.py` — typed вызовы `/api/v1`, timeout и request ID;
- `cookies.py` — route-scoped session cookie;
- `state.py` — rerun-safe `st.session_state`;
- `errors.py` — преобразование API error codes в сообщения UI.

Session ID передается в заголовке отдельного запроса и не хранится в общих headers.
