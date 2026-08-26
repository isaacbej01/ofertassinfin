"""Carga de configuración y secretos."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "config.yaml"
DATA_DIR = ROOT / "data"
MEDIA_DIR = ROOT / "docs" / "media"      # servido por GitHub Pages
QUEUE_DIR = DATA_DIR / "queue"


@lru_cache(maxsize=1)
def cfg() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get(path: str, default=None):
    """cfg('filtros.descuento_minimo_pct') -> 25"""
    node = cfg()
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


# --------------------------------------------------------------------------
# Secretos. En local vienen de .env; en GitHub Actions de repository secrets.
# --------------------------------------------------------------------------
def _load_dotenv():
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


def secret(name: str, required: bool = False, default: str = "") -> str:
    val = os.environ.get(name, default)
    if required and not val:
        raise RuntimeError(
            f"Falta el secreto {name}. Defínelo en .env (local) o en "
            f"GitHub → Settings → Secrets and variables → Actions."
        )
    return val


class Secrets:
    # --- MercadoLibre ---
    ML_CLIENT_ID = lambda: secret("ML_CLIENT_ID")
    ML_CLIENT_SECRET = lambda: secret("ML_CLIENT_SECRET")
    ML_REFRESH_TOKEN = lambda: secret("ML_REFRESH_TOKEN")
    ML_AFFILIATE_TAG = lambda: secret("ML_AFFILIATE_TAG")     # matt_tool / matt_word
    ML_SESSION_COOKIE = lambda: secret("ML_SESSION_COOKIE")   # opcional, endpoint interno

    # --- Amazon ---
    AMZ_PARTNER_TAG = lambda: secret("AMZ_PARTNER_TAG")
    AMZ_CREDENTIAL_ID = lambda: secret("AMZ_CREDENTIAL_ID")
    AMZ_CREDENTIAL_SECRET = lambda: secret("AMZ_CREDENTIAL_SECRET")

    # --- Buffer ---
    BUFFER_ACCESS_TOKEN = lambda: secret("BUFFER_ACCESS_TOKEN")
    BUFFER_CHANNEL_IG = lambda: secret("BUFFER_CHANNEL_IG")
    BUFFER_CHANNEL_TIKTOK = lambda: secret("BUFFER_CHANNEL_TIKTOK")

    # --- Hosting de imágenes ---
    MEDIA_BASE_URL = lambda: secret("MEDIA_BASE_URL")  # ej. https://usuario.github.io/ofertas-sin-fin/media
