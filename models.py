"""Modelos de datos compartidos por todo el sistema."""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


@dataclass
class Deal:
    """Una oferta candidata, normalizada sin importar la fuente."""

    # --- identidad ---
    source: str                      # "mercadolibre" | "amazon"
    source_id: str                   # MLM123456789 | ASIN
    url: str                         # URL limpia del producto (sin afiliado)

    # --- contenido ---
    title: str
    image_url: str
    category: str = ""
    category_id: str = ""
    brand: str = ""

    # --- precio ---
    price: float = 0.0               # precio actual MXN
    original_price: Optional[float] = None
    currency: str = "MXN"

    # --- señales de calidad ---
    rating: Optional[float] = None
    reviews: int = 0
    sold: int = 0
    free_shipping: bool = False
    is_full: bool = False            # ML Full / Amazon Prime

    # --- derivados ---
    discount_pct: float = 0.0
    est_commission_mxn: float = 0.0
    score: float = 0.0

    # --- afiliado ---
    affiliate_url: str = ""

    # --- trazabilidad ---
    fetched_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    raw: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        if self.original_price and self.original_price > self.price > 0:
            # Se trunca hacia abajo a propósito: los marketplaces muestran el
            # descuento truncado. Redondear hacia arriba exagera la oferta —
            # 62.85% se anuncia como 62%, igual que en la ficha del producto.
            self.discount_pct = float(
                math.floor((1 - self.price / self.original_price) * 100)
            )

    @property
    def key(self) -> str:
        """Clave estable para deduplicar entre corridas."""
        return f"{self.source}:{self.source_id}"

    @property
    def content_hash(self) -> str:
        """Hash del creativo: cambia si cambia precio o título."""
        base = f"{self.key}|{self.price}|{self.title[:60]}"
        return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("raw", None)
        return d


@dataclass
class Post:
    """Una publicación lista para encolar."""

    deal: Deal
    image_paths: dict                # {"instagram": path, "tiktok": path}
    image_urls: dict = field(default_factory=dict)
    caption: str = ""
    scheduled_at: Optional[str] = None   # ISO 8601 UTC
    template: str = "clasica"
    status: str = "pending"              # pending | scheduled | failed
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "deal": self.deal.to_dict(),
            "image_paths": self.image_paths,
            "image_urls": self.image_urls,
            "caption": self.caption,
            "scheduled_at": self.scheduled_at,
            "template": self.template,
            "status": self.status,
            "error": self.error,
        }
