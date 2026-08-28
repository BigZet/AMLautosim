# Deployment assets

На старте здесь достаточно нескольких файлов:

- `compose.yml` — все сервисы production;
- `compose.dev.yml` — локальные overrides;
- `Caddyfile` — HTTPS, `/play`, `/admin` и WebSocket routes.

Подкаталоги для monitoring или окружений стоит добавлять только при появлении реальных
файлов. Секреты, дампы и runtime data сюда не коммитятся.
