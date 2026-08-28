"""Cliente de la API GraphQL de Buffer.

Por qué Buffer y no las APIs oficiales: TikTok exige auditar cada aplicación
antes de dejarla publicar en público, y sin esa auditoría todo sale en modo
privado. Buffer ya está auditado. Eso es lo que se está comprando.

ESQUEMA VERIFICADO CONTRA EL SERVIDOR el 27/08/2026 por introspección, no
copiado de la documentación — que en varios puntos no coincide con lo que el
servidor realmente acepta. Lo que se corrigió respecto a la primera versión:

  * el endpoint es https://api.buffer.com, sin /graphql
  * los canales NO cuelgan de account: hay una consulta `channels(input:)`
    de primer nivel, y `account.currentOrganization` responde FORBIDDEN
  * el input se llama CreatePostInput, no PostCreateInput
  * es channelId (uno solo), no channelIds (lista): un post por canal
  * schedulingType y needsApproval son obligatorios y no estaban
  * el campo de usuario del canal es `name`, no `serviceUsername`

Límites del plan gratuito: 100 llamadas/15 min, 250/24 h, 3.000/30 días.
Cuatro ofertas al día por dos canales son ~20 llamadas. Sobra.
"""
from __future__ import annotations

import logging

import requests

from ..config import Secrets

log = logging.getLogger(__name__)

ENDPOINT = "https://api.buffer.com"

# Valores verificados por introspección del esquema
MODOS = ("addToQueue", "customScheduled", "shareNext", "shareNow")
TIPOS_INSTAGRAM = ("post", "carousel", "reel", "story")


class BufferError(RuntimeError):
    pass


class Buffer:
    def __init__(self, token: str | None = None):
        self.token = token or Secrets.BUFFER_ACCESS_TOKEN()
        if not self.token:
            raise BufferError(
                "Falta BUFFER_ACCESS_TOKEN. Se genera en Buffer → Settings → API."
            )
        self._org_id: str | None = None

    # ---------------------------------------------------------------- núcleo
    def _gql(self, query: str, variables: dict | None = None) -> dict:
        r = requests.post(
            ENDPOINT,
            headers={"Authorization": f"Bearer {self.token}",
                     "Content-Type": "application/json"},
            json={"query": query, "variables": variables or {}},
            timeout=40,
        )
        if r.status_code == 429:
            raise BufferError("Rate limit de Buffer (429). Baja la frecuencia.")
        if r.status_code != 200:
            raise BufferError(f"Buffer HTTP {r.status_code}: {r.text[:400]}")
        data = r.json()
        if data.get("errors"):
            msgs = "; ".join(e.get("message", "?") for e in data["errors"])
            raise BufferError(f"Buffer GraphQL: {msgs}")
        return data.get("data") or {}

    # ------------------------------------------------------------ organización
    def organization_id(self) -> str:
        """El id de organización es obligatorio para listar canales."""
        if self._org_id:
            return self._org_id
        data = self._gql("query { account { organizations { id name } } }")
        orgs = ((data.get("account") or {}).get("organizations") or [])
        if not orgs:
            raise BufferError("La cuenta de Buffer no tiene organizaciones.")
        self._org_id = orgs[0]["id"]
        return self._org_id

    # ----------------------------------------------------------------- canales
    def channels(self) -> list[dict]:
        data = self._gql(
            """query C($input: ChannelsInput!) {
                 channels(input: $input) {
                   id service name displayName isDisconnected isLocked type
                 }
               }""",
            {"input": {"organizationId": self.organization_id()}},
        )
        return data.get("channels") or []

    # --------------------------------------------------------------- publicar
    def create_post(self, channel_id: str, text: str, image_url: str,
                    due_at: str | None = None, servicio: str = "",
                    titulo_tiktok: str = "", tipo_instagram: str = "post",
                    borrador: bool = False) -> dict:
        """Programa UN post en UN canal.

        Buffer acepta un solo channelId por llamada, así que publicar la misma
        oferta en Instagram y TikTok son dos llamadas — y está bien, porque
        cada red lleva su propio creativo con su propia geometría.

        due_at: ISO 8601 UTC, ej. 2026-08-28T15:30:00Z. Sin él, va a la cola.
        """
        entrada = {
            "channelId": channel_id,
            "text": text,
            "assets": [{"image": {"url": image_url}}],
            "mode": "customScheduled" if due_at else "addToQueue",
            "schedulingType": "automatic",   # 'notification' avisaría al celular
            "needsApproval": False,
            "source": "ofertas-sin-fin",
        }
        if due_at:
            entrada["dueAt"] = due_at
        if borrador:
            entrada["saveToDraft"] = True

        # Cada red exige su propio bloque de metadata.
        if servicio == "instagram":
            entrada["metadata"] = {"instagram": {
                "type": tipo_instagram,        # post | carousel | reel | story
                "shouldShareToFeed": True,
            }}
        elif servicio == "tiktok":
            meta = {"isAiGenerated": False}
            if titulo_tiktok:
                meta["title"] = titulo_tiktok  # solo aplica a photo posts
            entrada["metadata"] = {"tiktok": meta}

        data = self._gql(
            """mutation Crear($input: CreatePostInput!) {
                 createPost(input: $input) {
                   __typename
                   ... on PostActionSuccess { post { id status dueAt } }
                   ... on InvalidInputError  { message }
                   ... on UnauthorizedError  { message }
                   ... on LimitReachedError  { message }
                   ... on NotFoundError      { message }
                   ... on UnexpectedError    { message }
                   ... on RestProxyError     { code message link }
                 }
               }""",
            {"input": entrada},
        )
        res = data.get("createPost") or {}
        tipo = res.get("__typename")
        if tipo != "PostActionSuccess":
            raise BufferError(
                f"Buffer rechazó el post ({tipo}): {res.get('message') or res}"
            )
        return res["post"]

    # ------------------------------------------------------------ diagnóstico
    def esquema_createPost(self) -> str:
        """Vuelve a preguntarle al servidor qué campos espera.

        Buffer ha cambiado este contrato antes y no lo documenta del todo.
        Si create_post empieza a fallar, esto dice qué cambió.
        """
        data = self._gql(
            """query { __type(name: "CreatePostInput") {
                 inputFields { name type { kind name ofType { kind name ofType { name } } } }
               } }"""
        )

        def desnudo(t):
            while t and not t.get("name"):
                t = t.get("ofType")
            return (t or {}).get("name", "?")

        campos = ((data.get("__type") or {}).get("inputFields") or [])
        return "\n".join(
            f"  {c['name']}: {desnudo(c['type'])}"
            f"{'  (obligatorio)' if c['type'].get('kind') == 'NON_NULL' else ''}"
            for c in campos
        ) or "(el servidor no expuso el tipo)"
