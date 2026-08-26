"""Fuente: Amazon México.

ESTADO A AGOSTO 2026 — leer antes de tocar:
  * PA-API 5.0 fue apagada el 15 may 2026. No existe. No la programes.
  * La reemplaza la Creators API (creatorsapi.amazon), con OAuth 2.0
    client_credentials en vez de AWS SigV4.
  * Requisito de acceso: >= 10 ventas calificadas en los últimos 30 días
    (ventana rodante). Si pasas 30 días sin ventas, te cortan el acceso y
    lo recuperas ~2 días después de que se embarque una venta referida.
  * Por eso este módulo tiene DOS MODOS:
      - "manual": lee ofertas curadas de config/amazon_manual.yaml y solo
        construye los links de afiliado. Es el modo de arranque (fase 1).
      - "api": descubrimiento automático vía SearchItems + minSavingPercent.

Política crítica: prohibido scrapear las páginas de ofertas de Amazon.
El precio solo puede venir de links de Amazon, Creators API o PA-API, con
caché máximo de 24 h y timestamp visible. Este módulo respeta eso.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Iterator
from urllib.parse import urlencode

import requests
import yaml

from ..config import Secrets, get, ROOT
from ..models import Deal

log = logging.getLogger(__name__)

CREATORS_API = "https://creatorsapi.amazon/catalog/v1"
TOKEN_URL = "https://api.amazon.com/auth/o2/token"   # VERIFICAR en Associates Central
MANUAL_FILE = ROOT / "config" / "amazon_manual.yaml"


class AmazonError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Links de afiliado — funciona SIEMPRE, con o sin API
# ---------------------------------------------------------------------------
def affiliate_url(asin_or_url: str, sub_id: str = "") -> str:
    """https://www.amazon.com.mx/dp/<ASIN>/?tag=<TAG>&ascsubtag=<sub_id>

    Prohibido por política: acortadores de terceros (bit.ly y similares),
    cloaking, o redirecciones que lleguen a Amazon sin clic del usuario.
    """
    tag = Secrets.AMZ_PARTNER_TAG()
    if not tag:
        raise AmazonError("Falta AMZ_PARTNER_TAG (tu tag de afiliado de Amazon MX).")

    if asin_or_url.startswith("http"):
        base = asin_or_url.split("?")[0].rstrip("/")
    else:
        base = f"https://www.amazon.com.mx/dp/{asin_or_url}"

    params = {"tag": tag}
    if sub_id:
        params["ascsubtag"] = sub_id
    return f"{base}/?{urlencode(params)}"


# ---------------------------------------------------------------------------
# Modo manual (fase 1: antes de tener acceso a Creators API)
# ---------------------------------------------------------------------------
def discover_manual() -> Iterator[Deal]:
    """Lee ofertas curadas a mano de config/amazon_manual.yaml.

    Formato de cada entrada:
      - asin: B0XXXXXXX
        title: "Freidora de aire 5.5L"
        image_url: "https://m.media-amazon.com/images/I/....jpg"
        price: 1299
        original_price: 2499
        category: cocina
        rating: 4.5
        reviews: 1200
    """
    if not MANUAL_FILE.exists():
        return
    data = yaml.safe_load(MANUAL_FILE.read_text(encoding="utf-8")) or {}
    for row in data.get("ofertas", []):
        if not row.get("asin"):
            continue
        yield Deal(
            source="amazon",
            source_id=row["asin"],
            url=f"https://www.amazon.com.mx/dp/{row['asin']}",
            title=row.get("title", ""),
            image_url=row.get("image_url", ""),
            category=row.get("category", ""),
            brand=row.get("brand", ""),
            price=float(row.get("price", 0)),
            original_price=(float(row["original_price"])
                            if row.get("original_price") else None),
            rating=row.get("rating"),
            reviews=int(row.get("reviews", 0) or 0),
            free_shipping=bool(row.get("prime", True)),
            raw=row,
        )


# ---------------------------------------------------------------------------
# Modo API (fase 2: Creators API)
# ---------------------------------------------------------------------------
class CreatorsAPI:
    def __init__(self):
        self._token = None
        self._expires = 0.0
        self.marketplace = get("fuentes.amazon.marketplace", "www.amazon.com.mx")

    def token(self) -> str:
        if self._token and time.time() < self._expires - 120:
            return self._token
        cid = Secrets.AMZ_CREDENTIAL_ID()
        sec = Secrets.AMZ_CREDENTIAL_SECRET()
        if not (cid and sec):
            raise AmazonError(
                "Faltan AMZ_CREDENTIAL_ID / AMZ_CREDENTIAL_SECRET. Se generan en "
                "Associates Central → pestaña CreatorsAPI → Create Credential. "
                "El secret se muestra UNA sola vez."
            )
        r = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": cid,
                "client_secret": sec,
                "scope": "creatorsapi::default",
            },
            timeout=30,
        )
        if r.status_code != 200:
            raise AmazonError(
                f"No se pudo obtener token de Creators API ({r.status_code}): "
                f"{r.text[:300]}"
            )
        data = r.json()
        self._token = data["access_token"]
        self._expires = time.time() + int(data.get("expires_in", 3600))
        return self._token

    def _post(self, op: str, payload: dict) -> dict:
        r = requests.post(
            f"{CREATORS_API}/{op}",
            headers={
                "Authorization": f"Bearer {self.token()}",
                "Content-Type": "application/json",
                "x-marketplace": self.marketplace,
            },
            json=payload,
            timeout=40,
        )
        if r.status_code == 429:
            raise AmazonError("Rate limit de Creators API (429). Baja la frecuencia.")
        if r.status_code == 403:
            raise AmazonError(
                "403 de Creators API. Causa más probable: 30 días sin ventas "
                "calificadas → acceso revocado. Se recupera ~2 días después de "
                "que se embarque una venta referida."
            )
        if r.status_code != 200:
            raise AmazonError(f"Creators API {r.status_code}: {r.text[:300]}")
        return r.json()

    def search_items(self, keywords: str = "", search_index: str = "All",
                     min_saving_percent: int = 25, item_page: int = 1) -> list[dict]:
        payload = {
            "partnerTag": Secrets.AMZ_PARTNER_TAG(),
            "marketplace": self.marketplace,
            "searchIndex": search_index,
            "minSavingPercent": min_saving_percent,
            "itemCount": 10,
            "itemPage": item_page,
            "sortBy": "Relevance",
            "resources": [
                "Images.Primary.Large",
                "ItemInfo.Title",
                "ItemInfo.ByLineInfo",
                "ItemInfo.Classifications",
                "OffersV2.Listings.Price",
                "OffersV2.Listings.DealDetails",
                "OffersV2.Listings.Availability",
                "CustomerReviews.StarRating",
                "CustomerReviews.Count",
                "BrowseNodeInfo.BrowseNodes",
            ],
        }
        if keywords:
            payload["keywords"] = keywords
        minp = get("filtros.precio_minimo_mxn")
        maxp = get("filtros.precio_maximo_mxn")
        if minp:
            payload["minPrice"] = int(minp) * 100   # en centavos
        if maxp:
            payload["maxPrice"] = int(maxp) * 100
        try:
            data = self._post("searchItems", payload)
        except AmazonError as e:
            log.error("searchItems falló (%s/%s): %s", search_index, keywords, e)
            return []
        return (data.get("searchResult") or {}).get("items", [])

    @staticmethod
    def to_deal(raw: dict) -> Deal | None:
        asin = raw.get("asin") or raw.get("ASIN")
        if not asin:
            return None
        info = raw.get("itemInfo") or {}
        title = ((info.get("title") or {}).get("displayValue")) or ""
        if not title:
            return None
        img = (((raw.get("images") or {}).get("primary") or {})
               .get("large") or {}).get("url", "")

        listings = ((raw.get("offersV2") or {}).get("listings") or [])
        price = savings_pct = None
        original = None
        for L in listings:
            p = L.get("price") or {}
            price = (p.get("money") or {}).get("amount") or p.get("amount")
            sav = p.get("savings") or {}
            savings_pct = sav.get("percentage")
            if price and savings_pct:
                original = round(float(price) / (1 - savings_pct / 100), 2)
            break
        if not price:
            return None

        reviews = (raw.get("customerReviews") or {})
        brand = ((info.get("byLineInfo") or {}).get("brand") or {}).get("displayValue", "")
        nodes = ((raw.get("browseNodeInfo") or {}).get("browseNodes") or [])
        cat = nodes[0].get("displayName", "") if nodes else ""

        return Deal(
            source="amazon",
            source_id=asin,
            url=f"https://www.amazon.com.mx/dp/{asin}",
            title=title,
            image_url=img,
            category=cat,
            brand=brand,
            price=float(price),
            original_price=float(original) if original else None,
            rating=(reviews.get("starRating") or {}).get("value"),
            reviews=int(reviews.get("count") or 0),
            raw=raw,
        )

    def discover(self) -> Iterator[Deal]:
        conf = get("fuentes.amazon", {})
        minsav = int(get("filtros.descuento_minimo_pct", 25))
        presupuesto = int(conf.get("max_llamadas_por_corrida", 60))
        delay = 1.0 / max(conf.get("tps", 1), 1)
        vistos: set[str] = set()
        llamadas = 0

        for idx in conf.get("search_indexes", ["All"]):
            for page in range(1, 4):          # 10 items x 3 páginas por índice
                if llamadas >= presupuesto:
                    return
                items = self.search_items(search_index=idx,
                                          min_saving_percent=minsav,
                                          item_page=page)
                llamadas += 1
                time.sleep(delay)
                if not items:
                    break
                for raw in items:
                    d = self.to_deal(raw)
                    if d and d.source_id not in vistos:
                        vistos.add(d.source_id)
                        yield d


def discover() -> Iterator[Deal]:
    """Punto de entrada: usa la API si está configurada, si no el modo manual."""
    if Secrets.AMZ_CREDENTIAL_ID() and Secrets.AMZ_CREDENTIAL_SECRET():
        try:
            yield from CreatorsAPI().discover()
            return
        except AmazonError as e:
            log.error("Creators API no disponible, cayendo a modo manual: %s", e)
    yield from discover_manual()
