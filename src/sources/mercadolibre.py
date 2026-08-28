"""Fuente: MercadoLibre México.

Descubrimiento vía API oficial (api.mercadolibre.com) con OAuth.
Generación de link de afiliado vía inyección de parámetros matt_* o,
si se configura cookie de sesión, vía el endpoint interno del panel.

NOTAS DE REALIDAD (agosto 2026):
  * ML NO tiene API pública oficial de afiliados. La generación de links
    es el punto frágil del sistema — ver scripts/validate_ml.py.
  * La API de productos exige access token. Solo hay grant types
    authorization_code y refresh_token: no hay modo server-to-server puro.
    Por eso se autoriza una vez a mano (scripts/ml_oauth.py) y luego se
    rota el access token con el refresh token (válido 6 meses).
"""
from __future__ import annotations

import logging
import re
import time
from typing import Iterator
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

import requests

from ..config import Secrets, get
from ..models import Deal

log = logging.getLogger(__name__)

API = "https://api.mercadolibre.com"
UA = "OfertasSinFin/1.0 (+https://github.com/)"


class MercadoLibreError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class MLAuth:
    """Maneja el access token (6 h) a partir del refresh token (6 meses)."""

    def __init__(self):
        self._token = None
        self._expires = 0.0
        self._refresh_vigente: str | None = None

    def token(self) -> str:
        if self._token and time.time() < self._expires - 120:
            return self._token

        # Si ya refrescamos una vez en este proceso, el valor del secret quedó
        # muerto: ML solo acepta el ÚLTIMO refresh token que emitió.
        refresh = self._refresh_vigente or Secrets.ML_REFRESH_TOKEN()
        if not refresh:
            raise MercadoLibreError(
                "No hay ML_REFRESH_TOKEN. Corre `python scripts/ml_oauth.py` una vez "
                "para autorizar la app y obtenerlo."
            )

        r = requests.post(
            f"{API}/oauth/token",
            headers={"accept": "application/json",
                     "content-type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "refresh_token",
                "client_id": Secrets.ML_CLIENT_ID(),
                "client_secret": Secrets.ML_CLIENT_SECRET(),
                "refresh_token": refresh,
            },
            timeout=30,
        )
        if r.status_code != 200:
            raise MercadoLibreError(
                f"No se pudo refrescar el token de ML ({r.status_code}): {r.text[:300]}"
            )
        data = r.json()
        self._token = data["access_token"]
        self._expires = time.time() + int(data.get("expires_in", 10800))

        nuevo_refresh = data.get("refresh_token")
        if nuevo_refresh and nuevo_refresh != refresh:
            self._refresh_vigente = nuevo_refresh
            _persistir_refresh(nuevo_refresh)

        return self._token


def _persistir_refresh(token: str):
    """Guarda el refresh token nuevo. Este es el punto más frágil del sistema.

    La documentación de ML es explícita: «the refresh_token is for one-time use
    only and you will receive a new one at each token update process» y «after
    being used it will become invalid». O sea que el valor guardado en el secret
    queda muerto en cuanto se usa una vez. Si el nuevo no se persiste, la
    siguiente corrida falla y hay que reautorizar a mano.

    Por eso NO se imprime ni se avisa nada más: se escribe en el archivo que
    indica ML_TOKEN_FILE y el workflow lo sube como secret del repo. El log de
    un repo público también es público.
    """
    import os

    # Si algún otro punto del código llegara a imprimirlo, que GitHub lo tape.
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::add-mask::{token}", flush=True)

    destino = os.environ.get("ML_TOKEN_FILE")
    if not destino:
        log.error(
            "ML rotó el refresh token y no hay ML_TOKEN_FILE donde guardarlo. "
            "La próxima corrida va a fallar: reautoriza con el workflow "
            "«Autorizar MercadoLibre»."
        )
        return

    with open(destino, "w", encoding="utf-8") as f:
        f.write(token)          # sin salto de línea: `gh secret set` lo toma tal cual
    log.warning("ML rotó el refresh token; escrito para persistirlo como secret.")


# Una sola instancia por proceso. Cada MLAuth extra provocaría un refresh extra,
# y cada refresh mata el token anterior: dos instancias son una carrera perdida.
_auth_compartido: "MLAuth | None" = None


def auth() -> "MLAuth":
    global _auth_compartido
    if _auth_compartido is None:
        _auth_compartido = MLAuth()
    return _auth_compartido


# ---------------------------------------------------------------------------
# Cliente
# ---------------------------------------------------------------------------
class MercadoLibre:
    def __init__(self):
        self.auth = auth()
        self.site = get("fuentes.mercadolibre.site_id", "MLM")
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept": "application/json"})

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{API}{path}"
        for intento in range(3):
            r = self.s.get(
                url,
                params=params or {},
                headers={"Authorization": f"Bearer {self.auth.token()}"},
                timeout=30,
            )
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503):
                time.sleep(2 ** intento)
                continue
            if r.status_code in (401, 403):
                raise MercadoLibreError(
                    f"ML rechazó la llamada a {path} ({r.status_code}). "
                    f"Revisa el token y los scopes de la app. Detalle: {r.text[:300]}"
                )
            raise MercadoLibreError(f"ML {r.status_code} en {path}: {r.text[:300]}")
        raise MercadoLibreError(f"ML no respondió tras 3 intentos en {path}")

    # ------------------------------------------------------------- discovery
    def categorias(self) -> list[str]:
        """IDs de categoría a barrer.

        Las de config van primero (son las de mejor comisión); después se
        agregan todas las del sitio. Desde que /search murió, las categorías
        son la única puerta de entrada al catálogo, así que conviene tenerlas
        completas y no depender de una lista escrita a mano que envejece.
        """
        conf = get("fuentes.mercadolibre", {})
        fijas = [c for c in (conf.get("categorias") or []) if c]
        tope = int(conf.get("max_categorias", 40))

        if not conf.get("descubrir_categorias", True):
            return fijas[:tope]

        try:
            data = self._get(f"/sites/{self.site}/categories")
        except MercadoLibreError as e:
            log.warning("no se pudo listar las categorías del sitio: %s", e)
            return fijas[:tope]

        del_sitio = [c["id"] for c in (data if isinstance(data, list) else [])
                     if isinstance(c, dict) and c.get("id")]
        return list(dict.fromkeys(fijas + del_sitio))[:tope]

    def search(self, q: str = "", category: str = "", limit: int = 50) -> list[dict]:
        """⚠️ MUERTO. ML devuelve 403 forbidden en /sites/{site}/search desde
        2026, aun con OAuth válido y la app bien configurada — confirmado por
        el diagnóstico del 28/08/2026 y por decenas de reportes públicos de
        otros desarrolladores. No lo llama nadie; se conserva por si ML
        reabre el acceso.
        """
        params = {"limit": min(limit, 50), "offset": 0}
        if q:
            params["q"] = q
        if category:
            params["category"] = category
        try:
            data = self._get(f"/sites/{self.site}/search", params)
        except MercadoLibreError as e:
            log.error("search falló (q=%r cat=%r): %s", q, category, e)
            return []
        return data.get("results", [])

    def highlights(self, category_id: str) -> list[dict]:
        """Top 20 más vendidos de una categoría.

        Devuelve [{"id": ..., "type": "ITEM"|"PRODUCT"}]. La distinción importa:
        México migró a catálogo, así que la mayoría de las posiciones ya no son
        publicaciones sueltas (ITEM) sino productos de catálogo (PRODUCT), que
        se resuelven por otro endpoint. La primera versión filtraba solo ITEM y
        por eso 12 categorías rendían 8 items.
        """
        try:
            data = self._get(f"/highlights/{self.site}/category/{category_id}")
        except MercadoLibreError as e:
            log.warning("highlights falló (%s): %s", category_id, e)
            return []
        return [
            {"id": c["id"], "type": c.get("type") or "ITEM"}
            for c in data.get("content", []) if c.get("id")
        ]

    def items(self, ids: list[str]) -> list[dict]:
        """Trae publicaciones completas. Multiget de a 20, con plan B.

        El multiget devuelve una lista de sobres {code, body}: un 200 global
        puede traer 20 sobres con 403 adentro. Cuando un lote entero viene
        vacío se cae a /items/{id} uno por uno, que es más caro pero es la
        diferencia entre tener catálogo y no tenerlo.
        """
        out: list[dict] = []
        codigos: dict = {}
        for i in range(0, len(ids), 20):
            chunk = ids[i:i + 20]
            data = []
            try:
                data = self._get("/items", {"ids": ",".join(chunk)})
            except MercadoLibreError as e:
                log.warning("multiget falló: %s", e)

            obtenidos = 0
            for wrapper in data if isinstance(data, list) else []:
                cod = wrapper.get("code")
                codigos[cod] = codigos.get(cod, 0) + 1
                if cod == 200 and wrapper.get("body"):
                    out.append(wrapper["body"])
                    obtenidos += 1

            if obtenidos:
                continue

            # Plan B: el lote vino vacío. Uno por uno.
            for iid in chunk:
                try:
                    cuerpo = self._get(f"/items/{iid}")
                except MercadoLibreError:
                    continue
                if isinstance(cuerpo, dict) and cuerpo.get("id"):
                    out.append(cuerpo)

        if codigos:
            log.info("multiget: sobres por código %s", codigos)
        log.info("items: %d pedidos → %d obtenidos", len(ids), len(out))
        return out

    @staticmethod
    def _tiene_precio(p: dict) -> bool:
        return bool((p.get("buy_box_winner") or {}).get("price"))

    def catalogo_a_deals(self, product_ids: list[str]) -> Iterator[Deal]:
        """Arma ofertas juntando las dos capas que ML SÍ deja leer.

        El diagnóstico del 28/08/2026 cerró la discusión: /items/{id} responde
        403 hasta con un ID real, o sea que no hay forma de leer la publicación
        completa de otro vendedor. Pero no hace falta:

            /products/{id}        → nombre, fotos, marca, permalink, rating
            /products/{id}/items  → precio, precio anterior, envío, vendidos

        Entre las dos está todo lo que necesita un creativo. Son dos llamadas
        por producto en vez de una, y es el precio de seguir vivos en ML.
        """
        for pid in product_ids:
            try:
                p = self._get(f"/products/{pid}")
                data = self._get(f"/products/{pid}/items", {"limit": 1})
            except MercadoLibreError as e:
                log.warning("producto %s: %s", pid, e)
                continue

            ofertas = data.get("results") or []
            if not ofertas:
                continue
            d = self.catalogo_a_deal(p, ofertas[0])
            if d:
                yield d

    @staticmethod
    def catalogo_a_deal(producto: dict, oferta: dict) -> Deal | None:
        precio = oferta.get("price")
        pid = producto.get("id") or oferta.get("item_id")
        nombre = producto.get("name") or producto.get("title")
        if not (precio and pid and nombre):
            return None

        img = ""
        for foto in (producto.get("pictures") or []):
            img = foto.get("secure_url") or foto.get("url") or ""
            if img:
                break

        envio = oferta.get("shipping") or {}
        attrs = {a.get("id"): a.get("value_name")
                 for a in (producto.get("attributes") or [])}
        reviews = producto.get("reviews") or {}

        return Deal(
            source="mercadolibre",
            source_id=str(oferta.get("item_id") or pid),
            # El link va a la ficha del producto, no a la publicación de un
            # vendedor: si ese vendedor se queda sin stock, la ficha sigue viva.
            url=(producto.get("permalink")
                 or f"https://www.mercadolibre.com.mx/p/{pid}"),
            title=nombre,
            image_url=img.replace("http://", "https://"),
            category_id=(oferta.get("category_id")
                         or producto.get("domain_id") or ""),
            brand=attrs.get("BRAND", "") or "",
            price=float(precio),
            original_price=(float(oferta["original_price"])
                            if oferta.get("original_price") else None),
            reviews=int(reviews.get("total") or 0),
            rating=(producto.get("rating_average")
                    or reviews.get("rating_average")),
            sold=int(oferta.get("sold_quantity")
                     or producto.get("sold_quantity") or 0),
            free_shipping=bool(envio.get("free_shipping")),
            is_full=bool(envio.get("logistic_type") == "fulfillment"),
            raw={"producto": producto, "oferta": oferta},
        )

    def items_de_productos(self, product_ids: list[str]) -> list[str]:
        """Traduce productos de catálogo a IDs de publicación con precio.

        Un producto de catálogo es una ficha, no una oferta: describe "Freidora
        Ninja 5.5L" sin decir a cuánto. Quien pone precio es cada vendedor, y
        esas ofertas cuelgan de /products/{id}/items — el único de los caminos
        probados que respondió 200 con datos reales. buy_box_winner viene nulo,
        /products/search no trae precio, y los USER_PRODUCT dan 403.

        Devolver IDs (y no Deals) es a propósito: así el multiget y el
        normalizador de items que ya funcionan se encargan del resto.
        """
        item_ids: list[str] = []
        for pid in product_ids:
            try:
                data = self._get(f"/products/{pid}/items", {"limit": 1})
            except MercadoLibreError as e:
                log.warning("ofertas del producto %s: %s", pid, e)
                continue
            for r in (data.get("results") or [])[:1]:
                iid = r.get("item_id") or r.get("id")
                if iid:
                    item_ids.append(iid)
        log.info("productos de catálogo: %d → %d publicaciones",
                 len(product_ids), len(item_ids))
        return item_ids

    # -------------------------------------------------------------- normaliza
    @staticmethod
    def producto_a_deal(raw: dict) -> Deal | None:
        """Normaliza un producto de catálogo.

        El precio no vive en el producto sino en la oferta ganadora del buy box
        (`buy_box_winner`), que es justo el precio que ve el comprador. Sin buy
        box no hay nada que anunciar: el producto existe pero nadie lo vende.
        """
        pid = raw.get("id")
        nombre = raw.get("family_name") or raw.get("name") or raw.get("title")
        ganador = raw.get("buy_box_winner") or {}
        precio = ganador.get("price")
        if not (pid and nombre and precio):
            return None

        original = ganador.get("original_price")
        pics = raw.get("pictures") or []
        img = ""
        for p in pics:
            img = p.get("secure_url") or p.get("url") or ""
            if img:
                break

        envio = ganador.get("shipping") or {}
        attrs = {a.get("id"): a.get("value_name")
                 for a in (raw.get("attributes") or [])}
        rating = (raw.get("rating_average")
                  or (raw.get("reviews") or {}).get("rating_average"))

        return Deal(
            source="mercadolibre",
            source_id=pid,
            url=(raw.get("permalink")
                 or f"https://www.mercadolibre.com.mx/p/{pid}"),
            title=nombre,
            image_url=img.replace("http://", "https://"),
            category_id=raw.get("domain_id", "") or "",
            brand=attrs.get("BRAND", "") or "",
            price=float(precio),
            original_price=float(original) if original else None,
            reviews=int((raw.get("reviews") or {}).get("total") or 0),
            rating=rating,
            sold=int(raw.get("sold_quantity") or 0),
            free_shipping=bool(envio.get("free_shipping")),
            is_full=bool(envio.get("logistic_type") == "fulfillment"),
            raw=raw,
        )

    @staticmethod
    def to_deal(raw: dict) -> Deal | None:
        item_id = raw.get("id")
        title = raw.get("title")
        if not item_id or not title:
            return None

        price = raw.get("price")
        original = raw.get("original_price")
        if not price:
            return None

        # Algunas respuestas traen el precio en sale_price/prices
        if not original:
            prices = (raw.get("prices") or {}).get("prices") or []
            for p in prices:
                if p.get("type") == "standard" and p.get("amount", 0) > price:
                    original = p["amount"]
                    break

        thumb = raw.get("thumbnail") or ""
        pics = raw.get("pictures") or []
        if pics:
            thumb = pics[0].get("secure_url") or pics[0].get("url") or thumb
        # El thumbnail de búsqueda viene en baja resolución: subimos calidad
        thumb = re.sub(r"-[IVDNOQ]\.jpg$", "-F.jpg", thumb).replace("http://", "https://")

        shipping = raw.get("shipping") or {}
        attrs = {a.get("id"): a.get("value_name") for a in (raw.get("attributes") or [])}

        return Deal(
            source="mercadolibre",
            source_id=item_id,
            url=(raw.get("permalink") or f"https://articulo.mercadolibre.com.mx/{item_id}"),
            title=title,
            image_url=thumb,
            category_id=raw.get("category_id", "") or "",
            brand=attrs.get("BRAND", "") or "",
            price=float(price),
            original_price=float(original) if original else None,
            reviews=int((raw.get("reviews") or {}).get("total") or 0),
            rating=(raw.get("reviews") or {}).get("rating_average"),
            sold=int(raw.get("sold_quantity") or 0),
            free_shipping=bool(shipping.get("free_shipping")),
            is_full=bool(shipping.get("logistic_type") == "fulfillment"),
            raw=raw,
        )

    def discover(self) -> Iterator[Deal]:
        """Descubre ofertas vía best-sellers por categoría + multiget.

        Este era el camino secundario hasta que ML cerró /search con 403.
        Ahora es el único, y resulta que no es mal negocio: los highlights ya
        vienen filtrados por lo que la gente realmente compra, así que el
        sesgo de calidad viene incluido. Lo que hay que aportar es cobertura
        de categorías, que es justo lo que da `categorias()`.
        """
        # Falla temprano y una sola vez: sin token no tiene caso intentar
        # 30 llamadas y llenar el log con el mismo error.
        self.auth.token()

        cats = self.categorias()
        items: list[str] = []
        productos: list[str] = []
        ignorados = 0
        vistos: set[str] = set()
        for cat in cats:
            for pos in self.highlights(cat):
                if pos["id"] in vistos:
                    continue
                vistos.add(pos["id"])
                if pos["type"] == "PRODUCT":
                    productos.append(pos["id"])
                elif pos["type"] == "ITEM":
                    items.append(pos["id"])
                else:
                    # USER_PRODUCT y similares: no son items ni productos de
                    # catálogo, y /items les responde 404. Son pocos; mandarlos
                    # al multiget solo ensucia el resultado.
                    ignorados += 1

        log.info("descubrimiento: %d categorías → %d items + %d productos "
                 "(%d posiciones de otro tipo, ignoradas)",
                 len(cats), len(items), len(productos), ignorados)
        if not (items or productos):
            log.error("ninguna categoría devolvió best-sellers. Corre el "
                      "diagnóstico: puede que ML haya cerrado otro endpoint.")
            return

        # Las publicaciones sueltas (ITEM) casi siempre dan 403 desde 2026;
        # se intentan igual porque son gratis de intentar y a veces pasan.
        for raw in self.items(items):
            d = self.to_deal(raw)
            if d:
                yield d

        # El grueso viene del catálogo. Dos llamadas por producto, así que se
        # topa: una corrida no necesita el catálogo entero, solo candidatos
        # suficientes para elegir cuatro.
        tope = int(get("fuentes.mercadolibre.max_productos", 150))
        yield from self.catalogo_a_deals(productos[:tope])


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------
def short_url(url: str, item_id: str = "") -> str:
    """Forma corta y canónica de una URL de Mercado Libre.

    El permalink de ML trae el título completo como slug y se va a 130+
    caracteres. El campo "Website" de la bio de TikTok tiene tope, y una URL
    kilométrica se lee como spam. Las dos formas cortas están verificadas:

        catálogo  →  https://www.mercadolibre.com.mx/p/MLM53177027      (45)
        listing   →  https://articulo.mercadolibre.com.mx/MLM-53177027

    Si no se reconoce el formato, devuelve la URL original: mejor larga que rota.
    """
    m = re.search(r"/p/(MLM\d+)", url or "")
    if m:
        return f"https://www.mercadolibre.com.mx/p/{m.group(1)}"
    m = re.search(r"(MLM)-?(\d+)", url or "") or (
        re.match(r"(MLM)(\d+)", item_id or "") if item_id else None)
    if m:
        return f"https://articulo.mercadolibre.com.mx/MLM-{m.group(2)}"
    return url


# ---------------------------------------------------------------------------
# Links de afiliado
# ---------------------------------------------------------------------------
def affiliate_url(deal: Deal, sub_id: str = "") -> str:
    """Construye el link de afiliado de ML.

    Estrategia A (por defecto): inyectar matt_tool / matt_word en la URL.
    Es lo que hace el propio panel de ML. Requiere ML_AFFILIATE_TAG con el
    formato exacto que veas al generar un link de prueba en tu panel.

    Estrategia B (si hay ML_SESSION_COOKIE): pedir el link corto oficial al
    endpoint interno del panel. Más fiel, pero se puede romper sin aviso.

    ⚠️ VALIDA LA ATRIBUCIÓN con una compra de prueba antes de confiar en esto.
    """
    tag = Secrets.ML_AFFILIATE_TAG()
    if not tag:
        return deal.url

    cookie = Secrets.ML_SESSION_COOKIE()
    if cookie:
        short = _affiliate_url_panel(deal.url, tag, cookie)
        if short:
            return short

    parsed = urlparse(short_url(deal.url, deal.source_id))
    qs = dict(parse_qsl(parsed.query))
    if "|" in tag or ":" in tag:
        # Formato "matt_tool|matt_word" o "matt:usuario:toolid"
        partes = tag.split("|")
        qs["matt_tool"] = partes[0]
        if len(partes) > 1:
            qs["matt_word"] = partes[1]
    else:
        qs["matt_tool"] = tag
    if sub_id:
        qs["matt_word"] = f"{qs.get('matt_word', '')}_{sub_id}".strip("_")
    return urlunparse(parsed._replace(query=urlencode(qs)))


def _affiliate_url_panel(url: str, tag: str, cookie: str) -> str:
    """Endpoint interno del panel de afiliados. NO oficial, no soportado."""
    endpoint = "https://www.mercadolibre.com.mx/affiliate-program/api/v2/stripe/user/links"
    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "cookie": cookie,
        "referer": url,
        "origin": "https://www.mercadolibre.com.mx",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        ),
    }
    try:
        r = requests.post(endpoint, headers=headers,
                          json={"url": url, "tag": tag}, timeout=20)
        if r.status_code == 200:
            return r.json().get("short_url") or r.json().get("long_url") or ""
        log.warning("Endpoint interno de ML devolvió %s", r.status_code)
    except requests.RequestException as e:
        log.warning("Endpoint interno de ML falló: %s", e)
    return ""
