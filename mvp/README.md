# Streamlit MVP

Автономный UI-прототип AML-симулятора. В папке находятся два независимых Streamlit-интерфейса и вся необходимая им in-memory игровая логика. FastAPI, база данных и внешние сервисы не используются.

## Запуск

```powershell
cd mvp
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Интерфейс участника:

```powershell
.\.venv\Scripts\python.exe -m streamlit run participant_app.py --server.port 8502
```

Панель организатора:

```powershell
.\.venv\Scripts\python.exe -m streamlit run admin_app.py --server.port 8503
```

Данные хранятся только в памяти процесса или текущей Streamlit-сессии и сбрасываются после перезапуска.