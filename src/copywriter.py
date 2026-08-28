"""Generación del caption.

Reglas duras que este módulo respeta (no las quites):
  * Disclosure de afiliado SIEMPRE, al inicio y visible. PROFECO prohíbe
    esconderla entre hashtags y prohíbe abreviaturas ambiguas como #Publi o #Ad.
  * El precio va con timestamp o no va como promesa. Un post vive meses;
    el precio no.
  * Ni TikTok ni Instagram hacen clicables los links del caption. El link
    real vive en la página de link-in-bio (src/linkinbio.py).
"""
from __future__ import annotations

import random

from .config import get
from .models import Deal

# Ganchos rotativos. La variedad es lo que evita que los sistemas antispam
# lean la cuenta como un bot publicando la misma plantilla.
GANCHOS = [
    "Esto bajó {pct}% y no sé por cuánto tiempo.",
    "{pct}% menos. Así de simple.",
    "Encontré esto a {pct}% de descuento y tuve que compartirlo.",
    "De {antes} a {ahora}. Sí, leíste bien.",
    "Te ahorras {ahorro} en esto 👇",
    "{pct}% off. Si lo necesitabas, es hoy.",
    "Bajó {pct}%. Mi trabajo es avisarte, el tuyo decidir.",
    "Cayó a {ahora}. Antes costaba {antes}.",
]

CIERRES = [
    "Precio al momento de publicar, puede cambiar sin aviso.",
    "El precio cambia solo, revísalo antes de comprar.",
    "Ojo: los precios en estas plataformas se mueven todo el día.",
]


def money(v: float) -> str:
    return f"${v:,.0f} MXN".replace(",", ",")


def _hashtags(deal: Deal) -> str:
    base = list(get("copy.hashtags_base", []))
    base += list(get(f"copy.hashtags_por_fuente.{deal.source}", []))

    # Hashtags de categoría a partir del título
    mapa = {
        "cocina": "#cocina", "sartén": "#cocina", "freidora": "#airfryer",
        "licuadora": "#cocina", "cafetera": "#cafe",
        "audífono": "#audifonos", "audifono": "#audifonos",
        "bocina": "#bocinas", "smartwatch": "#smartwatch",
        "laptop": "#tecnologia", "celular": "#tecnologia",
        "crema": "#skincare", "perfume": "#perfumes", "maquillaje": "#belleza",
        "tenis": "#tenis", "mochila": "#mochilas",
        "aspiradora": "#hogar", "organizador": "#organizacion",
        "silla": "#hogar", "lámpara": "#decoracion", "lampara": "#decoracion",
    }
    t = deal.title.lower()
    for k, v in mapa.items():
        if k in t and v not in base:
            base.append(v)

    random.shuffle(base)
    return " ".join(base[: get("copy.max_hashtags", 10)])


def caption(deal: Deal, incluir_link: bool = False, red: str = "") -> str:
    disclosure = (
        get("copy.disclosure_amazon")
        if deal.source == "amazon"
        else "Contiene link de afiliado: puedo recibir una comisión si compras, "
             "sin costo extra para ti."
    )

    gancho = random.choice(GANCHOS).format(
        pct=f"{deal.discount_pct:.0f}",
        antes=money(deal.original_price) if deal.original_price else "",
        ahora=money(deal.price),
        ahorro=money((deal.original_price or deal.price) - deal.price),
    )

    titulo = deal.title if len(deal.title) <= 90 else deal.title[:87] + "…"
    # Cada red tiene su propia verdad sobre dónde está el link. TikTok no
    # da link en bio hasta los 1,000 seguidores: prometerlo ahí sería
    # mandar a la gente a un lugar vacío.
    opciones = get(f"copy.cta_{red}", None) if red else None
    cta = random.choice(opciones or get("copy.cta", ["Link en la bio 🔗"]))
    tienda = "Amazon México" if deal.source == "amazon" else "Mercado Libre"

    partes = [
        f"#PublicidadPagada · {disclosure}",
        "",
        gancho,
        "",
        f"📦 {titulo}",
        f"🏷️ {money(deal.price)}"
        + (f" (antes {money(deal.original_price)})" if deal.original_price else ""),
        f"🛒 En {tienda}",
        "",
        cta,
        "",
        random.choice(CIERRES),
    ]

    if incluir_link and deal.affiliate_url:
        partes.insert(-2, deal.affiliate_url)

    partes += ["", _hashtags(deal)]
    return "\n".join(partes).strip()
