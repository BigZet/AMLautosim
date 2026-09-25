"""UI response policy, including framework-generated HTTP 404 pages."""

from starlette.responses import HTMLResponse

NOT_FOUND = '''<!doctype html><html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Страница не найдена — AML Практикум</title>
<main style="max-width:40rem;margin:12vh auto;padding:1rem;font:1.2rem sans-serif">
<h1>Страница не найдена</h1><p>Возможно, адрес изменился.</p>
<a href="/play">Вернуться к игре</a></main></html>'''


def install_security(app, *, secure: bool):
    @app.middleware('http')
    async def secure_response(request, call_next):
        response = await call_next(request)
        if response.status_code == 404:
            response = HTMLResponse(NOT_FOUND, status_code=404)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['X-Frame-Options'] = 'DENY'
        # NiceGUI currently needs inline/eval scripts; report-only until browser QA.
        response.headers['Content-Security-Policy-Report-Only'] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "font-src 'self' data:; connect-src 'self' ws: wss:; "
            "frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
        )
        if secure:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response
