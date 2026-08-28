"""Canjea el ?code= de MercadoLibre por el refresh token. Corre en GitHub Actions.

Se usa una sola vez por autorización, desde el workflow «Autorizar MercadoLibre».
La alternativa (scripts/ml_oauth.py) hace lo mismo pero en tu computadora y te
pide copiar el token a mano; esta versión evita ese paso y, sobre todo, evita
que el token pase por el chat o por la pantalla.

El refresh token NUNCA se imprime: se escribe en el archivo que indica
ML_TOKEN_FILE y el workflow lo guarda como secret del repo.

Variables de entorno:
    ML_CLIENT_ID, ML_CLIENT_SECRET   de la app en el DevCenter de ML
    ML_CODE                          el code= de la redirección (o la URL entera)
    ML_REDIRECT_URI                  el mismo que está configurado en la app
    ML_TOKEN_FILE                    dónde dejar el refresh token
"""
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from src.config import Secrets  # noqa: E402

TOKEN = "https://api.mercadolibre.com/oauth/token"


def limpiar_code(entrada: str) -> str:
    """Acepta el code pelón o la URL completa de la redirección.

    Pegar la barra de direcciones entera es lo más natural del mundo, y el
    code de ML trae guiones y mayúsculas que invitan a recortarlo mal.
    """
    entrada = (entrada or "").strip().strip('"').strip("'")
    if "code=" in entrada:
        qs = parse_qs(urlparse(entrada).query if "://" in entrada else entrada)
        valores = qs.get("code") or []
        if valores:
            return valores[0].strip()
    return entrada


def main() -> int:
    cid = Secrets.ML_CLIENT_ID()
    sec = Secrets.ML_CLIENT_SECRET()
    code = limpiar_code(os.environ.get("ML_CODE", ""))
    redirect = (os.environ.get("ML_REDIRECT_URI") or "").strip()
    destino = (os.environ.get("ML_TOKEN_FILE") or "").strip()

    faltan = [n for n, v in (("ML_CLIENT_ID", cid), ("ML_CLIENT_SECRET", sec),
                             ("ML_CODE", code), ("ML_REDIRECT_URI", redirect),
                             ("ML_TOKEN_FILE", destino)) if not v]
    if faltan:
        print(f"❌ Falta: {', '.join(faltan)}")
        return 1

    print(f"Canjeando el code (largo {len(code)}) contra {redirect} …")
    r = requests.post(
        TOKEN,
        headers={"accept": "application/json",
                 "content-type": "application/x-www-form-urlencoded"},
        data={"grant_type": "authorization_code", "client_id": cid,
              "client_secret": sec, "code": code, "redirect_uri": redirect},
        timeout=30,
    )

    if r.status_code != 200:
        # El cuerpo del error de ML no trae credenciales, solo el motivo.
        print(f"❌ ML respondió {r.status_code}: {r.text[:400]}")
        print(
            "\nLas tres causas casi siempre son:\n"
            "  1. el code ya se usó o ya venció (dura pocos minutos) → vuelve a "
            "autorizar y córrelo de inmediato\n"
            "  2. el redirect_uri no es idéntico al de la app en el DevCenter\n"
            "  3. la app no tiene el scope offline_access activado"
        )
        return 1

    d = r.json()
    refresh = d.get("refresh_token")
    if not refresh:
        print("❌ ML no devolvió refresh_token. Casi seguro le falta el scope "
              "offline_access a la app: actívalo en el DevCenter y reautoriza.")
        return 1

    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::add-mask::{refresh}", flush=True)
    Path(destino).write_text(refresh, encoding="utf-8")

    print(f"✅ Autorizado. Refresh token obtenido ({len(refresh)} caracteres) "
          f"y listo para guardarse como secret.")
    print(f"   Usuario de ML autorizado: {d.get('user_id')}")
    print(f"   Access token de prueba vigente por {d.get('expires_in')} s.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
