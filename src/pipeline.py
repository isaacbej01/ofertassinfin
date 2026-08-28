"""Orquestador: descubre → filtra → rankea → crea → publica.

Se corre con `python -m src.pipeline` o desde scripts/run.py.
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from datetime import datetime, timedelta, timezone

from . import copywriter, linkinbio, scoring
from .config import MEDIA_DIR, QUEUE_DIR, Secrets, get
from .creative import card, story
from .models import Deal, Post
from .sources import amazon as amazon_src
from .sources import mercadolibre as ml_src
from .state import State

MX_TZ = timezone(timedelta(hours=-6))
log = logging.getLogger("ofertassinfin")


def setup_logging(verbose: bool = False):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ---------------------------------------------------------------------------
def discover() -> list[Deal]:
    deals: list[Deal] = []

    if get("fuentes.mercadolibre.activa", False):
        try:
            ml = ml_src.MercadoLibre()
            encontrados = list(ml.discover())
            log.info("MercadoLibre: %d productos revisados", len(encontrados))
            deals += encontrados
        except Exception as e:                    # noqa: BLE001
            log.error("MercadoLibre falló por completo: %s", e)

    if get("fuentes.amazon.activa", False) or amazon_src.MANUAL_FILE.exists():
        try:
            encontrados = list(amazon_src.discover())
            log.info("Amazon: %d productos revisados", len(encontrados))
            deals += encontrados
        except Exception as e:                    # noqa: BLE001
            log.error("Amazon falló por completo: %s", e)

    return deals


def build_affiliate_links(deals: list[Deal]):
    hoy = datetime.now(MX_TZ).strftime("%Y%m%d")
    for d in deals:
        try:
            if d.source == "amazon":
                d.affiliate_url = amazon_src.affiliate_url(d.source_id, sub_id=f"osf_{hoy}")
            else:
                d.affiliate_url = ml_src.affiliate_url(d, sub_id=f"osf{hoy}")
        except Exception as e:                    # noqa: BLE001
            log.warning("No se pudo generar link de afiliado para %s: %s", d.key, e)
            d.affiliate_url = d.url


def schedule_times(n: int) -> list[str]:
    """Cuándo sale cada post, en ISO 8601 UTC.

    Modo "inmediato": todo en cuanto corre el sistema, separado por 1-2 min.
    Las ofertas relámpago de ML duran unas 6 horas; programar para la noche
    una oferta encontrada en la mañana es mandar gente a un precio muerto.

    El colchón de arranque no es capricho: los creativos se suben a GitHub
    Pages DESPUÉS de programarse en Buffer, y Buffer descarga la imagen al
    publicar, no al programar. Sin ese margen, el primer post sale sin foto.
    """
    if get("cadencia.modo", "horarios") == "inmediato":
        arranque = int(get("cadencia.minutos_para_arrancar", 12))
        sep = list(get("cadencia.separacion_minutos", [1, 2])) or [1, 2]
        t = datetime.now(timezone.utc) + timedelta(minutes=arranque)
        salida = []
        for _ in range(n):
            salida.append(t.strftime("%Y-%m-%dT%H:%M:%SZ"))
            t += timedelta(minutes=random.randint(int(min(sep)), int(max(sep))))
        return salida

    base = get("cadencia.horarios", ["09:15", "13:30", "18:45", "21:20"])
    jitter = int(get("cadencia.jitter_minutos", 25))
    ahora = datetime.now(MX_TZ)
    salida = []
    dia = 0
    while len(salida) < n:
        for h in base:
            if len(salida) >= n:
                break
            hh, mm = (int(x) for x in h.split(":"))
            t = (ahora + timedelta(days=dia)).replace(
                hour=hh, minute=mm, second=0, microsecond=0
            ) + timedelta(minutes=random.randint(-jitter, jitter))
            if t <= ahora + timedelta(minutes=12):
                continue
            salida.append(t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        dia += 1
        if dia > 3:
            break
    return salida


def creativos_por_destino(deal: Deal, i: int = 0) -> dict:
    """Un creativo por destino, con la geometría correcta de cada uno.

    NO se puede usar el mismo archivo en los dos: Instagram y TikTok tapan
    zonas distintas con su interfaz. Antes esto generaba el creativo de feed
    a 1080x1920 para TikTok y el resultado perdía el precio bajo el caption.

      instagram → 1080x1350, post de feed (permanente, indexable)
      tiktok    → 1080x1920, photo post que esquiva la barra de acciones

    Las stories con sticker de link no salen por aquí: Meta prohíbe publicar
    stickers por API, así que esas se generan aparte y se suben a mano.
    """
    plantilla = story.elegir_plantilla(i)
    return {
        "instagram": str(card.render(deal, formato="instagram",
                                     plantilla=plantilla)),
        # El CTA del creativo tiene que decir la verdad de ESA red.
        "tiktok": str(story.render_offer(
            deal, plantilla=plantilla, destino="tiktok",
            cta_texto=get("copy.cta_creativo_tiktok", "COMENTA 'LINK'"))),
    }


def build_posts(deals: list[Deal]) -> list[Post]:
    tiempos = schedule_times(len(deals))
    posts = []
    for i, d in enumerate(deals):
        try:
            paths = creativos_por_destino(d, i)
        except Exception as e:                    # noqa: BLE001
            log.error("Falló el creativo de %s: %s", d.key, e)
            continue
        base = Secrets.MEDIA_BASE_URL().rstrip("/")
        urls = {}
        for fmt, p in paths.items():
            urls[fmt] = f"{base}/{p.split('/')[-1]}" if base else ""
        posts.append(Post(
            deal=d,
            image_paths=paths,
            image_urls=urls,
            caption=copywriter.caption(d, red="instagram"),
            caption_tiktok=copywriter.caption(d, red="tiktok"),
            scheduled_at=tiempos[i] if i < len(tiempos) else None,
        ))
    return posts


def publish(posts: list[Post], dry_run: bool = False) -> list[Post]:
    proveedor = get("publicacion.proveedor", "buffer")
    if dry_run or proveedor == "manual":
        for p in posts:
            p.status = "queued"
        return posts

    from .publish.buffer import Buffer, BufferError

    try:
        bf = Buffer()
    except BufferError as e:
        log.error("Buffer no configurado (%s). Todo va a la cola local.", e)
        for p in posts:
            p.status, p.error = "queued", str(e)
        return posts

    canales = {
        "instagram": Secrets.BUFFER_CHANNEL_IG(),
        "tiktok": Secrets.BUFFER_CHANNEL_TIKTOK(),
    }
    draft = get("publicacion.modo") == "borrador"

    for p in posts:
        for red, channel_id in canales.items():
            if not channel_id:
                continue
            # Sin fallback a propósito: publicar el creativo de Instagram en
            # TikTok pierde el precio detrás del caption. Mejor no publicar.
            url = p.image_urls.get(red)
            if not url:
                p.status, p.error = "failed", f"sin creativo para {red}"
                log.error("Sin creativo de %s para %s", red, p.deal.key)
                continue
            try:
                # Buffer acepta un canal por llamada, no una lista.
                bf.create_post(
                    channel_id,
                    (p.caption_tiktok if red == "tiktok" and p.caption_tiktok
                     else p.caption),
                    url,
                    due_at=p.scheduled_at, servicio=red, borrador=draft,
                    # En TikTok el título es lo que se lee bajo el video;
                    # el caption largo con hashtags va aparte.
                    titulo_tiktok=(p.deal.title[:90] if red == "tiktok" else ""),
                )
                p.status = "scheduled"
                log.info("Programado en %s: %s", red, p.deal.title[:60])
            except BufferError as e:
                p.status, p.error = "failed", str(e)
                log.error("Buffer falló (%s / %s): %s", red, p.deal.key, e)
    return posts


PENDIENTES = QUEUE_DIR / "pendientes.json"


def save_queue(posts: list[Post], pendientes: bool = False):
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    datos = json.dumps([p.to_dict() for p in posts], ensure_ascii=False, indent=2)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (QUEUE_DIR / f"{stamp}.json").write_text(datos, encoding="utf-8")
    if pendientes:
        PENDIENTES.write_text(datos, encoding="utf-8")


def cargar_pendientes() -> list[Post]:
    if not PENDIENTES.exists():
        return []
    posts = []
    for d in json.loads(PENDIENTES.read_text(encoding="utf-8")):
        posts.append(Post(
            deal=Deal.from_dict(d.get("deal") or {}),
            image_paths=d.get("image_paths") or {},
            image_urls=d.get("image_urls") or {},
            caption=d.get("caption", ""),
            caption_tiktok=d.get("caption_tiktok", ""),
            scheduled_at=d.get("scheduled_at"),
        ))
    return posts


# ---------------------------------------------------------------------------
def run(n: int | None = None, dry_run: bool = False,
        fase: str = "completa") -> dict:
    st = State()
    # Una oferta por corrida: el sistema corre varias veces al día para
    # que los posts no se canibalicen entre ellos.
    n = n or int(get("cadencia.posts_por_corrida",
                     get("cadencia.posts_por_dia", 1)))

    crudos = discover()
    nuevos = st.filter_new(crudos)
    log.info("%d productos, %d no publicados antes", len(crudos), len(nuevos))

    ya_hoy = {f: st.published_today(f) for f in ("amazon", "mercadolibre")}
    elegidos = scoring.select(nuevos, n, ya_publicados_hoy=ya_hoy)
    log.info("Seleccionados %d:", len(elegidos))
    for d in elegidos:
        log.info("  [%.3f] -%s%% $%s · %s · ~$%s comisión",
                 d.score, f"{d.discount_pct:.0f}", f"{d.price:,.0f}",
                 d.title[:52], f"{d.est_commission_mxn:,.0f}")

    if not elegidos:
        st.log_run({"encontrados": len(crudos), "publicados": 0,
                    "nota": "sin candidatos que pasen los filtros"})
        st.save()
        return {"publicados": 0, "encontrados": len(crudos)}

    build_affiliate_links(elegidos)
    posts = build_posts(elegidos)

    if fase == "generar":
        # Buffer valida la imagen EN EL MOMENTO de crear el post, no al
        # publicarlo. Si se le pasa una URL que todavía no existe en Pages,
        # rechaza con "Image could not be read from its URL". Por eso los
        # creativos se suben primero y la publicación va en una segunda
        # llamada, cuando las URLs ya responden.
        # En ensayo no se deja cola pendiente: nadie debe publicarla después.
        save_queue(posts, pendientes=not dry_run)
        log.info("FASE 1: %d creativos listos y encolados. Falta subirlos a "
                 "Pages y correr la fase de publicación.", len(posts))
        return {"publicados": 0, "encontrados": len(crudos),
                "generados": len(posts), "fase": "generar"}

    posts = publish(posts, dry_run=dry_run)
    save_queue(posts)

    if dry_run:
        # Un ensayo no deja huella. Si marcara las ofertas como publicadas,
        # cada prueba quemaría productos por 45 días sin que nadie los haya
        # visto, y el link-in-bio público mostraría ofertas que no se
        # publicaron. Los creativos sí quedan, que es lo que se quiere ver.
        log.info("ENSAYO: %d creativos generados. Nada se marcó como "
                 "publicado y no se tocó el link-in-bio.", len(posts))
        st.log_run({"encontrados": len(crudos), "candidatos": len(nuevos),
                    "publicados": 0, "dry_run": True,
                    "ensayo": [d.key for d in elegidos]})
        st.save()
        return {"publicados": 0, "encontrados": len(crudos),
                "generados": len(posts), "dry_run": True}

    feed = linkinbio.add([p.deal for p in posts if p.status in ("scheduled", "queued")])
    linkinbio.build(feed)

    ok = 0
    for p in posts:
        if p.status in ("scheduled", "queued"):
            st.mark_published(p.deal, scheduled_at=p.scheduled_at or "")
            ok += 1
    st.prune()
    st.log_run({"encontrados": len(crudos), "candidatos": len(nuevos),
                "publicados": ok, "dry_run": False})
    st.save()

    return {"publicados": ok, "encontrados": len(crudos),
            "fallidos": sum(1 for p in posts if p.status == "failed")}


def publicar_pendientes(dry_run: bool = False) -> dict:
    """FASE 2: publica en Buffer lo que la fase 1 dejó encolado.

    Para entonces los creativos ya están servidos por GitHub Pages, que es la
    única condición que Buffer exige y que la versión anterior no cumplía.
    """
    posts = cargar_pendientes()
    if not posts:
        log.info("No hay nada pendiente por publicar.")
        return {"publicados": 0, "pendientes": 0}

    st = State()
    posts = publish(posts, dry_run=dry_run)
    save_queue(posts)

    listos = [p for p in posts if p.status in ("scheduled", "queued")]
    if listos:
        linkinbio.build(linkinbio.add([p.deal for p in listos]))

    for p in listos:
        st.mark_published(p.deal, scheduled_at=p.scheduled_at or "")
    st.prune()
    st.log_run({"publicados": len(listos), "fase": "publicar",
                "fallidos": sum(1 for p in posts if p.status == "failed")})
    st.save()

    # La cola se vacía pase lo que pase: reintentar mañana una oferta de hoy
    # es publicar un precio que ya cambió.
    PENDIENTES.write_text("[]", encoding="utf-8")

    for p in posts:
        if p.status == "failed":
            log.error("No se publicó %s: %s", p.deal.key, p.error)
    return {"publicados": len(listos), "pendientes": len(posts)}


def main():
    ap = argparse.ArgumentParser(description="Ofertas Sin Fin — pipeline")
    ap.add_argument("-n", type=int, help="cuántos posts generar")
    ap.add_argument("--dry-run", action="store_true",
                    help="genera todo pero no publica en Buffer")
    ap.add_argument("--fase", choices=["completa", "generar", "publicar"],
                    default="completa",
                    help="generar: crea creativos y encola. "
                         "publicar: manda a Buffer lo encolado.")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    setup_logging(args.verbose)
    if args.fase == "publicar":
        res = publicar_pendientes(dry_run=args.dry_run)
    else:
        res = run(n=args.n, dry_run=args.dry_run, fase=args.fase)
    log.info("Resultado: %s", res)
    # La fase de generación no publica nada: salir en error sería mentir.
    if args.fase == "generar" or args.dry_run:
        return 0
    return 0 if res["publicados"] else 1


if __name__ == "__main__":
    sys.exit(main())
