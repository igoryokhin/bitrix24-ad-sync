from authlib.integrations.flask_client import OAuth

oauth = OAuth()


def init_oauth(app):
    """Регистрирует Keycloak как OIDC-клиент, если заданы issuer/client_id.
    Возвращает True, если OIDC сконфигурирован и кнопка входа должна показываться."""
    if not (app.config.get("OIDC_ISSUER") and app.config.get("OIDC_CLIENT_ID")):
        return False
    oauth.init_app(app)
    oauth.register(
        name="keycloak",
        server_metadata_url=f"{app.config['OIDC_ISSUER']}/.well-known/openid-configuration",
        client_id=app.config["OIDC_CLIENT_ID"],
        client_secret=app.config["OIDC_CLIENT_SECRET"],
        client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"},
    )
    return True
