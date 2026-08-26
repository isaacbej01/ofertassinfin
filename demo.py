"""Genera tarjetas de ejemplo sin tocar ninguna API. Sirve para
iterar el diseño y para ver qué va a publicar el sistema.

    python scripts/demo.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import copywriter                     # noqa: E402
from src.creative import card                  # noqa: E402
from src.models import Deal                    # noqa: E402
from src import scoring                        # noqa: E402

EJEMPLOS = [
    Deal(
        source="mercadolibre", source_id="MLM1234567890",
        url="https://articulo.mercadolibre.com.mx/MLM-1234567890",
        title="Freidora De Aire Digital 5.5L Antiadherente Sin Aceite",
        image_url="https://http2.mlstatic.com/D_NQ_NP_2X_placeholder-F.jpg",
        category_id="MLM1574", brand="Ninja",
        price=1299, original_price=2599,
        rating=4.6, reviews=3412, sold=5000,
        free_shipping=True, is_full=True,
    ),
    Deal(
        source="amazon", source_id="B0CXYZ1234",
        url="https://www.amazon.com.mx/dp/B0CXYZ1234",
        title="Audífonos Inalámbricos Bluetooth 5.3 con Cancelación de Ruido",
        image_url="", category="audio", brand="Soundcore",
        price=749, original_price=1499,
        rating=4.4, reviews=890, free_shipping=True,
    ),
    Deal(
        source="amazon", source_id="B0ABCD5678",
        url="https://www.amazon.com.mx/dp/B0ABCD5678",
        title="Set de Brochas de Maquillaje Profesional 15 Piezas con Estuche",
        image_url="", category="belleza",
        price=289, original_price=699,
        rating=4.7, reviews=2140,
    ),
]

if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "data" / "demo"
    out.mkdir(parents=True, exist_ok=True)
    plantillas = ["clasica", "flash", "minimal"]
    for d, plantilla in zip(EJEMPLOS, plantillas):
        scoring.score(d)
        p = card.render(d, formato="instagram", plantilla=plantilla, out_dir=out)
        print(f"\n{'='*72}\n{plantilla.upper()}  ·  score {d.score}  ·  "
              f"comisión estimada ${d.est_commission_mxn:,.0f}\n{p}\n")
        print(copywriter.caption(d))
