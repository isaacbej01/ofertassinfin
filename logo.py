"""Marca de Ofertas Sin Fin, dibujada en código.

El avatar de la cuenta es de ~130 px: escalarlo a 1080 se ve borroso. Aquí
se reconstruye la etiqueta de precio y el logotipo con Pillow, así que sale
nítido a cualquier tamaño y respeta los colores muestreados del original:

    naranja  #F96D0F      crema  #FCF7F1      tinta  #101010
"""
from __future__ import annotations

import math

from PIL import Image, ImageDraw

from .card import font, hex2rgb

NARANJA = "#F96D0F"
CREMA = "#FCF7F1"
TINTA = "#101010"

SS = 4          # supersampling: se dibuja 4x y se reduce con LANCZOS


def tag_mark(size: int, color: str = NARANJA, hueco: str = CREMA,
             cordel: str | None = TINTA) -> Image.Image:
    """La etiqueta de precio con el % adentro. Devuelve RGBA cuadrada."""
    S = size * SS
    m = int(S * 0.09)          # margen
    r = int(S * 0.15)          # radio de esquina

    # 1. Silueta: cuadrado redondeado al que se le corta la esquina superior
    #    derecha en diagonal — así es una etiqueta de precio y no un botón.
    mask = Image.new("L", (S, S), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([m, m, S - m, S - m], radius=r, fill=255)
    md.polygon([(int(S * .62), 0), (S, 0), (S, int(S * .62))], fill=0)

    cuerpo = Image.new("RGBA", (S, S), hex2rgb(color) + (255,))
    cuerpo.putalpha(mask)

    # 2. El % antes del hueco, para que el cordel quede encima
    pct = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(pct).text((int(S * .42), int(S * .60)), "%",
                             font=font("bold", int(S * 0.44)),
                             fill=hex2rgb(hueco), anchor="mm")
    pct = pct.rotate(14, resample=Image.BICUBIC, center=(int(S * .42), int(S * .60)))
    cuerpo.alpha_composite(pct)

    d = ImageDraw.Draw(cuerpo)

    # 3. Cordel: sale del hueco hacia la esquina, por encima del corte
    hx, hy, hr = int(S * .705), int(S * .265), int(S * .055)
    if cordel:
        d.line([(hx, hy), (int(S * .97), int(S * .03))],
               fill=hex2rgb(cordel), width=max(2, int(S * .032)))

    # 4. Hueco
    d.ellipse([hx - hr, hy - hr, hx + hr, hy + hr], fill=hex2rgb(hueco))

    # 5. Inclinación de la etiqueta, como en el avatar
    cuerpo = cuerpo.rotate(-8, resample=Image.BICUBIC)
    return cuerpo.resize((size, size), Image.LANCZOS)


def lockup(alto: int, color_texto: str = TINTA, color_tag: str = NARANJA,
           hueco: str = CREMA, cordel: str | None = TINTA,
           una_linea: bool = False) -> Image.Image:
    """Etiqueta + 'Ofertas Sin Fin'. `alto` es la altura total en px."""
    if una_linea:
        fs = int(alto * 0.82)
        f = font("bold", fs)
        tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        tw = int(tmp.textlength("Ofertas Sin Fin", font=f))
        tag = tag_mark(alto, color_tag, hueco, cordel)
        im = Image.new("RGBA", (alto + int(alto * .28) + tw, alto), (0, 0, 0, 0))
        im.alpha_composite(tag, (0, 0))
        ImageDraw.Draw(im).text((alto + int(alto * .28), alto // 2),
                                "Ofertas Sin Fin", font=f,
                                fill=hex2rgb(color_texto), anchor="lm")
        return im

    # Dos líneas, como el avatar
    fs = int(alto * 0.46)
    f = font("bold", fs)
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    tw = int(max(tmp.textlength("Ofertas", font=f), tmp.textlength("Sin Fin", font=f)))
    tag = tag_mark(int(alto * 0.94), color_tag, hueco, cordel)
    gap = int(alto * .20)
    im = Image.new("RGBA", (tag.width + gap + tw, alto), (0, 0, 0, 0))
    im.alpha_composite(tag, (0, (alto - tag.height) // 2))
    d = ImageDraw.Draw(im)
    x = tag.width + gap
    d.text((x, int(alto * .28)), "Ofertas", font=f, fill=hex2rgb(color_texto), anchor="lm")
    d.text((x, int(alto * .74)), "Sin Fin", font=f, fill=hex2rgb(color_texto), anchor="lm")
    return im
