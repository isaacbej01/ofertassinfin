"""Filtrado y ranking de ofertas candidatas."""
from __future__ import annotations

import logging
import unicodedata
from typing import Iterable

from .config import get
from .models import Deal

log = logging.getLogger(__name__)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return s.lower()


# ---------------------------------------------------------------------------
# Filtros duros
# ---------------------------------------------------------------------------
def passes(d: Deal) -> tuple[bool, str]:
    f = get("filtros", {})

    if d.discount_pct < f.get("descuento_minimo_pct", 25):
        return False, f"descuento {d.discount_pct}% < mínimo"
    if not d.original_price:
        return False, "sin precio original: no hay descuento verificable"
    if d.price < f.get("precio_minimo_mxn", 0):
        return False, "precio muy bajo"
    if d.price > f.get("precio_maximo_mxn", 10 ** 9):
        return False, "precio muy alto"
    if not d.image_url:
        return False, "sin imagen"
    if len(d.title) < 12:
        return False, "título muy corto"

    if d.rating is not None and d.rating < f.get("rating_minimo", 0):
        return False, f"rating {d.rating} < mínimo"
    # Reviews: solo exigimos el mínimo cuando la fuente reporta reviews.
    # ML frecuentemente no las expone en search; ahí usamos sold_quantity.
    if d.reviews and d.reviews < f.get("reviews_minimas", 0) and d.sold < 50:
        return False, "poca prueba social"

    if f.get("requiere_envio_gratis") and not d.free_shipping:
        return False, "sin envío gratis"

    t = _norm(d.title)
    for palabra in f.get("excluir_palabras", []):
        if _norm(palabra) in t:
            return False, f"palabra excluida: {palabra}"

    # Descuentos absurdos suelen ser precio original inflado
    if d.discount_pct > 90:
        return False, "descuento inverosímil (>90%), probable precio inflado"

    return True, ""


# ---------------------------------------------------------------------------
# Comisión estimada
# ---------------------------------------------------------------------------
def estimate_commission(d: Deal) -> float:
    c = get(f"comisiones.{d.source}", {}) or {}
    rate = c.get("default", 0.08)
    hay = _norm(f"{d.category} {d.title}")
    for cat, r in (c.get("por_categoria") or {}).items():
        if _norm(cat) in hay:
            rate = r
            break
    bruto = d.price * rate
    tope = c.get("tope_mxn_default")
    if tope:
        if any(k in hay for k in ("computo", "videojuego", "television", " tv ", "monitor")):
            tope = c.get("tope_mxn_electronica", tope)
        bruto = min(bruto, tope)
    return round(bruto, 2)


# ---------------------------------------------------------------------------
# Score
# ---------------------------------------------------------------------------
def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def score(d: Deal) -> float:
    w = get("scoring", {})
    d.est_commission_mxn = estimate_commission(d)

    s_desc = _clamp01(d.discount_pct / 70.0)
    s_com = _clamp01(d.est_commission_mxn / 300.0)
    social = max(d.reviews, d.sold)
    s_pop = _clamp01((social / 1000.0) ** 0.5)
    s_rat = _clamp01(((d.rating or 4.0) - 3.0) / 2.0)

    total = (
        w.get("peso_descuento", 0.45) * s_desc
        + w.get("peso_comision", 0.25) * s_com
        + w.get("peso_popularidad", 0.20) * s_pop
        + w.get("peso_rating", 0.10) * s_rat
    )

    hay = _norm(f"{d.category} {d.title}")
    for cat, bonus in (w.get("bonus_categoria") or {}).items():
        if _norm(cat) in hay:
            total += bonus
            break

    if d.free_shipping:
        total += 0.03
    if d.is_full:
        total += 0.02

    d.score = round(total, 4)
    return d.score


# ---------------------------------------------------------------------------
# Selección final con reglas de diversidad
# ---------------------------------------------------------------------------
def select(deals: Iterable[Deal], n: int, ya_publicados_hoy: dict | None = None) -> list[Deal]:
    ya_publicados_hoy = ya_publicados_hoy or {}
    candidatos, descartes = [], {}

    for d in deals:
        ok, motivo = passes(d)
        if not ok:
            descartes[motivo] = descartes.get(motivo, 0) + 1
            continue
        score(d)
        candidatos.append(d)

    candidatos.sort(key=lambda x: x.score, reverse=True)
    log.info("Candidatos válidos: %d. Descartes: %s", len(candidatos), descartes)

    max_fuente = get("cadencia.max_por_fuente_por_dia", {}) or {}
    max_cat_seguidos = get("cadencia.max_misma_categoria_seguidos", 2)

    elegidos: list[Deal] = []
    por_fuente = dict(ya_publicados_hoy)
    racha_cat, racha_n = None, 0

    for d in candidatos:
        if len(elegidos) >= n:
            break
        tope = max_fuente.get(d.source)
        if tope is not None and por_fuente.get(d.source, 0) >= tope:
            continue
        cat = d.category_id or d.category or "sin_categoria"
        if cat == racha_cat and racha_n >= max_cat_seguidos:
            continue
        elegidos.append(d)
        por_fuente[d.source] = por_fuente.get(d.source, 0) + 1
        racha_n = racha_n + 1 if cat == racha_cat else 1
        racha_cat = cat

    return elegidos
