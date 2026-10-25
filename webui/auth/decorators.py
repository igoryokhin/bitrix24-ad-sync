from functools import wraps

from flask import session, request, redirect, url_for, jsonify


def require_admin(view):
    """Точечный декоратор для не-API HTML-роутов. Для /api/* авторизация
    проверяется централизованно в app.py (before_request), это отдельный
    путь на случай прямых серверных страниц вне /api/."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            if request.path.startswith("/api/"):
                return jsonify(error="unauthorized"), 401
            return redirect(url_for("auth.login_page", next=request.path))
        return view(*args, **kwargs)
    return wrapped
