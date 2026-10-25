from . import me, dashboard, users, sync, settings, audit


def register_api(app):
    app.register_blueprint(me.bp)
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(users.bp)
    app.register_blueprint(sync.bp)
    app.register_blueprint(settings.bp)
    app.register_blueprint(audit.bp)
