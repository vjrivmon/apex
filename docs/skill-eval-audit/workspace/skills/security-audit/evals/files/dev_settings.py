# settings/dev.py — local development configuration.
# Loaded only when APP_ENV == "dev" (see settings/__init__.py).
# The production config (settings/prod.py) overrides all of these.

DEBUG = True

# Wide-open CORS so the Vite dev server on a random port can hit the API.
# settings/prod.py sets CORS_ALLOWED_ORIGINS = ["https://app.example.com"].
CORS_ALLOWED_ORIGINS = ["*"]

DATABASE_URL = "sqlite:///./dev.db"

# Dummy secret; prod reads SECRET_KEY from the environment / secrets manager.
SECRET_KEY = "dev-only-not-secret"

LOG_LEVEL = "DEBUG"
