"""Genera la tanda de reactivación de la cuenta, en los tres formatos reales.

Ofertas de Mercado Libre capturadas el 26/08/2026.
Cuando el sistema esté conectado esto lo hace el pipeline solo; el script
existe para producir la primera tanda a mano y validar formato y tono.

Salida en data/stories/:
  instagram_story/   1080x1920  · zonas seguras de IG Stories, hueco para
                                  el sticker de link o de encuesta
  tiktok/            1080x1920  · photo post; esquiva la barra de acciones
                                  de la derecha y el caption de abajo
  instagram_feed/    1080x1350  · carrusel de feed, solo las ofertas

    python scripts/secuencia_reactivacion.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

from src.creative import card as C  # noqa: E402
from src.creative import story  # noqa: E402
from src.models import Deal  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
OUT = RAIZ / "data" / "stories"
IMGS = Path("/root/prod")          # fotos de producto ya descargadas

# Las imágenes de producto están en disco: leerlas de ahí en vez de la red.
_orig = C.fetch_image
C.fetch_image = story.fetch_image = lambda u, timeout=20: (
    Image.open(u).convert("RGBA") if Path(u).exists() else _orig(u, timeout)
)

OFERTAS = [
    Deal(
        source="mercadolibre", source_id="MLM53177027",
        url="https://www.mercadolibre.com.mx/hidrolavadora-electrica-portatil-1200w-1600-psi-alta-presion-amarillo-60hz-para-lavar-carros/p/MLM53177027",
        title="Hidrolavadora Eléctrica Portátil 1200W · 1600 PSI",
        image_url=str(IMGS / "hidrolavadora.png"),
        category="hogar", brand="Trent",
        price=854, original_price=2299,
        rating=4.8, sold=250000, free_shipping=True,
    ),
    Deal(
        source="mercadolibre", source_id="MLM29367002",
        url="https://www.mercadolibre.com.mx/recipientes-24-pz-hermeticos-de-almacenamiento-de-cocina-transparente-raganet/p/MLM29367002",
        title="24 Recipientes Herméticos para Cocina",
        image_url=str(IMGS / "recipientes.png"),
        category="cocina", brand="Raganet",
        price=329, original_price=699,
        rating=4.8, sold=50000, free_shipping=True,
    ),
    Deal(
        source="mercadolibre", source_id="MLM50224717",
        url="https://www.mercadolibre.com.mx/colchon-individual-noite-basic-con-memory-adapt-gris/p/MLM50224717",
        title="Colchón Individual Noite Basic con Memory Adapt",
        image_url=str(IMGS / "colchon.png"),
        category="hogar", brand="Noite",
        price=1599, original_price=3926,
        rating=4.8, sold=5000, free_shipping=True,
    ),
]

ALIAS = {"MLM53177027": "hidrolavadora",
         "MLM29367002": "recipientes",
         "MLM50224717": "colchon"}

PLANTILLAS = ["crema", "negro", "crema"]


def generar():
    dirs = {k: OUT / k for k in ("instagram_story", "tiktok", "instagram_feed")}
    for p in dirs.values():
        p.mkdir(parents=True, exist_ok=True)
    hechos = {k: [] for k in dirs}

    # --- 01 Reactivación -------------------------------------------------
    for destino, carpeta in (("instagram", "instagram_story"), ("tiktok", "tiktok")):
        hechos[carpeta].append(story.render_statement(
            plantilla="crema", destino=destino, marca_grande=True,
            eyebrow="después de un rato en pausa",
            titulo="Volvimos.\nY ahora sí,\ntodos los días.",
            cuerpo="Rastreamos Mercado Libre buscando descuentos reales — de "
                   "esos que sí bajaron de precio, no los que fingen bajar. "
                   "Lo que encontramos, aquí te lo dejamos.",
            pie="Nuevas ofertas cada día",
            out_dir=dirs[carpeta], nombre="01_reactivacion.png",
        ))

    # --- 02 Encuesta -----------------------------------------------------
    # En IG existe el sticker de encuesta. En TikTok no: la conversación
    # pasa por comentarios, así que el CTA cambia.
    hechos["instagram_story"].append(story.render_statement(
        plantilla="naranja", destino="instagram",
        eyebrow="tú decides",
        titulo="¿Qué cazamos\nesta semana?",
        cuerpo="Vota abajo y esa es la categoría que voy a rastrear los "
               "próximos siete días.",
        cta_sticker="VOTA AQUÍ ABAJO",
        pie="Gana la más votada. Sin trampa.",
        out_dir=dirs["instagram_story"], nombre="02_encuesta.png",
    ))
    hechos["tiktok"].append(story.render_statement(
        plantilla="naranja", destino="tiktok",
        eyebrow="tú decides",
        titulo="¿Qué cazamos\nesta semana?",
        cuerpo="Escribe tu categoría en los comentarios. La más pedida es la "
               "que voy a rastrear los próximos siete días.",
        cta_boton="COMENTA LA TUYA",
        pie="Gana la más pedida. Sin trampa.",
        out_dir=dirs["tiktok"], nombre="02_encuesta.png",
    ))

    # --- 03 a 05 Ofertas -------------------------------------------------
    for i, (deal, plantilla) in enumerate(zip(OFERTAS, PLANTILLAS), start=3):
        base = f"0{i}_oferta_{ALIAS[deal.source_id]}.png"
        hechos["instagram_story"].append(story.render_offer(
            deal, plantilla=plantilla, destino="instagram",
            out_dir=dirs["instagram_story"], nombre=base))
        hechos["tiktok"].append(story.render_offer(
            deal, plantilla=plantilla, destino="tiktok",
            out_dir=dirs["tiktok"], nombre=base))
        p = C.render(deal, formato="instagram", plantilla=plantilla,
                     out_dir=dirs["instagram_feed"])
        destino_feed = dirs["instagram_feed"] / base
        Path(p).replace(destino_feed)
        hechos["instagram_feed"].append(destino_feed)

    return hechos


def hoja_contactos(rutas, salida: Path, alto_px: int = 560):
    ims = [Image.open(p) for p in rutas]
    esc = alto_px / ims[0].height
    w, h = int(ims[0].width * esc), alto_px
    hoja = Image.new("RGB", (len(ims) * (w + 20) + 20, h + 40), (24, 25, 32))
    for i, im in enumerate(ims):
        hoja.paste(im.resize((w, h), Image.LANCZOS), (20 + i * (w + 20), 20))
    hoja.save(salida)
    return salida


if __name__ == "__main__":
    hechos = generar()
    for carpeta, rutas in hechos.items():
        print(f"\n{carpeta}  ({len(rutas)} piezas)")
        for r in rutas:
            print("  ", r)
        hoja_contactos(rutas, OUT / f"_hoja_{carpeta}.png")
    print(f"\nHojas de contacto en {OUT}")
