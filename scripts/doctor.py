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

    def precio_de(p: dict) -> tuple:
        b = p.get("buy_box_winner") or {}
        return b.get("price"), b.get("original_price")

    # 1. Producto de catálogo: el padre suele ser una FAMILIA sin buy box.
    pid = next((c["id"] for c in contenido if c.get("type") == "PRODUCT"), "")
    if pid:
        p = s.get(f"{API}/products/{pid}", timeout=25).json()
        pr, orig = precio_de(p)
        hijos = p.get("children_ids") or []
        print(f"      · producto {pid}: precio={pr} original={orig} "
              f"hijos={len(hijos)}")
        if not pr and hijos:
            rh = s.get(f"{API}/products/{hijos[0]}", timeout=25)
            if rh.status_code == 200:
                h = rh.json()
                phr, phorig = precio_de(h)
                print(f"      · HIJO {hijos[0]}: precio={phr} original={phorig}")
            else:
                print(f"      · HIJO {hijos[0]} → {rh.status_code}")
        # Aquí es donde vive el precio: las ofertas concretas del producto.
        ri = s.get(f"{API}/products/{pid}/items",
                   params={"limit": 1}, timeout=25)
        print(f"      · /products/{pid}/items → {ri.status_code}")
        if ri.status_code == 200:
            res = (ri.json() or {}).get("results") or []
            if res:
                o = res[0]
                print(f"      · campos de la oferta: {campos(o)}")
                print(f"      · precio={o.get('price')} "
                      f"original={o.get('original_price')} "
                      f"vendidos={o.get('sold_quantity')} "
                      f"envío={(o.get('shipping') or {}).get('free_shipping')}")

            # Con un item_id REAL en la mano: ¿por qué el multiget da 0?
            real = (res[0].get("item_id") or res[0].get("id")) if res else ""
            if real:
                rm = s.get(f"{API}/items", params={"ids": real}, timeout=25)
                sobres = rm.json() if rm.status_code == 200 else []
                w = sobres[0] if isinstance(sobres, list) and sobres else {}
                print(f"      · multiget {real} → HTTP {rm.status_code} · "
                      f"sobre code={w.get('code')} "
                      f"{json.dumps(w, ensure_ascii=False)[:200] if not w.get('body') else 'CON BODY'}")
                rs1 = s.get(f"{API}/items/{real}", timeout=25)
                print(f"      · /items/{real} → {rs1.status_code}")
                if rs1.status_code == 200:
                    it = rs1.json()
                    print(f"      · precio={it.get('price')} "
                          f"original={it.get('original_price')} "
                          f"vendidos={it.get('sold_quantity')}")

    # 2. USER_PRODUCT: no es un item, /items le da 404. ¿Por dónde se resuelve?
    uid = next((c["id"] for c in contenido
                if c.get("type") == "USER_PRODUCT"), "")
    if uid:
        for ruta in (f"/user-products/{uid}", f"/products/{uid}",
                     f"/items/{uid}"):
            r2 = s.get(f"{API}{ruta}", timeout=25)
            extra = ""
            if r2.status_code == 200:
                j = r2.json()
                extra = f" · {campos(j)[:150]}"
            print(f"      · {ruta} → {r2.status_code}{extra}")

    # 3. /products/search: ¿trae precio de una vez? Sería una llamada, no dos.
    rs = s.get(f"{API}/products/search",
               params={"site_id": site, "status": "active",
                       "q": "freidora de aire"}, timeout=25)
    if rs.status_code == 200:
        res = (rs.json() or {}).get("results") or []
        print(f"      · products/search: {len(res)} resultados")
        if res:
            pr, orig = precio_de(res[0])
            print(f"      · campos: {campos(res[0])}")
            print(f"      · primero: precio={pr} original={orig}")

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
    otros = 0
    for cat in cats:
        for pos in ml.highlights(cat):
            if pos["id"] in vistos:
                continue
            vistos.add(pos["id"])
            if pos["type"] == "PRODUCT":
                productos.append(pos["id"])
            elif pos["type"] == "ITEM":
                items.append(pos["id"])
            else:
                otros += 1

    if not (items or productos):
        return FAIL, "ninguna categoría devolvió best-sellers"

    d_items = [d for d in (ml.to_deal(r) for r in ml.items(items[:20])) if d]
    d_cat = list(ml.catalogo_a_deals(productos[:40]))      # muestra de 40
    deals = d_items + d_cat

    minimo = get("filtros.descuento_minimo_pct", 25)
    con_desc = [d for d in deals if d.discount_pct > 0]
    publicables = [d for d in con_desc if d.discount_pct >= minimo]

    print(f"      · {len(cats)} categorías → {len(items)} items + "
          f"{len(productos)} productos + {otros} de otro tipo")
    print(f"      · 40 productos de catálogo → {len(d_cat)} ofertas armadas "
          f"· {len(d_items)} de publicaciones sueltas")
    sin_tachado = sum(1 for d in d_cat if not d.original_price)
    print(f"      · {sin_tachado} de {len(d_cat)} sin precio anterior "
          f"(esos nunca podrán mostrar descuento)")
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
