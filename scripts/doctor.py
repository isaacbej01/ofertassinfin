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
    from src.sources.mercadolibre import auth
    t = auth().token()
    # Nunca se imprime el token, ni un fragmento: el log de un repo público
    # también es público. Basta con saber que se obtuvo y cuánto mide.
    return OK, f"access token obtenido ({len(t)} caracteres)"


# Endpoints candidatos para descubrir ofertas. Se prueban TODOS y se reporta qué
# responde cada uno: a lo largo de 2026 ML fue cerrando el acceso público a
# /sites/{site}/search (403 Forbidden aun con OAuth válido) sin documentarlo.
# Saber cuáles siguen abiertos es lo que decide cómo se descubren las ofertas.
SONDAS = (
    ("categorias del sitio",   "/sites/{site}/categories", {}),
    ("busqueda por texto",     "/sites/{site}/search",
     {"q": "audifonos bluetooth", "limit": 5}),
    ("busqueda por categoria", "/sites/{site}/search",
     {"category": "MLM1051", "limit": 5}),
    ("mas vendidos",           "/highlights/{site}/category/MLM1051", {}),
    ("catalogo de productos",  "/products/search",
     {"site_id": "{site}", "status": "active", "q": "audifonos bluetooth"}),
    ("tendencias",             "/trends/{site}", {}),
    ("multiget de items",      "/items", {"ids": "MLM1234567890"}),
)


def c_ml_endpoints():
    """Sonda cada endpoint y reporta el código HTTP tal cual lo devuelve ML."""
    from src.sources.mercadolibre import API, UA, auth

    sesion = requests.Session()
    sesion.headers.update({"User-Agent": UA, "Accept": "application/json",
                           "Authorization": f"Bearer {auth().token()}"})
    site = get("fuentes.mercadolibre.site_id", "MLM")
    print("   sondeando endpoints de descubrimiento:")

    vivos, muertos = [], []
    for nombre, ruta, params in SONDAS:
        p = {k: (v.format(site=site) if isinstance(v, str) else v)
             for k, v in params.items()}
        try:
            r = sesion.get(f"{API}{ruta.format(site=site)}", params=p, timeout=25)
        except requests.RequestException as e:
            print(f"      · {nombre:<24} red: {e}")
            muertos.append(nombre)
            continue

        if r.status_code == 200:
            try:
                cuerpo = r.json()
            except ValueError:
                cuerpo = {}
            if isinstance(cuerpo, list):
                n = len(cuerpo)
            elif isinstance(cuerpo, dict):
                n = len(cuerpo.get("results") or cuerpo.get("content") or [])
            else:
                n = 0
            print(f"      · {nombre:<24} 200 OK · {n} elementos")
            (vivos if n else muertos).append(nombre)
        else:
            # El cuerpo del error de ML explica el motivo y no trae credenciales.
            print(f"      · {nombre:<24} {r.status_code} · {r.text[:130]}")
            muertos.append(nombre)

    if not vivos:
        return FAIL, ("ningún endpoint de descubrimiento devolvió datos — "
                      "hay que cambiar la fuente de ofertas")
    return OK, f"sirven: {', '.join(vivos)}"


def c_ml_forma():
    """Imprime la forma REAL de las respuestas de ML.

    Existe porque ML cambia el contrato sin avisar y el normalizador asume
    campos que pueden haber dejado de existir. Cuando la cosecha salga en
    cero, esto dice por qué en una sola corrida en vez de tres.
    """
    import json

    from src.sources.mercadolibre import API, UA, auth

    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json",
                      "Authorization": f"Bearer {auth().token()}"})
    site = get("fuentes.mercadolibre.site_id", "MLM")

    r = s.get(f"{API}/highlights/{site}/category/MLM1051", timeout=25)
    contenido = (r.json() or {}).get("content") or []
    tipos: dict = {}
    for c in contenido:
        tipos[c.get("type")] = tipos.get(c.get("type"), 0) + 1
    print(f"      · highlights: {len(contenido)} posiciones, tipos {tipos}")
    print(f"      · muestra: {json.dumps(contenido[:2], ensure_ascii=False)[:200]}")

    def campos(d: dict, k: str = "") -> str:
        return f"{k}{sorted(d.keys())}"[:320]

    pid = next((c["id"] for c in contenido if c.get("type") == "PRODUCT"), "")
    if pid:
        rp = s.get(f"{API}/products/{pid}", timeout=25)
        print(f"      · /products/{pid} → {rp.status_code}")
        if rp.status_code == 200:
            p = rp.json()
            print(f"      · campos: {campos(p)}")
            bbw = p.get("buy_box_winner") or {}
            print(f"      · buy_box_winner: {campos(bbw) if bbw else 'AUSENTE'}")
            print(f"      · precio={bbw.get('price')} "
                  f"original={bbw.get('original_price')}")

    iid = next((c["id"] for c in contenido if c.get("type") != "PRODUCT"), "")
    if iid:
        ri = s.get(f"{API}/items", params={"ids": iid}, timeout=25)
        cuerpo = ri.json() if ri.status_code == 200 else []
        w = cuerpo[0] if isinstance(cuerpo, list) and cuerpo else {}
        print(f"      · /items?ids={iid} → {ri.status_code} · "
              f"code={w.get('code')}")
        if w.get("body"):
            print(f"      · campos: {campos(w['body'])}")

    return OK, "forma de las respuestas impresa arriba"


def c_ml_cosecha():
    """Corre el descubrimiento de verdad y cuenta cuántas ofertas publicables
    salen. Es la única pregunta que importa: que los endpoints respondan 200
    no sirve de nada si al final del embudo no quedan ofertas con descuento.
    """
    from src.sources.mercadolibre import MercadoLibre

    ml = MercadoLibre()
    cats = ml.categorias()[:12]              # muestra: 12 categorías bastan
    items: list[str] = []
    productos: list[str] = []
    vistos: set[str] = set()
    for cat in cats:
        for pos in ml.highlights(cat):
            if pos["id"] in vistos:
                continue
            vistos.add(pos["id"])
            (productos if pos["type"] == "PRODUCT" else items).append(pos["id"])

    if not (items or productos):
        return FAIL, "ninguna categoría devolvió best-sellers"

    deals = [d for d in (ml.to_deal(r) for r in ml.items(items[:200])) if d]
    deals += [d for d in (ml.producto_a_deal(r)
                          for r in ml.productos(productos[:60])) if d]

    minimo = get("filtros.descuento_minimo_pct", 25)
    con_desc = [d for d in deals if d.discount_pct > 0]
    publicables = [d for d in con_desc if d.discount_pct >= minimo]

    print(f"      · {len(cats)} categorías → {len(items)} items + "
          f"{len(productos)} productos → {len(deals)} normalizados")
    print(f"      · {len(con_desc)} con descuento → {len(publicables)} "
          f"sobre el mínimo de {minimo}%")
    for d in sorted(publicables, key=lambda x: -x.discount_pct)[:3]:
        print(f"      · -{d.discount_pct:.0f}%  ${d.price:,.0f}  {d.title[:52]}")

    if not publicables:
        return WARN, ("hay catálogo pero nada pasa el descuento mínimo — "
                      "hay que bajar el filtro o buscar otra fuente")
    if len(publicables) < 8:
        return WARN, (f"solo {len(publicables)} ofertas publicables: alcanza "
                      "para hoy pero no para sostener 4 posts diarios")
    return OK, f"{len(publicables)} ofertas publicables de {len(deals)} items"


def c_ml_afiliado():
    from src.models import Deal
    from src.sources.mercadolibre import affiliate_url

    if not Secrets.ML_AFFILIATE_TAG():
        return WARN, ("todavía sin ML_AFFILIATE_TAG: los links saldrían sin "
                      "afiliado (pendiente el alta del programa)")

    d = Deal(source="mercadolibre", source_id="MLM123",
             url="https://articulo.mercadolibre.com.mx/MLM-123-prueba",
             title="prueba", image_url="")
    if "matt_" not in affiliate_url(d):
        return FAIL, "hay tag configurado pero no se inyectó en la URL"
    return WARN, ("link con parámetros de afiliado — VALIDA LA ATRIBUCIÓN con "
                  "una compra de prueba antes de confiar")


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
    rotos = [c for c in canales if c.get("isDisconnected")]
    detalle = " · ".join(f"{c.get('service')}:@{c.get('name')} → {c.get('id')}"
                         for c in canales)
    if rotos:
        return WARN, f"{detalle} — DESCONECTADO: {', '.join(c['service'] for c in rotos)}"
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
        check("ML · endpoints", c_ml_endpoints)
        check("ML · forma de las respuestas", c_ml_forma)
        check("ML · cosecha real", c_ml_cosecha)
        check("ML · link de afiliado", c_ml_afiliado)
    check("Amazon", c_amazon)
    check("Buffer", c_buffer)
    check("Hosting de imágenes", c_media)

    fails = sum(1 for e, *_ in resultados if e == FAIL)
    print(f"\n{len(resultados)} pruebas · {fails} en rojo\n")
    sys.exit(1 if fails else 0)
