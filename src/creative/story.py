"""Creativos verticales 1080x1920, en dos versiones que NO son intercambiables.

Instagram y TikTok tapan zonas distintas de la pantalla con su propia
interfaz. Un creativo hecho para uno pierde información en el otro, así que
cada oferta se genera dos veces.

INSTAGRAM STORIES
  0–250      barra superior: foto de perfil, usuario, cerrar
  250–1500   contenido
  1500–1740  RESERVADA para el sticker de link o de encuesta (lo pones a
             mano; Meta no permite publicar stickers por API)
  1740–1920  barra inferior: "Enviar mensaje", reacciones
  → El CTA es el hueco vacío con una flecha. El link vive en el sticker.

TIKTOK — photo post (Photo Mode), no Stories: TikTok Stories no tiene API,
Buffer no la soporta y no admite links clicables.
  0–200      pestañas "Siguiendo / Para ti", buscador
  200–1540   contenido
  x > 900    columna de acciones (avatar, like, comentar, guardar, compartir),
             estorba en la mitad inferior de la pantalla
  1540–1920  usuario, caption y ticker de música
  → El CTA es un botón dibujado: en TikTok el único link clicable es el
    de la bio.

Paleta: la del logo real de la cuenta. Ver creativo.plantillas en el config.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw

from ..config import MEDIA_DIR, get
from ..models import Deal
from . import logo as L
from .card import (fetch_image, fit_contain, font, glow, gradient_bg, hex2rgb,
                   money, rounded_mask, star, tokens, wrap_to_width)

W, H = 1080, 1920
M = 76
MX_TZ = timezone(timedelta(hours=-6))

PUNTO_MARKETPLACE = {"amazon": "#FF9900", "mercadolibre": "#FFE600"}
NOMBRE_MARKETPLACE = {"amazon": "AMAZON", "mercadolibre": "MERCADO LIBRE"}

# --------------------------------------------------------------------------
# Geometría por destino. Se ajusta aquí, no dentro de las funciones.
# --------------------------------------------------------------------------
LAYOUT = {
    "instagram": {
        "logo_y": 268,
        "card_y": 396,
        "card_h": 520,
        "ancho_util": W - M,      # no hay columna de acciones que esquivar
        "pie_y": 1388,            # la letra chica va ANTES del CTA: debajo
        "cta_y": 1478,            # la taparía la barra de "Enviar mensaje"
        "hueco_top": 1520,        # 1520–1730 libres para el sticker
        "cta_tipo": "sticker",
    },
    "tiktok": {
        "logo_y": 228,
        "card_y": 336,
        "card_h": 520,
        "ancho_util": 892,        # 1080 − 140 de barra de acciones − aire
        "pie_y": 1328,
        "cta_y": 1396,            # el botón cierra en 1478, sobre el caption
        "hueco_top": None,
        "cta_tipo": "boton",
    },
}

DESTINOS = tuple(LAYOUT)


def elegir_plantilla(i: int | None = None) -> str:
    rot = get("creativo.rotacion", ["crema", "negro", "naranja"])
    return rot[i % len(rot)] if i is not None else random.choice(rot)


# --------------------------------------------------------------------------
def _lienzo(t: dict) -> Image.Image:
    canvas = gradient_bg((W, H), t["fondo"], t["fondo2"]).convert("RGBA")
    if t["oscuro"]:
        canvas.alpha_composite(glow((W, H), (int(W * .98), int(H * .06)), 430,
                                    t["acento"], 44))
    return canvas


def _cabecera(canvas: Image.Image, t: dict, lay: dict):
    lk = L.lockup(84, color_texto=t["tinta"], color_tag=t["acento"],
                  hueco=t["fondo"], cordel=t["tinta"], una_linea=True)
    canvas.alpha_composite(lk, (M, lay["logo_y"]))


def _pill_marketplace(d: ImageDraw.ImageDraw, t: dict, deal: Deal, x: int, y: int):
    nombre = NOMBRE_MARKETPLACE.get(deal.source, deal.source.upper())
    f = font("medium", 25)
    ancho = int(d.textlength(nombre, font=f)) + 82
    d.rounded_rectangle([x, y, x + ancho, y + 54], radius=27, fill=hex2rgb(t["tinta"]))
    d.ellipse([x + 24, y + 20, x + 38, y + 34],
              fill=hex2rgb(PUNTO_MARKETPLACE.get(deal.source, "#FFFFFF")))
    d.text((x + 52, y + 27), nombre, font=f, fill=hex2rgb(t["fondo"]), anchor="lm")


def _cta(d: ImageDraw.ImageDraw, t: dict, lay: dict, texto_sticker: str,
         texto_boton: str):
    """Instagram: rótulo y flecha sobre el hueco. TikTok: botón dibujado."""
    if lay["cta_tipo"] == "sticker":
        cx = W // 2
        d.text((cx, lay["cta_y"]), texto_sticker, font=font("bold", 34),
               fill=hex2rgb(t["acento"]), anchor="mm")
        cy = lay["hueco_top"] + 4
        d.polygon([(cx - 17, cy), (cx + 17, cy), (cx, cy + 24)],
                  fill=hex2rgb(t["acento"]))
    else:
        x1, y0 = lay["ancho_util"], lay["cta_y"]
        d.rounded_rectangle([M, y0, x1, y0 + 82], radius=41, fill=hex2rgb(t["acento"]))
        d.text(((M + x1) // 2, y0 + 41), texto_boton, font=font("bold", 34),
               fill=hex2rgb(t["badge_tinta"]), anchor="mm")


def _pie(d: ImageDraw.ImageDraw, t: dict, lay: dict, con_precio: bool,
         extra: str = "", con_afiliado: bool = True):
    """La leyenda de afiliado solo se imprime si el post REALMENTE lleva link
    de afiliado. Declararla sin tenerlo es tan falso como ocultarla cuando sí
    lo hay — y las dos cosas erosionan lo mismo."""
    ap = hex2rgb(t["apagado"])
    cx = (M + lay["ancho_util"]) // 2 if lay["cta_tipo"] == "boton" else W // 2
    y = lay["pie_y"]
    if con_precio:
        ts = datetime.now(MX_TZ).strftime("Precio al %d/%m/%Y %H:%M h · sujeto a cambio")
        d.text((cx, y), ts, font=font("light", 24), fill=ap, anchor="mm")
        y += 34
    linea = extra or ("Contiene link de afiliado · #PublicidadPagada"
                      if con_afiliado else "")
    if linea:
        d.text((cx, y), linea, font=font("light", 23), fill=ap, anchor="mm")


# --------------------------------------------------------------------------
def render_offer(deal: Deal, plantilla: str = "crema", destino: str = "instagram",
                 con_afiliado: bool = True, cta_texto: str = "",
                 out_dir: Path | None = None, nombre: str | None = None) -> Path:
    """cta_texto sobreescribe el CTA por defecto.

    Hace falta porque el CTA tiene que decir la verdad sobre dónde está el
    link, y eso depende de la cuenta: TikTok solo permite link en bio con
    cuenta Business o 1,000+ seguidores. Sin eso, "link en la bio" es falso
    y la alternativa honesta es pedir el comentario y mandarlo por DM —
    que además es de las dos únicas vías donde TikTok permite links.
    """
    t = tokens(plantilla)
    lay = LAYOUT[destino]
    ancho = lay["ancho_util"]

    canvas = _lienzo(t)
    _cabecera(canvas, t, lay)
    d = ImageDraw.Draw(canvas)

    # ---- foto del producto ----
    # Va a todo lo ancho a propósito: queda por encima de la barra de
    # acciones de TikTok, que solo estorba en la mitad inferior.
    y, card_h = lay["card_y"], lay["card_h"]
    card = Image.new("RGBA", (W - 2 * M, card_h), (255, 255, 255, 255))
    prod = fetch_image(deal.image_url)
    if prod:
        bg = Image.new("RGBA", prod.size, (255, 255, 255, 255))
        bg.alpha_composite(prod)
        prod = fit_contain(bg.convert("RGBA"),
                           (int((W - 2 * M) * .88), int(card_h * .88)))
        card.alpha_composite(prod, ((card.width - prod.width) // 2,
                                    (card.height - prod.height) // 2))
    card.putalpha(rounded_mask(card.size, 44))
    canvas.alpha_composite(card, (M, y))
    if not t["oscuro"]:
        d.rounded_rectangle([M, y, W - M, y + card_h], radius=44,
                            outline=hex2rgb("#E4D9C9"), width=3)
    _pill_marketplace(d, t, deal, M + 26, y + card_h - 78)

    # ---- badge de descuento ----
    if deal.discount_pct > 0:
        bd = 282
        badge = Image.new("RGBA", (bd, bd), (0, 0, 0, 0))
        b = ImageDraw.Draw(badge)
        b.ellipse([0, 0, bd - 1, bd - 1], fill=hex2rgb(t["acento"]))
        tinta = hex2rgb(t["badge_tinta"])
        b.text((bd // 2, int(bd * .43)), f"-{deal.discount_pct:.0f}%",
               font=font("bold", 90), fill=tinta, anchor="mm")
        b.text((bd // 2, int(bd * .70)), "DE DESCUENTO", font=font("medium", 24),
               fill=tinta, anchor="mm")
        badge = badge.rotate(random.choice([-7, 7]), resample=Image.BICUBIC, expand=True)
        canvas.alpha_composite(badge, (W - M - 252, y - 60))

    y += card_h + 46

    # ---- título ----
    f_t = font("bold", 54)
    for ln in wrap_to_width(d, deal.title, f_t, ancho - M, 2):
        d.text((M, y), ln, font=f_t, fill=hex2rgb(t["tinta"]))
        y += 66
    y += 16

    # ---- precios ----
    if deal.original_price:
        f_a = font("medium", 42)
        ant = money(deal.original_price)
        d.text((M, y), ant, font=f_a, fill=hex2rgb(t["apagado"]))
        aw = d.textlength(ant, font=f_a)
        d.line([M - 4, y + 28, M + aw + 4, y + 28], fill=hex2rgb(t["apagado"]), width=4)

        f_h = font("medium", 31)
        ah = f"AHORRAS {money(deal.original_price - deal.price)}"
        ahw = d.textlength(ah, font=f_h)
        d.rounded_rectangle([M + aw + 30, y - 6, M + aw + 30 + ahw + 40, y + 50],
                            radius=28, fill=hex2rgb(t["tinta"]))
        d.text((M + aw + 50, y + 4), ah, font=f_h, fill=hex2rgb(t["fondo"]))
        y += 62

    f_p = font("bold", 112)
    d.text((M, y), money(deal.price), font=f_p, fill=hex2rgb(t["acento"]))
    pw = d.textlength(money(deal.price), font=f_p)
    d.text((M + pw + 18, y + 58), "MXN", font=font("medium", 32),
           fill=hex2rgb(t["apagado"]))
    y += 140

    # ---- señales de confianza ----
    chips = []
    if deal.free_shipping:
        chips.append(("ENVÍO GRATIS", False))
    if deal.rating:
        chips.append((f"{deal.rating:.1f}", True))
    if deal.sold:
        chips.append((f"+{deal.sold:,} vendidos".replace(",", ","), False))
    elif deal.reviews:
        chips.append((f"{deal.reviews:,} opiniones".replace(",", ","), False))

    cx, f_c = M, font("medium", 29)
    for texto, con_estrella in chips[:3]:
        extra = 36 if con_estrella else 0
        cw = d.textlength(texto, font=f_c) + 48 + extra
        if cx + cw > ancho:
            break
        d.rounded_rectangle([cx, y, cx + cw, y + 58], radius=29,
                            outline=hex2rgb(t["apagado"]), width=2)
        tx = cx + 24
        if con_estrella:
            star(d, (tx + 13, y + 29), 14, hex2rgb("#F5A623"))
            tx += extra
        d.text((tx, y + 11), texto, font=f_c, fill=hex2rgb(t["apagado"]))
        cx += cw + 16

    _pie(d, t, lay, con_precio=True, con_afiliado=con_afiliado)
    _cta(d, t, lay, cta_texto or "EL LINK, AQUÍ ABAJO",
         cta_texto or "LINK EN LA BIO")

    out_dir = out_dir or MEDIA_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    fn = nombre or (f"{destino}_{deal.source}_{deal.source_id}_"
                    f"{deal.content_hash}_{plantilla}.png")
    p = out_dir / fn
    canvas.convert("RGB").save(p, "PNG", optimize=True)
    return p


# --------------------------------------------------------------------------
def render_statement(titulo: str, cuerpo: str = "", eyebrow: str = "",
                     pie: str = "", cta_sticker: str = "", cta_boton: str = "",
                     plantilla: str = "crema", destino: str = "instagram",
                     marca_grande: bool = False, out_dir: Path | None = None,
                     nombre: str = "story.png") -> Path:
    """Creativo sin producto: reactivación, encuesta, aviso.

    cta_sticker y cta_boton pueden decir cosas distintas: en Instagram existe
    el sticker de encuesta, en TikTok la conversación pasa por comentarios.
    """
    t = tokens(plantilla)
    lay = LAYOUT[destino]
    ancho = lay["ancho_util"]
    hay_cta = bool(cta_sticker or cta_boton)

    canvas = _lienzo(t)
    _cabecera(canvas, t, lay)
    d = ImageDraw.Draw(canvas)

    tope = lay["card_y"] + 74
    limite = lay["pie_y"] - 56

    if marca_grande:
        tag = L.tag_mark(300, color=t["acento"], hueco=t["fondo"], cordel=t["tinta"])
        canvas.alpha_composite(tag, (M - 18, tope - 30))
        tope += 288

    # El texto se encoge hasta caber. Sin esto, un copy largo se encima con
    # la letra chica del pie — y no se nota hasta que ya está publicado.
    f_eye = font("medium", 30)
    espacio = limite - tope
    escalas = ((100, 38), (92, 36), (84, 34), (76, 32), (68, 30), (60, 28))
    for fs_t, fs_c in escalas:
        f_tit, f_cue = font("bold", fs_t), font("regular", fs_c)
        salto_t, salto_c = int(fs_t * 1.14), int(fs_c * 1.42)
        lineas_t = wrap_to_width(d, titulo, f_tit, ancho - M, 5)
        lineas_c = wrap_to_width(d, cuerpo, f_cue, ancho - M - 16, 7) if cuerpo else []
        alto = (58 if eyebrow else 0) + len(lineas_t) * salto_t \
            + (34 + len(lineas_c) * salto_c if lineas_c else 0)
        if alto <= espacio:
            break

    y = tope + max(0, (espacio - alto) // 2)

    if eyebrow:
        d.text((M, y), eyebrow.upper(), font=f_eye, fill=hex2rgb(t["apagado"]))
        y += 50
        d.line([M, y, M + 100, y], fill=hex2rgb(t["acento"]), width=6)
        y += 22

    for ln in lineas_t:
        d.text((M, y), ln, font=f_tit, fill=hex2rgb(t["tinta"]))
        y += salto_t
    if lineas_c:
        y += 34
        for ln in lineas_c:
            d.text((M, y), ln, font=f_cue, fill=hex2rgb(t["apagado"]))
            y += salto_c

    if pie:
        _pie(d, t, lay, con_precio=False, extra=pie)
    if hay_cta:
        _cta(d, t, lay, cta_sticker or cta_boton, cta_boton or cta_sticker)

    out_dir = out_dir or MEDIA_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / nombre
    canvas.convert("RGB").save(p, "PNG", optimize=True)
    return p
