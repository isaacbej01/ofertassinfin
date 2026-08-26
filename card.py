"""Generación de la tarjeta de oferta (PNG) con Pillow.

Sin navegador headless: arranca en <1s y corre igual en GitHub Actions
que en local. Tres plantillas que rotan para que la parrilla no se vea
como un bot publicando la misma imagen cuatro veces al día.
"""
from __future__ import annotations

import io
import logging
import math
import random
import textwrap
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..config import MEDIA_DIR, get
from ..models import Deal

log = logging.getLogger(__name__)

ASSETS = Path(__file__).parent / "assets"
MX_TZ = timezone(timedelta(hours=-6))

FONTS = {
    "bold": ASSETS / "Poppins-Bold.ttf",
    "medium": ASSETS / "Poppins-Medium.ttf",
    "regular": ASSETS / "Poppins-Regular.ttf",
    "light": ASSETS / "Poppins-Light.ttf",
}

_FALLBACK = {"fondo": "#FCF7F1", "fondo2": "#F3E8DA", "tinta": "#101010",
             "apagado": "#7A7168", "acento": "#F96D0F",
             "badge_tinta": "#FFFFFF", "oscuro": False}


def tokens(plantilla: str) -> dict:
    """Paleta de una plantilla, leída de creativo.plantillas en el config."""
    t = get(f"creativo.plantillas.{plantilla}")
    return dict(_FALLBACK, **t) if t else dict(_FALLBACK)


MARKETPLACE = {
    "amazon": {"nombre": "AMAZON", "color": "#FF9900"},
    "mercadolibre": {"nombre": "MERCADO LIBRE", "color": "#FFE600"},
}


def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS[weight]), size)


def hex2rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def money(v: float) -> str:
    return f"${v:,.0f}".replace(",", ",")


# ---------------------------------------------------------------------------
# Utilidades de dibujo
# ---------------------------------------------------------------------------
def fetch_image(url: str, timeout: int = 20) -> Image.Image | None:
    try:
        r = requests.get(url, timeout=timeout,
                         headers={"User-Agent": "Mozilla/5.0 OfertasSinFin/1.0"})
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert("RGBA")
    except Exception as e:                      # noqa: BLE001
        log.warning("No se pudo descargar la imagen %s: %s", url, e)
        return None


def fit_contain(img: Image.Image, box: tuple[int, int]) -> Image.Image:
    w, h = box
    ratio = min(w / img.width, h / img.height)
    return img.resize((max(1, int(img.width * ratio)), max(1, int(img.height * ratio))),
                      Image.LANCZOS)


def rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1],
                                        radius=radius, fill=255)
    return m


def wrap_to_width(draw, text: str, fnt, max_w: int, max_lines: int) -> list[str]:
    palabras, lineas, actual = text.split(), [], ""
    for p in palabras:
        prueba = f"{actual} {p}".strip()
        if draw.textlength(prueba, font=fnt) <= max_w:
            actual = prueba
        else:
            if actual:
                lineas.append(actual)
            actual = p
            if len(lineas) == max_lines:
                break
    if actual and len(lineas) < max_lines:
        lineas.append(actual)
    if len(lineas) == max_lines and len(" ".join(lineas)) < len(text):
        ult = lineas[-1]
        while ult and draw.textlength(ult + "…", font=fnt) > max_w:
            ult = ult[:-1]
        lineas[-1] = ult.rstrip() + "…"
    return lineas


def star(draw: ImageDraw.ImageDraw, center: tuple[int, int], r: int, color):
    """Estrella de 5 puntas. Poppins no trae el glifo ★ y sale como tofu."""
    cx, cy = center
    pts = []
    for i in range(10):
        ang = math.radians(-90 + i * 36)
        rad = r if i % 2 == 0 else r * 0.42
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    draw.polygon(pts, fill=color)


def gradient_bg(size, top: str, bottom: str) -> Image.Image:
    w, h = size
    base = Image.new("RGB", (1, h))
    t, b = hex2rgb(top), hex2rgb(bottom)
    px = base.load()
    for y in range(h):
        k = y / max(h - 1, 1)
        px[0, y] = tuple(int(t[i] + (b[i] - t[i]) * k) for i in range(3))
    return base.resize(size, Image.BILINEAR)


def glow(size, center, radius, color, alpha=110) -> Image.Image:
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy = center
    d.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
              fill=hex2rgb(color) + (alpha,))
    return layer.filter(ImageFilter.GaussianBlur(radius // 2))


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------
def render(deal: Deal, formato: str = "instagram", plantilla: str = "crema",
           out_dir: Path | None = None) -> Path:
    W, H = get(f"creativo.formatos.{formato}", [1080, 1350])
    tk = tokens(plantilla)
    acento, fondo = tk["acento"], tk["fondo"]
    txt, sec, oscuro = tk["tinta"], tk["apagado"], tk["oscuro"]

    canvas = gradient_bg((W, H), fondo, tk["fondo2"]).convert("RGBA")
    if oscuro:
        canvas.alpha_composite(glow((W, H), (int(W * .98), int(H * .06)),
                                    int(W * .42), acento, 44))
    d = ImageDraw.Draw(canvas)

    M = 72                                   # margen lateral
    y = int(H * 0.055)

    # ---------------- header: logotipo ----------------
    from . import logo as L
    lk = L.lockup(72, color_texto=txt, color_tag=acento, hueco=fondo, cordel=txt,
                  una_linea=True)
    canvas.alpha_composite(lk, (M, y - 6))
    y += 104

    # ---------------- imagen del producto ----------------
    card_h = int(H * 0.40)
    card_box = [M, y, W - M, y + card_h]
    card = Image.new("RGBA", (W - 2 * M, card_h), (255, 255, 255, 255))
    prod = fetch_image(deal.image_url)
    if prod:
        bg = Image.new("RGBA", prod.size, (255, 255, 255, 255))
        bg.alpha_composite(prod)
        prod = fit_contain(bg.convert("RGBA"),
                           (int((W - 2 * M) * 0.86), int(card_h * 0.86)))
        card.alpha_composite(
            prod, ((card.width - prod.width) // 2, (card.height - prod.height) // 2)
        )
    else:
        ImageDraw.Draw(card).text(
            (card.width // 2, card.height // 2), "SIN IMAGEN",
            font=font("medium", 40), fill=(180, 180, 180), anchor="mm")

    card.putalpha(rounded_mask(card.size, 40))
    canvas.alpha_composite(card, (M, y))
    if not oscuro:
        # sobre fondo claro la tarjeta blanca se pierde: le damos borde
        d.rounded_rectangle(card_box, radius=40, outline=hex2rgb("#E4D9C9"), width=3)
    mk = MARKETPLACE.get(deal.source, {"nombre": deal.source.upper(), "color": "#888888"})
    f_mk = font("medium", 23)
    pw_ = int(d.textlength(mk["nombre"], font=f_mk)) + 76
    px, py = M + 22, y + card_h - 70
    d.rounded_rectangle([px, py, px + pw_, py + 48], radius=24, fill=hex2rgb(txt))
    d.ellipse([px + 22, py + 17, px + 35, py + 30], fill=hex2rgb(mk["color"]))
    d.text((px + 48, py + 24), mk["nombre"], font=f_mk, fill=hex2rgb(fondo), anchor="lm")

    # ---------------- badge de descuento ----------------
    if deal.discount_pct > 0:
        bd = int(W * 0.235)
        badge = Image.new("RGBA", (bd, bd), (0, 0, 0, 0))
        bdr = ImageDraw.Draw(badge)
        bdr.ellipse([0, 0, bd - 1, bd - 1], fill=hex2rgb(acento))
        pct = f"-{deal.discount_pct:.0f}%"
        f_pct = font("bold", int(bd * 0.30))
        bdr.text((bd // 2, int(bd * 0.44)), pct, font=f_pct,
                 fill=hex2rgb(tk["badge_tinta"]), anchor="mm")
        bdr.text((bd // 2, int(bd * 0.70)), "DESCUENTO", font=font("medium", int(bd * 0.09)),
                 fill=hex2rgb(tk["badge_tinta"]), anchor="mm")
        badge = badge.rotate(random.choice([-8, -6, 6, 8]), resample=Image.BICUBIC,
                             expand=True)
        canvas.alpha_composite(badge, (W - M - int(bd * 0.85), y - int(bd * 0.30)))

    y += card_h + 56

    # ---------------- título ----------------
    f_tit = font("bold", 54)
    lineas = wrap_to_width(d, deal.title, f_tit, W - 2 * M, 2)
    for ln in lineas:
        d.text((M, y), ln, font=f_tit, fill=hex2rgb(txt))
        y += 66
    y += 22

    # ---------------- precios ----------------
    if get("creativo.mostrar_precio", True):
        if deal.original_price:
            f_ant = font("medium", 40)
            ant = money(deal.original_price)
            d.text((M, y), ant, font=f_ant, fill=hex2rgb(sec))
            aw = d.textlength(ant, font=f_ant)
            d.line([M - 4, y + 26, M + aw + 4, y + 26], fill=hex2rgb(sec), width=4)

            ahorro = deal.original_price - deal.price
            f_ah = font("medium", 30)
            texto_ah = f"AHORRAS {money(ahorro)}"
            ahw = d.textlength(texto_ah, font=f_ah)
            d.rounded_rectangle([M + aw + 28, y - 4, M + aw + 28 + ahw + 36, y + 48],
                                radius=26, fill=hex2rgb(txt))
            d.text((M + aw + 46, y + 6), texto_ah, font=f_ah, fill=hex2rgb(fondo))
            y += 62

        f_pre = font("bold", 108)
        d.text((M, y), money(deal.price), font=f_pre, fill=hex2rgb(acento))
        pw = d.textlength(money(deal.price), font=f_pre)
        d.text((M + pw + 16, y + 56), "MXN", font=font("medium", 32), fill=hex2rgb(sec))
        y += 132

    # ---------------- señales ----------------
    chips: list[tuple[str, bool]] = []          # (texto, lleva estrella)
    if deal.free_shipping:
        chips.append(("ENVÍO GRATIS", False))
    if deal.is_full:
        chips.append(("FULL" if deal.source == "mercadolibre" else "PRIME", False))
    if deal.rating:
        chips.append((f"{deal.rating:.1f}", True))
    if deal.reviews >= 50:
        chips.append((f"{deal.reviews:,} opiniones".replace(",", ","), False))
    elif deal.sold >= 100:
        chips.append((f"+{deal.sold:,} vendidos".replace(",", ","), False))

    cx = M
    f_chip = font("medium", 28)
    borde = hex2rgb(sec)
    for texto, estrella in chips[:3]:
        extra = 34 if estrella else 0
        cw = d.textlength(texto, font=f_chip) + 44 + extra
        if cx + cw > W - M:
            break
        d.rounded_rectangle([cx, y, cx + cw, y + 54], radius=27, outline=borde, width=2)
        tx = cx + 22
        if estrella:
            star(d, (tx + 12, y + 27), 13, hex2rgb("#F5A623"))
            tx += extra
        d.text((tx, y + 10), texto, font=f_chip, fill=hex2rgb(sec))
        cx += cw + 14

    # ---------------- footer ----------------
    fy = H - 118
    cta = random.choice(get("copy.cta", ["Link en la bio 🔗"]))
    d.rounded_rectangle([M, fy, W - M, fy + 78], radius=39, fill=hex2rgb(acento))
    d.text((W // 2, fy + 39), cta.replace("🔗", "").replace("👆", "").replace("🏃", "").strip().upper(),
           font=font("bold", 34), fill=hex2rgb(tk["badge_tinta"]), anchor="mm")

    if get("creativo.mostrar_timestamp", True):
        ts = datetime.now(MX_TZ).strftime("Precio al %d/%m/%Y %H:%M h")
        d.text((W // 2, fy - 26), f"{ts} · sujeto a cambio",
               font=font("light", 24), fill=hex2rgb(sec), anchor="mm")

    # ---------------- guardar ----------------
    out_dir = out_dir or MEDIA_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{deal.source}_{deal.source_id}_{deal.content_hash}_{plantilla}_{formato}.png"
    path = out_dir / fname
    canvas.convert("RGB").save(path, "PNG", optimize=True)
    return path


def render_all(deal: Deal, plantilla: str | None = None) -> dict:
    plantilla = plantilla or random.choice(get("creativo.rotacion", ["crema"]))
    out = {}
    for formato in get("creativo.formatos", {"instagram": [1080, 1350]}):
        out[formato] = str(render(deal, formato=formato, plantilla=plantilla))
    return out
