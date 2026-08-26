"""Diagnóstico: prueba cada pieza del sistema por separado y dice qué falta.

    python scripts/doctor.py

Córrelo cada vez que algo deje de funcionar. La causa casi siempre es una
de estas cuatro: token de ML expirado, acceso a Creators API revocado por
30 días sin ventas, key de Buffer vencida, o URLs de imágenes caídas.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from src.config import Secrets, get  # noqa: E402

OK, WARN, FAIL = "✅", "⚠️ ", "❌"
resultados = []


def check(nombre, fn):
    try:
        estado, detalle = fn()
    except Exception as e:                       # noqa: BLE001
        estado, detalle = FAIL, f"excepción: {e}"
    resultados.append((estado, nombre, detalle))
    print(f"{estado} {nombre}: {detalle}")


# ---------------------------------------------------------------- secretos
def c_secretos():
    faltan = [n for n in ("ML_CLIENT_ID", "ML_CLIENT_SECRET", "ML_REFRESH_TOKEN",
                          "ML_AFFILIATE_TAG", "BUFFER_ACCESS_TOKEN",
                          "MEDIA_BASE_URL")
              if not getattr(Secrets, n)()]
    if not faltan:
        return OK, "todos los secretos base están definidos"
    return WARN, f"faltan: {', '.join(faltan)}"


# --------------------------------------------------------------- fuentes
def c_ml_token():
    from src.sources.mercadolibre import MLAuth
    t = MLAuth().token()
    return OK, f"access token obtenido (…{t[-6:]})"


def c_ml_search():
    from src.sources.mercadolibre import MercadoLibre
    res = MercadoLibre().search(q="audifonos bluetooth", limit=5)
    if not res:
        return FAIL, "la búsqueda devolvió 0 resultados"
    con_desc = sum(1 for r in res if r.get("original_price"))
    return OK, f"{len(res)} resultados, {con_desc} con precio original"


def c_ml_afiliado():
    from src.models import Deal
    from src.sources.mercadolibre import affiliate_url
    d = Deal(source="mercadolibre", source_id="MLM123",
             url="https://articulo.mercadolibre.com.mx/MLM-123-prueba",
             title="prueba", image_url="")
    u = affiliate_url(d)
    if "matt_" not in u and u == d.url:
        return FAIL, "no se generó link de afiliado (revisa ML_AFFILIATE_TAG)"
    return WARN, (f"link generado: {u[:90]}… — VALIDA LA ATRIBUCIÓN con una "
                  "compra de prueba antes de confiar en esto")


def c_amazon():
    if not Secrets.AMZ_PARTNER_TAG():
        return WARN, "sin AMZ_PARTNER_TAG: Amazon desactivado"
    from src.sources.amazon import affiliate_url
    u = affiliate_url("B0TEST1234", sub_id="doctor")
    if not (Secrets.AMZ_CREDENTIAL_ID() and Secrets.AMZ_CREDENTIAL_SECRET()):
        return WARN, f"links OK ({u[:60]}…) pero sin Creators API (modo manual)"
    from src.sources.amazon import CreatorsAPI
    items = CreatorsAPI().search_items(search_index="All", min_saving_percent=30)
    return (OK, f"Creators API viva, {len(items)} items") if items else \
           (WARN, "Creators API respondió sin items")


# --------------------------------------------------------------- publicación
def c_buffer():
    from src.publish.buffer import Buffer
    canales = Buffer().channels()
    if not canales:
        return FAIL, "la API responde pero no hay canales conectados"
    detalle = ", ".join(f"{c['service']}:{c['id'][:8]}…" for c in canales)
    ids = {c["id"] for c in canales}
    faltan = [n for n, v in (("IG", Secrets.BUFFER_CHANNEL_IG()),
                             ("TikTok", Secrets.BUFFER_CHANNEL_TIKTOK()))
              if v and v not in ids]
    if faltan:
        return WARN, f"{detalle} — pero el ID de {', '.join(faltan)} no coincide"
    return OK, detalle


def c_media():
    base = Secrets.MEDIA_BASE_URL()
    if not base:
        return FAIL, "sin MEDIA_BASE_URL: Buffer no podrá descargar las imágenes"
    r = requests.get(base.rsplit("/media", 1)[0] + "/", timeout=15)
    if r.status_code == 200:
        return OK, f"GitHub Pages responde en {base}"
    return WARN, f"la página respondió {r.status_code} — ¿ya activaste Pages?"


# --------------------------------------------------------------- creativo
def c_creativo():
    from src.creative import card
    from src.models import Deal
    d = Deal(source="amazon", source_id="TEST", url="x",
             title="Producto de prueba para el diagnóstico del sistema",
             image_url="", price=499, original_price=999)
    p = card.render(d, out_dir=Path("/tmp"))
    kb = Path(p).stat().st_size // 1024
    return OK, f"tarjeta generada ({kb} KB)"


if __name__ == "__main__":
    print("\n— Diagnóstico Ofertas Sin Fin —\n")
    check("Secretos", c_secretos)
    check("Creativo (Pillow)", c_creativo)
    if get("fuentes.mercadolibre.activa"):
        check("ML · token OAuth", c_ml_token)
        check("ML · búsqueda", c_ml_search)
        check("ML · link de afiliado", c_ml_afiliado)
    check("Amazon", c_amazon)
    check("Buffer", c_buffer)
    check("Hosting de imágenes", c_media)

    fails = sum(1 for e, *_ in resultados if e == FAIL)
    print(f"\n{len(resultados)} pruebas · {fails} en rojo\n")
    sys.exit(1 if fails else 0)
