# Setup — estado y pasos

Actualizado: 26 de agosto de 2026.
Esta etapa es de **validación**: el objetivo es que el circuito completo cierre
de punta a punta, no que rinda. La optimización de formato viene después.

Leyenda: ✅ hecho · 🔓 puedes hacerlo ya · ⏳ bloqueado por algo externo

---

## ✅ PASO 1 — Instagram a cuenta profesional

Hecho. Cuenta Creator.

Datos que dejó: **20 seguidores**, 3 vistas en la story de reactivación y
2 en la de oferta. Instagram no está dormido, está vacío. Se publica ahí
porque no cuesta nada, pero la audiencia real hay que construirla en TikTok.

**TikTok se queda como cuenta personal a propósito.** Buffer publica sin
necesitar Business, y pasar a Business no daría link en bio (eso requiere
verificación de negocio) pero sí quitaría la música de tendencia. Mal trato.
Se revisa al llegar a 1,000 seguidores — faltan 155.

---

## ⏳ PASO 2 — Afiliado de Mercado Libre

En proceso. Bloqueado porque tu conocido necesita su **Constancia de
Situación Fiscal** del SAT.

Vías para sacarla (todas gratis, ninguna requiere cita):

| Vía | Requiere | Tarda |
|---|---|---|
| Portal sat.gob.mx | RFC + contraseña o e.firma | inmediato, 24/7 |
| App SAT Móvil | RFC + contraseña | inmediato |
| App SAT ID | RFC, correo, teléfono, video de identidad | ~5 días hábiles |
| Chat del SAT (chat.sat.gob.mx) | — | L-V 9:00-18:00 |
| Oficina o módulo móvil | Identificación oficial | mismo día |

Si ya tiene contraseña del SAT, es cosa de minutos. Si no, la app SAT ID
la genera sin ir a ninguna oficina.

Cuando esté dentro del programa, hace falta:
1. Generar un link de prueba en el panel y pasar la URL completa.
2. **Comprar con ese link desde otra cuenta** y confirmar que la comisión
   se registra. ML no tiene API oficial de afiliados: el sistema inyecta
   los parámetros `matt_*` y no hay forma de saber si funciona sin probarlo
   con dinero real.
3. Revisar en los T&C (mercadolibre.com.mx/ayuda/30228) si prohíben
   contenido generado automáticamente, y anotar la tabla de comisiones y la
   ventana de atribución vigentes en México.

**El sistema corre sin esto.** Publica con links normales; simplemente no
cobra. No bloquea los pasos 3, 4 ni 5.

---

## 🔓 PASO 3 — Repositorio y GitHub Pages

Aquí nace el hosting de las imágenes y la página de link-in-bio. Sin esto,
Buffer no tiene de dónde descargar los creativos.

1. Crear cuenta en github.com si no tienes.
2. Nuevo repositorio **público** llamado `ofertassinfin`.
   - Público, no privado: Actions es ilimitado en repos públicos (en privados
     son 2,000 min/mes) y Pages da hosting gratis. No hay secretos en el
     código — todos van en GitHub Secrets, que es otra cosa.
3. Subir el contenido de la carpeta `ofertas-sin-fin`.
4. Settings → Pages → Source: **Deploy from a branch** → rama `main`,
   carpeta `/docs` → Save.
5. Esperar 1-2 minutos y abrir `https://TU_USUARIO.github.io/ofertassinfin/`.
   Debe verse la página con el aviso de "Todavía no hay ofertas publicadas".

Tu `MEDIA_BASE_URL` queda como
`https://TU_USUARIO.github.io/ofertassinfin/media`.

---

## 🔓 PASO 4 — Buffer y la app de Mercado Libre

**Buffer**
1. Cuenta en buffer.com, conectar **Instagram** (por Instagram Login, sin
   Página de Facebook) y **TikTok**.
2. Plan Free para validar; Essentials (~$5 USD por canal) cuando el tope de
   10 posts en cola estorbe.
3. Settings → Developers → **Create API key**.
4. `python scripts/doctor.py` imprime los IDs de tus canales.

**App de Mercado Libre** (para descubrir ofertas, no para afiliados)
1. developers.mercadolibre.com.mx/devcenter → crear app.
2. Redirect URI **debe** ser https (sirve `https://localhost:8443/cb`).
3. `python scripts/ml_oauth.py` una vez. Guarda el `ML_REFRESH_TOKEN`.

**Secretos en GitHub**: Settings → Secrets and variables → Actions.
Los nombres están en `.env.example`.

---

## 🔓 PASO 5 — Primera corrida

```bash
python scripts/doctor.py             # qué está conectado y qué no
python -m src.pipeline --dry-run -v  # genera sin publicar
```

Revisa `data/queue/*.json` y `docs/index.html`. Si convence:

```bash
python -m src.pipeline
```

Entra a Buffer y revisa la cola **antes** de que salga el primer post.
Luego: Actions → *Publicar ofertas* → Run workflow, y de ahí corre solo.

Arranca en 2 posts al día. Sube a 4 en dos semanas.

---

## Después de validar

Cuando el circuito cierre solo, el trabajo cambia de "que funcione" a
"que lo vean". El primer post de TikTok sacó **30 vistas con 845 seguidores**
— 3.5%, o sea que TikTok casi no lo distribuyó. Eso no se arregla con más
automatización.

Lo primero a probar entonces: publicar el mismo creativo desde la app
eligiendo **sonido de tendencia**, y comparar contra el automático sin
sonido. Buffer no puede adjuntar audio por API, así que si el sonido resulta
determinante, TikTok pasa a modo notificación y solo Instagram queda 100%
automático.
