"""Autorización inicial de MercadoLibre. Se corre UNA sola vez, a mano.

Por qué existe: la API de ML solo soporta los grant types authorization_code
y refresh_token. No hay client_credentials, o sea que no hay modo
servidor-a-servidor puro: alguien tiene que autorizar la app con una cuenta
real. Después de eso el sistema vive del refresh token (6 meses).

Uso:
    export ML_CLIENT_ID=... ML_CLIENT_SECRET=...
    python scripts/ml_oauth.py
    # abre la URL, autoriza, y pega aquí el ?code= de la redirección
"""
import sys
from pathlib import Path
from urllib.parse import urlencode

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import Secrets  # noqa: E402

AUTH = "https://auth.mercadolibre.com.mx/authorization"
TOKEN = "https://api.mercadolibre.com/oauth/token"


def main():
    cid = Secrets.ML_CLIENT_ID()
    sec = Secrets.ML_CLIENT_SECRET()
    if not (cid and sec):
        print("Falta ML_CLIENT_ID / ML_CLIENT_SECRET.\n"
              "Crea la app en https://developers.mercadolibre.com.mx/devcenter\n"
              "El redirect URI DEBE ser https (puedes usar https://localhost:8443/cb).")
        return 1

    redirect = input("Redirect URI configurado en la app: ").strip()
    url = f"{AUTH}?" + urlencode({
        "response_type": "code", "client_id": cid, "redirect_uri": redirect,
    })
    print("\n1) Abre esta URL en el navegador, con la cuenta de ML que usarás "
          "para afiliados:\n")
    print(url)
    print("\n2) Autoriza. Te va a redirigir a tu redirect URI con ?code=XXXX")
    code = input("\n3) Pega aquí el valor de code: ").strip()

    r = requests.post(TOKEN, data={
        "grant_type": "authorization_code",
        "client_id": cid, "client_secret": sec,
        "code": code, "redirect_uri": redirect,
    }, timeout=30)

    if r.status_code != 200:
        print(f"\n❌ ML respondió {r.status_code}:\n{r.text}")
        return 1

    d = r.json()
    print("\n✅ Listo. Guarda estos valores:\n")
    print(f"ML_REFRESH_TOKEN={d['refresh_token']}")
    print(f"\n(access token de prueba, expira en {d.get('expires_in')}s: "
          f"{d['access_token'][:24]}...)")
    print("\nGuárdalo en .env y como secret del repo en GitHub:\n"
          "  Settings → Secrets and variables → Actions → New repository secret")
    return 0


if __name__ == "__main__":
    sys.exit(main())
