"""Página de link-in-bio, generada estáticamente y servida por GitHub Pages.

Existe porque ni TikTok ni Instagram hacen clicables los links de los
captions: el único link clicable de la cuenta es el de la bio. Sin esta
página el sistema publica pero no monetiza.

Tres decisiones de diseño que no son estéticas, son de conversión:

  1. LO DE HOY ARRIBA, GRANDE. Quien llega acaba de ver un post de hoy.
     Si tiene que buscar entre 24 tarjetas, se va. Las de hoy salen en
     tarjetas grandes; el resto queda abajo en formato compacto.

  2. BUSCADOR. Un post de TikTok puede reventar tres semanas después.
     Ese tráfico llega buscando algo que ya no está arriba. El buscador
     filtra en el navegador, sin servidor.

  3. LAS VIEJAS SE MARCAN, NO SE ESCONDEN. Un precio de hace dos semanas
     probablemente ya cambió. Mandar a alguien a una oferta muerta sin
     avisar es publicidad engañosa bajo la LFPC, y quema la confianza que
     es el único activo real de una cuenta de ofertas.

Coste: $0. Vive en docs/index.html del mismo repo.
"""
from __future__ import annotations

import html
import json
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import ROOT, get
from .models import Deal

MX_TZ = timezone(timedelta(hours=-6))
DOCS = ROOT / "docs"
FEED = ROOT / "data" / "linkinbio.json"

MAX_ITEMS = 60          # historia suficiente para la cola larga de TikTok
DIAS_FRESCA = 3         # después de esto, la tarjeta se marca como vieja


def _sin_acentos(txt: str) -> str:
    """La gente busca "colchon", no "Colchón". El índice va sin acentos y
    el JS normaliza la consulta igual, si no el buscador no encuentra nada."""
    n = unicodedata.normalize("NFD", txt or "")
    return "".join(c for c in n if unicodedata.category(c) != "Mn").lower()


def _load_feed() -> list[dict]:
    if FEED.exists():
        try:
            return json.loads(FEED.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return []


def add(deals: list[Deal]) -> list[dict]:
    feed = _load_feed()
    existentes = {d["key"] for d in feed}
    nuevos = []
    for d in deals:
        if d.key in existentes or not d.affiliate_url:
            continue
        nuevos.append({
            "key": d.key,
            "source": d.source,
            "title": d.title,
            "image": d.image_url,
            "price": d.price,
            "original_price": d.original_price,
            "discount_pct": d.discount_pct,
            "url": d.affiliate_url,
            "added_at": datetime.now(timezone.utc).isoformat(),
        })
    feed = (nuevos + feed)[:MAX_ITEMS]
    FEED.parent.mkdir(parents=True, exist_ok=True)
    FEED.write_text(json.dumps(feed, ensure_ascii=False, indent=2), encoding="utf-8")
    return feed


def _edad_dias(iso: str) -> float:
    try:
        t = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return 999.0
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 86400


def _fecha_corta(iso: str) -> str:
    try:
        t = datetime.fromisoformat(iso)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return t.astimezone(MX_TZ).strftime("%d/%m")
    except (ValueError, TypeError):
        return ""


def _tarjeta(it: dict, grande: bool) -> str:
    pct = it.get("discount_pct") or 0
    vieja = _edad_dias(it.get("added_at", "")) > DIAS_FRESCA
    tienda = "Amazon" if it["source"] == "amazon" else "Mercado Libre"
    antes = (f'<s class="antes">${it["original_price"]:,.0f}</s>'
             if it.get("original_price") else "")
    aviso = ('<span class="vieja">Publicada el '
             f'{_fecha_corta(it.get("added_at", ""))} · verifica el precio</span>'
             if vieja else "")
    busca = html.escape(_sin_acentos(f'{it["title"]} {tienda}'), quote=True)

    return f"""
      <a class="card{' big' if grande else ''}" data-buscar="{busca}"
         href="{html.escape(it['url'])}" target="_blank"
         rel="nofollow sponsored noopener">
        <div class="thumb"><img src="{html.escape(it['image'])}" alt="" loading="lazy"></div>
        <div class="info">
          <div class="badges">
            <span class="pill {it['source']}">{tienda}</span>
            {f'<span class="pill off">-{pct:.0f}%</span>' if pct else ''}
          </div>
          <p class="titulo">{html.escape(it['title'])}</p>
          <p class="precio">${it['price']:,.0f} <small>MXN</small> {antes}</p>
          {aviso}
        </div>
        <span class="ir" aria-hidden="true">→</span>
      </a>"""


def build(feed: list[dict] | None = None) -> Path:
    feed = feed if feed is not None else _load_feed()
    marca = get("marca", {})
    acento = marca.get("naranja", "#F96D0F")
    crema = marca.get("crema", "#FCF7F1")
    tinta = marca.get("tinta", "#101010")
    nombre = marca.get("nombre", "Ofertas Sin Fin")
    handle = marca.get("handle_instagram", "@ofertassinfin")
    ahora = datetime.now(MX_TZ).strftime("%d/%m/%Y a las %H:%M h")

    hoy = [it for it in feed if _edad_dias(it.get("added_at", "")) <= 1]
    antes = [it for it in feed if _edad_dias(it.get("added_at", "")) > 1]

    if hoy:
        bloque_hoy = (f'<h2 class="sec">Lo de hoy <span>{len(hoy)}</span></h2>'
                      + "".join(_tarjeta(it, True) for it in hoy))
    elif feed:
        bloque_hoy = ('<h2 class="sec">Lo más reciente</h2>'
                      + "".join(_tarjeta(it, True) for it in feed[:3]))
        antes = feed[3:]
    else:
        bloque_hoy = ('<p class="vacio">Todavía no hay ofertas publicadas.<br>'
                      'Vuelve en un rato.</p>')

    bloque_antes = ""
    if antes:
        bloque_antes = ('<h2 class="sec">Anteriores</h2>'
                        + "".join(_tarjeta(it, False) for it in antes))

    doc = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(nombre)}</title>
<meta name="description" content="Las ofertas que publicamos en {html.escape(handle)}, con su link directo.">
<meta name="robots" content="noindex">
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  :root{{
    --crema:{crema}; --tinta:{tinta}; --acento:{acento};
    --linea:#E4D9C9; --apagado:#7A7168; --blanco:#FFFFFF;
  }}
  body{{
    background:var(--crema); color:var(--tinta);
    font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
    -webkit-font-smoothing:antialiased; padding:22px 16px 72px;
  }}
  .wrap{{max-width:560px;margin:0 auto}}

  header{{text-align:center;margin-bottom:18px}}
  .marca{{display:inline-flex;align-items:center;gap:9px;font-size:23px;
         font-weight:800;letter-spacing:-.02em}}
  .tag{{width:30px;height:30px;background:var(--acento);border-radius:8px;
       display:grid;place-items:center;color:#fff;font-size:15px;font-weight:800;
       clip-path:polygon(0 0,62% 0,100% 38%,100% 100%,0 100%)}}
  .handle{{color:var(--apagado);font-size:13.5px;margin-top:5px}}

  .buscador{{position:relative;margin:16px 0 20px}}
  .buscador input{{
    width:100%;padding:13px 15px 13px 40px;font-size:15px;font-family:inherit;
    color:var(--tinta);background:var(--blanco);border:1px solid var(--linea);
    border-radius:12px;outline:none;
  }}
  .buscador input:focus{{border-color:var(--acento);box-shadow:0 0 0 3px rgba(249,109,15,.16)}}
  .buscador svg{{position:absolute;left:14px;top:50%;transform:translateY(-50%);
                width:16px;height:16px;stroke:var(--apagado);fill:none;stroke-width:2}}

  .aviso{{background:var(--blanco);border:1px solid var(--linea);border-radius:12px;
         padding:11px 13px;font-size:12px;line-height:1.5;color:var(--apagado);
         margin-bottom:22px}}
  .aviso b{{color:var(--tinta);font-weight:600}}

  h2.sec{{font-size:12px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;
         color:var(--apagado);margin:26px 0 11px;display:flex;align-items:center;gap:8px}}
  h2.sec:first-of-type{{margin-top:0}}
  h2.sec span{{background:var(--acento);color:#fff;border-radius:999px;
              padding:1px 7px;font-size:11px;letter-spacing:0}}

  .card{{
    display:flex;gap:13px;align-items:center;background:var(--blanco);
    border:1px solid var(--linea);border-radius:16px;padding:11px;
    margin-bottom:10px;text-decoration:none;color:inherit;
    transition:border-color .15s,transform .15s;
  }}
  .card:hover,.card:focus-visible{{border-color:var(--acento);transform:translateY(-2px)}}
  .card:focus-visible{{outline:3px solid rgba(249,109,15,.4);outline-offset:2px}}
  .thumb{{flex:0 0 76px;height:76px;background:var(--crema);border-radius:11px;
         overflow:hidden;display:grid;place-items:center}}
  .card.big .thumb{{flex-basis:112px;height:112px}}
  .thumb img{{max-width:100%;max-height:100%;object-fit:contain}}
  .info{{flex:1;min-width:0;display:flex;flex-direction:column;gap:5px}}
  .badges{{display:flex;gap:5px;flex-wrap:wrap}}
  .pill{{font-size:10px;font-weight:700;padding:3px 7px;border-radius:999px}}
  .pill.amazon{{background:#FF9900;color:var(--tinta)}}
  .pill.mercadolibre{{background:#FFE600;color:var(--tinta)}}
  .pill.off{{background:var(--acento);color:#fff}}
  .titulo{{font-size:13px;line-height:1.35;color:#3A352F;display:-webkit-box;
          -webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}
  .card.big .titulo{{font-size:14.5px;font-weight:600;color:var(--tinta)}}
  .precio{{font-size:17px;font-weight:800}}
  .card.big .precio{{font-size:21px}}
  .precio small{{font-size:10.5px;font-weight:600;color:var(--apagado)}}
  .antes{{font-size:12.5px;font-weight:500;color:var(--apagado);margin-left:5px}}
  .vieja{{font-size:11px;color:#96590A;background:#FBF0DD;border-radius:6px;
         padding:2px 6px;align-self:flex-start}}
  .ir{{color:var(--apagado);font-size:17px;flex:0 0 auto;padding-right:3px}}

  .vacio{{text-align:center;color:var(--apagado);padding:44px 0;line-height:1.6}}
  .sin-resultados{{display:none;text-align:center;color:var(--apagado);padding:32px 0}}
  footer{{text-align:center;color:#8A8177;font-size:11px;margin-top:30px;line-height:1.7}}

  @media (prefers-reduced-motion:reduce){{*{{transition:none!important}}}}
</style>
</head>
<body>
<div class="wrap">

  <header>
    <div class="marca"><span class="tag">%</span>{html.escape(nombre)}</div>
    <p class="handle">{html.escape(handle)}</p>
  </header>

  <div class="buscador">
    <svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>
    <input id="q" type="search" placeholder="Buscar una oferta que viste…"
           autocomplete="off" aria-label="Buscar entre las ofertas">
  </div>

  <div class="aviso">
    <b>Aviso:</b> esta página contiene links de afiliado. Si compras a través de
    ellos podemos recibir una comisión, sin costo adicional para ti.
    Los precios son los vigentes al momento de publicar y cambian solos:
    el precio válido es siempre el que veas en la tienda.
    Última actualización: <b>{ahora}</b>.
  </div>

  <div id="lista">
    {bloque_hoy}
    {bloque_antes}
  </div>
  <p class="sin-resultados" id="nada">No encontramos esa oferta.<br>
     Prueba con otra palabra, o quizá ya salió de la lista.</p>

  <footer>
    {html.escape(nombre)} no vende ni envía productos.<br>
    Toda compra se realiza directamente en Amazon o Mercado Libre.
  </footer>
</div>

<script>
  // Filtro en el navegador: sin servidor, sin peticiones, funciona offline.
  (function () {{
    var q = document.getElementById('q');
    var lista = document.getElementById('lista');
    var nada = document.getElementById('nada');
    if (!q || !lista) return;

    q.addEventListener('input', function () {{
      var t = q.value.trim().toLowerCase()
              .normalize('NFD').replace(/[\u0300-\u036f]/g, '');
      var cards = lista.querySelectorAll('.card');
      var visibles = 0;

      cards.forEach(function (c) {{
        var ok = !t || (c.dataset.buscar || '').indexOf(t) !== -1;
        c.style.display = ok ? '' : 'none';
        if (ok) visibles++;
      }});

      // Con búsqueda activa los encabezados estorban: se ocultan.
      lista.querySelectorAll('h2.sec').forEach(function (h) {{
        h.style.display = t ? 'none' : '';
      }});
      nada.style.display = (t && visibles === 0) ? 'block' : 'none';
    }});
  }})();
</script>
</body>
</html>"""

    DOCS.mkdir(parents=True, exist_ok=True)
    out = DOCS / "index.html"
    out.write_text(doc, encoding="utf-8")
    return out
