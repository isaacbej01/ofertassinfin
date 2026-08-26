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

    def token(self) -> str:
        if self._token and time.time() < self._expires - 120:
            return self._token

        refresh = Secrets.ML_REFRESH_TOKEN()
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
            # ML rota el refresh token. Hay que persistirlo o el sistema muere
            # en 6 horas. El workflow lo escribe de vuelta a los secrets.
            log.warning(
                "ML rotó el refresh token. Actualiza el secret ML_REFRESH_TOKEN con: %s",
                nuevo_refresh,
            )
            _emit_github_output("ml_new_refresh_token", nuevo_refresh)

        return self._token


def _emit_github_output(name: str, value: str):
    """Expone un valor al workflow de GitHub Actions."""
    import os
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")


# ---------------------------------------------------------------------------
# Cliente
# ---------------------------------------------------------------------------
class MercadoLibre:
    def __init__(self):
        self.auth = MLAuth()
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
    def search(self, q: str = "", category: str = "", limit: int = 50) -> list[dict]:
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

    def highlights(self, category_id: str) -> list[str]:
        """Top 20 más vendidos de una categoría. Devuelve IDs de item."""
        try:
            data = self._get(f"/highlights/{self.site}/category/{category_id}")
        except MercadoLibreError as e:
            log.warning("highlights falló (%s): %s", category_id, e)
            return []
        return [
            c["id"] for c in data.get("content", [])
            if c.get("type") == "ITEM" and c.get("id")
        ]

    def items(self, ids: list[str]) -> list[dict]:
        """Multiget: hasta 20 IDs por llamada."""
        out = []
        for i in range(0, len(ids), 20):
            chunk = ids[i:i + 20]
            try:
                data = self._get("/items", {"ids": ",".join(chunk)})
            except MercadoLibreError as e:
                log.warning("multiget falló: %s", e)
                continue
            for wrapper in data if isinstance(data, list) else []:
                if wrapper.get("code") == 200 and wrapper.get("body"):
                    out.append(wrapper["body"])
        return out

    # -------------------------------------------------------------- normaliza
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
        # Falla temprano y una sola vez: sin token no tiene caso intentar
        # 30 búsquedas y llenar el log con el mismo error.
        self.auth.token()

        conf = get("fuentes.mercadolibre", {})
        limit = conf.get("resultados_por_query", 50)
        vistos: set[str] = set()

        for q in conf.get("queries", []):
            for raw in self.search(q=q, limit=limit):
                d = self.to_deal(raw)
                if d and d.source_id not in vistos:
                    vistos.add(d.source_id)
                    yield d

        for cat in conf.get("categorias", []):
            ids = [i for i in self.highlights(cat) if i not in vistos]
            for raw in self.items(ids):
                d = self.to_deal(raw)
                if d and d.source_id not in vistos:
                    vistos.add(d.source_id)
                    yield d
            for raw in self.search(category=cat, limit=limit):
                d = self.to_deal(raw)
                if d and d.source_id not in vistos:
                    vistos.add(d.source_id)
                    yield d


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
