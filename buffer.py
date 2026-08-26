"""Cliente de la API de Buffer (GraphQL).

Por qué Buffer y no la API oficial de TikTok: TikTok exige una auditoría
de tu app y, sin ella, TODO lo que publiques queda en modo privado
(SELF_ONLY). Buffer ya está auditado. Eso es lo que estás comprando por
~10 USD/mes.

Límites por API key (plan Essentials): 100 req/15min, 250/24h, 7,500/30d.
Con 4 posts/día x 2 redes vamos sobradísimos.

IMPORTANTE: Buffer NO sube archivos. Descarga la imagen desde la URL
pública EN EL MOMENTO DE PUBLICAR, no al programar. La URL tiene que
seguir viva hasta entonces — por eso las imágenes viven en GitHub Pages.
"""
from __future__ import annotations

import logging
from typing import Iterable

import requests

from ..config import Secrets

log = logging.getLogger(__name__)

ENDPOINT = "https://api.buffer.com/graphql"


class BufferError(RuntimeError):
    pass


class Buffer:
    def __init__(self, token: str | None = None):
        self.token = token or Secrets.BUFFER_ACCESS_TOKEN()
        if not self.token:
            raise BufferError(
                "Falta BUFFER_ACCESS_TOKEN. Se genera en Buffer → Settings → "
                "Developers → Create API key."
            )

    def _gql(self, query: str, variables: dict) -> dict:
        r = requests.post(
            ENDPOINT,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            json={"query": query, "variables": variables},
            timeout=40,
        )
        if r.status_code == 429:
            raise BufferError("Rate limit de Buffer (429).")
        if r.status_code != 200:
            raise BufferError(f"Buffer {r.status_code}: {r.text[:400]}")
        data = r.json()
        if data.get("errors"):
            raise BufferError(f"Buffer GraphQL error: {data['errors']}")
        return data.get("data", {})

    # ------------------------------------------------------------- canales
    def channels(self) -> list[dict]:
        q = """
        query { account { currentOrganization { channels {
            id service serviceUsername
        } } } }
        """
        data = self._gql(q, {})
        return (((data.get("account") or {}).get("currentOrganization") or {})
                .get("channels") or [])

    # ------------------------------------------------------------ publicar
    def create_post(self, channel_ids: Iterable[str], text: str,
                    image_urls: Iterable[str], due_at: str | None = None,
                    draft: bool = False) -> dict:
        """due_at: ISO 8601 UTC, ej. 2026-08-27T15:30:00Z"""
        q = """
        mutation CreatePost($input: PostCreateInput!) {
          createPost(input: $input) {
            __typename
            ... on PostCreateSuccess { post { id status dueAt } }
            ... on ValidationError { message }
            ... on UnauthorizedError { message }
          }
        }
        """
        assets = [{"image": {"url": u}} for u in image_urls if u]
        variables = {
            "input": {
                "channelIds": list(channel_ids),
                "text": text,
                "assets": assets,
                "mode": "draft" if draft else ("customScheduled" if due_at else "addToQueue"),
            }
        }
        if due_at and not draft:
            variables["input"]["dueAt"] = due_at

        data = self._gql(q, variables)
        res = data.get("createPost") or {}
        if res.get("__typename") not in ("PostCreateSuccess",):
            raise BufferError(f"Buffer rechazó el post: {res}")
        return res["post"]
