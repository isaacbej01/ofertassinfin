# Ofertas Sin Fin

Sistema automatizado que busca ofertas en Amazon México y Mercado Libre,
genera la tarjeta y el copy, y los programa en TikTok e Instagram con
links de afiliado.

Corre solo, en GitHub Actions, una vez al día. Costo de infraestructura: **$0**.
Único gasto: Buffer (~10 USD/mes) para publicar.

---

## Cómo funciona

```
                        ┌─── GitHub Actions (cron diario, gratis) ───┐
                        │                                            │
  Mercado Libre API ────┤                                            │
  (OAuth, /search,      │   1. DESCUBRIR   ~600 productos            │
   /highlights, /items) │   2. FILTRAR     descuento, precio,        │
                        │                  rating, palabras vetadas  │
  Amazon Creators API ──┤   3. RANKEAR     score = descuento +       │
  (o config/amazon_     │                  comisión + popularidad    │
   manual.yaml)         │   4. LINK        afiliado + subtag         │
                        │   5. CREATIVO    PNG 1080x1350 y 1080x1920 │
                        │   6. COPY        gancho + disclosure        │
                        │   7. PROGRAMAR   Buffer → IG + TikTok      │
                        │   8. LINK-IN-BIO página estática           │
                        └────────────────────┬───────────────────────┘
                                             │
                    docs/  →  GitHub Pages  ──┼──►  imágenes públicas
                                             └──►  ofertassinfin link-in-bio
```

El estado (qué se publicó, cuándo) vive en `data/state.json` y se commitea
solo. Sin base de datos, sin servidor, sin nada que se te caiga.

---

## Arranque rápido

```bash
git clone <tu-repo> && cd ofertas-sin-fin
pip install -r requirements.txt
cp .env.example .env          # y llénalo — ver SETUP.md

python scripts/demo.py        # ve cómo se ven las tarjetas, sin tocar APIs
python scripts/doctor.py      # diagnóstico: qué está conectado y qué no
python -m src.pipeline --dry-run -v   # corrida completa sin publicar
python -m src.pipeline                # en serio
```

**`SETUP.md` tiene el checklist de altas.** Empieza por ahí.

---

## Estructura

| Ruta | Qué es |
|---|---|
| `config/config.yaml` | **Todo lo que vas a querer ajustar.** Umbrales, categorías, horarios, comisiones, copy. Sin tocar código. |
| `config/amazon_manual.yaml` | Ofertas de Amazon curadas a mano, para la fase 1 (antes de tener Creators API). |
| `src/sources/mercadolibre.py` | OAuth, descubrimiento y links de afiliado de ML. |
| `src/sources/amazon.py` | Creators API + modo manual + construcción de links. |
| `src/scoring.py` | Filtros duros y ranking. Aquí decides qué es "buena oferta". |
| `src/creative/card.py` | Generación del PNG con Pillow. Tres plantillas que rotan. |
| `src/copywriter.py` | Caption, ganchos rotativos, hashtags, disclosure. |
| `src/publish/buffer.py` | Cliente de la API GraphQL de Buffer. |
| `src/linkinbio.py` | Página de link-in-bio (GitHub Pages). |
| `src/pipeline.py` | El orquestador. |
| `scripts/doctor.py` | Diagnóstico de todo el sistema. Córrelo cuando algo falle. |
| `scripts/ml_oauth.py` | Autorización inicial de ML. Se corre una vez. |

---

## Ajustes que vas a querer hacer

**"Publica muy poco"** → baja `filtros.descuento_minimo_pct` (25 → 20) o agrega
queries en `fuentes.mercadolibre.queries`.

**"Publica basura"** → sube `filtros.rating_minimo`, `filtros.reviews_minimas`,
o agrega palabras a `filtros.excluir_palabras`.

**"Quiero más posts al día"** → `cadencia.posts_por_dia` y agrega horarios en
`cadencia.horarios`. Ojo: TikTok tiene tope de ~15 posts/día por creador,
y subir de golpe a una cuenta dormida es la forma más rápida de que te
limiten el alcance. Sube de 2 a 4 a 6 a lo largo de semanas.

**"Quiero enfocarme en belleza"** → deja solo esas queries y sube
`scoring.bonus_categoria.belleza`.

---

## Lo que este sistema NO hace (todavía)

- **Video.** Fase 1 es imágenes. El generador de video vertical con voz IA
  es el siguiente módulo, y encaja en `src/creative/`.
- **Responder comentarios o DMs.**
- **Medir conversión real.** Los subtags (`ascsubtag` en Amazon, `matt_word`
  en ML) ya se generan por día, así que el reporte de afiliados te dirá qué
  día rindió. Cruzarlo con los posts es manual por ahora.

---

## Las cuatro cosas que romperán este sistema

Están en orden de probabilidad. `scripts/doctor.py` detecta las cuatro.

1. **El refresh token de ML rota o expira** (6 meses). El pipeline avisa en el
   log y el workflow deja un `::warning::`. Hay que actualizar el secret.
2. **Amazon corta la Creators API** por 30 días sin ventas calificadas.
   El sistema cae solo a modo manual, pero deja de descubrir ofertas de Amazon.
3. **La generación de links de afiliado de ML.** Es el punto más frágil:
   ML no tiene API oficial de afiliados. Ver la advertencia en `SETUP.md`.
4. **La key de Buffer.** Se revoca al cambiar de plan o de contraseña.

---

## Cumplimiento — no lo quites, no es decoración

- **Disclosure en cada post.** El copy la pone al inicio. PROFECO prohíbe
  esconderla entre hashtags y prohíbe `#Ad` y `#Publi` por ambiguas.
- **Timestamp en el precio.** La tarjeta lo estampa. Amazon exige caché
  máximo de 24 h y timestamp si publicas precios; un post vive meses.
- **Nada de acortadores de terceros** (bit.ly y similares) en links de Amazon:
  está prohibido por el operating agreement y es causal de cierre.
- **Nada de pauta pagada** sobre posts con link de afiliado de Amazon: desde
  el 14 abr 2026 esas compras quedan excluidas de comisión.
- **Nada de scraping** de las páginas de ofertas de Amazon. El precio solo
  puede venir de links de Amazon o de la Creators API.
- **Toggle de contenido comercial activado** en TikTok e Instagram.
