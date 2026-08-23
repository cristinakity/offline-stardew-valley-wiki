# Pendientes antes de desplegar y liberar una versión

Última revisión: 2026-08-11.

Este documento es la compuerta de salida para production y GitHub Releases. Ningún despliegue ni
release debe considerarse aprobado mientras quede pendiente un elemento marcado como **bloqueante**.

Convenciones:

- `[x]`: terminado y comprobado.
- `[ ]`: pendiente.
- `<VERSION>`: próxima versión real, por ejemplo `v2.0.0`.
- `<SNAPSHOT_REF>`: referencia GHCR inmutable terminada en `@sha256:...`.

## Estado local conocido

- [x] El run `#16` recuperó el full y terminó como `completed_with_warnings`.
- [x] El snapshot full recuperado es `20260811T015121Z-7206e5e0cacc`.
- [x] El candidato full local original `v1.3.0`, reutilizado para `v2.0.0`, contiene un `.tar.zst` de aproximadamente 643 MiB.
- [x] El build Linux `#1` terminó las 13 ediciones y produjo 40 archivos (ZIP, DEB, RPM y
  `SHA256SUMS`).
- [x] Los 30 assets opcionales se aceptaron y documentaron como advertencia conocida del snapshot usado por `v2.0.0`.
- [x] El snapshot conserva cero enlaces rotos, assets requeridos ausentes y recursos remotos.
- [x] El candidato `v1.3.1` de aproximadamente 11.8 MiB es un `sample` de 25 páginas por idioma;
  no debe utilizarse como release ni como seed inicial de production.
- [ ] Eliminar o renombrar los candidatos de prueba y duplicados cuando ya no sean necesarios.
- [ ] Purgar builds y workspaces locales obsoletos después de conservar los artefactos aprobados.

## 1. Bloqueadores de código y arquitectura

- [x] Agregar `WORKER_ENABLED=false` para iniciar production sólo con dashboard e
  importador, sin proceso crawler.
- [x] Rechazar desde la API los botones de `sample`, `incremental`, `full` y recovery
  mientras `WORKER_ENABLED=false`.
- [x] Mostrar claramente `Bootstrap mode / Worker disabled` en Status.
- [x] Permitir activar el worker únicamente mediante configuración de production y un redeploy/restart
  controlado por el broker.
- [x] Impedir que crawler y builder reclamen trabajos pesados simultáneamente.
- [x] Dejar `builder-worker` deshabilitado por defecto en production.
- [x] El broker admite límites reales de CPU, memoria, swap y PIDs compatibles con Podman; no depende
  de campos de Compose que el proveedor pudiera ignorar.
- [x] Configuración inicial conservadora para el contenedor único de production:
  - máximo de 1024 MiB, 1536 MiB con swap, 1 CPU y 256 PIDs;
  - `HTTP_CONCURRENCY=1`;
  - `PAGE_CONCURRENCY=1`;
  - builder deshabilitado;
  - swap disponible y monitorizada.
- [ ] Probar reinicio abrupto de dashboard y worker sin perder snapshot, jobs, candidatos ni auditoría.
- [ ] Confirmar que sólo un crawler y un build job pueden reclamar el mismo tipo de trabajo.
- [ ] Confirmar pausa, continuación, cancelación y recovery después de reiniciar contenedores.

## 2. Limpieza y seguridad del repositorio

- [ ] **Bloqueante:** revisar `git status` y separar cambios de aplicación, crawler, workflows y
  documentación en commits entendibles.
- [ ] El mirror antiguo y sus JSON ya se eliminaron del working tree; incluir esas eliminaciones en
  un commit normal, sin reescribir historial.
- [x] Confirmar que `.local-data`, snapshots, builds, candidatos, secretos y `.env.production` siguen
  ignorados por Git.
- [x] Ignorar `.tar.zst`, ZIP, DEB, RPM, EXE y contenido completo futuro de la wiki.
- [ ] Confirmar que no existan nombres de proveedores, direcciones de servidores, usuarios del host,
  llaves SSH, tokens ni información personal de infraestructura en código o documentación.
- [ ] Ejecutar un escaneo de secretos antes de publicar la rama.
- [x] Mantener intactos commits, issues, tags y releases históricos:
  - `v1.0.0-beta.1`;
  - `v1.0.0`;
  - `v1.1.0`;
  - `v1.2.0`.
- [x] Confirmar que un checkout de CI utiliza `fetch-depth: 1` cuando no necesita tags o historial.
- [x] Mantener código, pruebas, configuración y el lock del contenido en Git; distribuir binarios en
  Releases y snapshots en GHCR.

## 3. Validación del snapshot full final

- [x] Se seleccionó el candidato full `#7`, snapshot `20260811T015121Z-7206e5e0cacc`, para `v2.0.0`.
- [x] No utilizar candidatos `fixture` o `sample` como seed o release.
- [x] Ejecutar `sha256sum --check SHA256SUMS` dentro del candidato.
- [x] Confirmar que `content-lock.json`, `validation-report.json` y el manifiesto apuntan al mismo
  snapshot, versión y digest.
- [x] Confirmar 25,852/25,852 páginas o justificar cualquier diferencia respecto a MediaWiki.
- [x] Cero enlaces internos rotos.
- [x] Cero assets requeridos ausentes.
- [x] Cero recursos remotos necesarios durante el uso offline.
- [ ] Clasificar cada error de descarga como requerido u opcional y conservar su URL, idioma, error e
  intento final en el reporte.
- [ ] Probar automáticamente una muestra de páginas en los 12 idiomas.
- [ ] Confirmar búsqueda en los 12 índices y excluir resultados cuya página local no exista.
- [ ] Confirmar navegación desde portada, páginas internas, categorías y resultados de búsqueda.
- [ ] Confirmar traducción de la misma página entre idiomas mediante el índice rápido de traducciones.
- [ ] Confirmar back, forward, página e idioma recordados entre reinicios.
- [ ] Confirmar apertura local ampliada de imágenes disponibles.
- [ ] Confirmar mensajes traducidos para páginas especiales no offline y páginas todavía no incluidas.
- [ ] Ejecutar la regresión del issue `#5` en español, chino y japonés.
- [ ] Ejecutar Electron con la red deshabilitada y verificar que no intente cargar recursos externos.
- [ ] Verificar CSP, aislamiento del renderer, navegación externa y bloqueo de acceso Node.
- [ ] Revisar atribución, licencia y avisos requeridos por el contenido de la wiki.

## 4. Publicar el snapshot inicial en GHCR

- [ ] **Bloqueante:** instalar y probar ORAS en la máquina desde la que se publicará el candidato.
- [ ] Autenticarse en GHCR sin guardar el token en archivos o historial de shell.
- [ ] Publicar el `.tar.zst` full con un tag que nunca se reutilice:

  ```bash
  scripts/publish-snapshot.sh \
    ".local-data/candidates/<VERSION>/wiki-content-<SNAPSHOT>.tar.zst" \
    "ghcr.io/<OWNER>/offline-stardew-valley-wiki-snapshot:<VERSION>"
  ```

- [ ] Resolver el tag y guardar la referencia inmutable:

  ```bash
  SNAPSHOT_DIGEST="$(oras resolve "ghcr.io/<OWNER>/offline-stardew-valley-wiki-snapshot:<VERSION>")"
  SNAPSHOT_REF="ghcr.io/<OWNER>/offline-stardew-valley-wiki-snapshot:<VERSION>@${SNAPSHOT_DIGEST}"
  ```

- [ ] Verificar que `<SNAPSHOT_REF>` termina en `@sha256:` y que `oras pull` recupera el archivo
  correcto en un directorio temporal limpio.
- [ ] Conectar el paquete GHCR con el repositorio y conceder lectura al `GITHUB_TOKEN` de Actions, o
  configurar la visibilidad apropiada.
- [ ] Agregar al repositorio un `content-lock.json` pequeño con versión, snapshot ID, digest y
  `<SNAPSHOT_REF>`.
- [x] Agregar `npm run content:pull` para leer el lock, descargar, verificar e importar el
  snapshot para quien clone el código.

## 5. Bootstrap inicial de production mediante el broker

- [x] El contrato del broker permite exclusivamente volúmenes Podman nombrados y el runbook fija `/data`.
- [ ] Confirmar que el volumen inicial está vacío o respaldar y documentar cualquier contenido previo.
- [ ] Configurar el grant sin direcciones, usuarios ni credenciales del host dentro del repositorio.
- [ ] Configurar OAuth, allowlist, secreto de sesión y dominio mediante variables/secretos externos.
- [ ] Configurar inicialmente:

  ```text
  WORKER_ENABLED=false
  BOOTSTRAP_VALIDATION=quick
  ENABLED=false
  STORAGE_LIMIT_GB=15
  MIN_FREE_GB=3
  SNAPSHOT_RETENTION=3
  HTTP_CONCURRENCY=1
  PAGE_CONCURRENCY=1
  ```

- [x] El broker admite timeouts configurables de pull y arranque de hasta 3600 segundos para validar el seed sin
  que el broker reinicie el contenedor prematuramente.
- [ ] Ejecutar manualmente `Deploy updater to production` con environment protegido, confirmación y
  `<SNAPSHOT_REF>` inmutable.
- [ ] Confirmar que Actions descarga el snapshot, construye una imagen por commit SHA y solicita el
  despliegue al broker mediante OIDC; no usar SSH.
- [ ] Confirmar que el contenedor importa el seed solamente cuando `/data/current.json` no existe.
- [ ] Confirmar que un redeploy conserva el volumen y no reemplaza silenciosamente el snapshot activo.
- [ ] Confirmar dashboard accesible únicamente detrás del proxy y sin puertos públicos directos.
- [ ] Mantener el scheduler deshabilitado durante toda la revisión inicial.

## 6. Aprobación del snapshot en production

- [ ] El healthcheck reporta versión y environment correctos.
- [ ] Status muestra el snapshot ID esperado y `Worker disabled`.
- [ ] El run `snapshot_import` terminó correctamente.
- [ ] La validación importada conserva cero enlaces rotos, assets requeridos ausentes y recursos
  remotos.
- [ ] Navegación y búsqueda funcionan en los 12 idiomas usando el snapshot del volumen.
- [ ] Reiniciar el contenedor y confirmar que el snapshot permanece disponible.
- [ ] Confirmar uso de disco real y reserva libre antes de activar el crawler.
- [ ] Confirmar backup y restauración de SQLite.
- [ ] Confirmar logs y auditoría sin tokens, cookies ni secretos.
- [ ] Obtener aprobación humana explícita del bootstrap.
- [ ] Después de aprobar, cambiar `WORKER_ENABLED=true` y `ENABLED=true` y hacer un redeploy/restart
  mediante el broker.
- [ ] Ejecutar primero un incremental manual y confirmar que procesa cambios en vez de repetir el full.
- [ ] Activar después el calendario semanal y mensual.

## 7. GitHub Actions para builds de release

- [x] Refactorizar `build-candidate.yml` para no descargar todos los artefactos en un
  job agregador; los Linux actuales ocupan aproximadamente 17 GiB.
- [x] Crear primero un GitHub Release draft vacío.
- [x] Configurar matrices separadas para:
  - Linux: multilingüe y cada uno de los 12 idiomas;
  - Windows: multilingüe y cada uno de los 12 idiomas.
- [x] Cada job descarga exactamente `<SNAPSHOT_REF>@sha256`, nunca un tag mutable ni
  `current.json`.
- [x] Cada job construye una sola edición para limitar disco y memoria del runner.
- [x] Cada job sube sus paquetes directamente al draft, sin conservarlos como artifacts grandes
  de Actions.
- [x] Usar nombres únicos que incluyan versión, plataforma y edición.
- [x] Generar checksums por job y consolidar `SHA256SUMS` sin descargar todos los binarios nuevamente.
- [x] Verificar que cada archivo sea menor de 2 GiB antes de intentar subirlo a Releases.
- [ ] Confirmar que ningún job sobrescribe assets existentes y que un rerun es seguro.
- [ ] Confirmar que Linux produce ZIP, DEB y RPM.
- [ ] Confirmar que Windows produce ZIP y `squirrel.windows.zip` por edición acordada.
- [ ] Reconstruir al menos una edición Linux en Actions y compararla con el candidato local.
- [ ] Probar instalaciones reales de ZIP, DEB, RPM, Windows ZIP y Squirrel antes de publicar.

## 8. Versión, tag y notas automáticas

- [x] La versión seleccionada es `v2.0.0`; `package.json`, lock y reporte son coherentes, reutilizando el snapshot inmutable aprobado.
- [x] Crear `.github/release.yml` con categorías para features, fixes, documentación, dependencias y
  otros cambios.
- [x] Crear una plantilla de introducción para el release con descripción, características y pasos de
  instalación.
- [ ] Crear el draft con `--generate-notes` para incluir automáticamente:
  - `What's Changed`;
  - pull requests;
  - contributors;
  - enlace `Full Changelog` desde el tag anterior.
- [ ] Asociar el release al commit aprobado y verificar el tag antes de publicar.
- [ ] No mover, reemplazar ni reutilizar un tag publicado.
- [ ] Mostrar el digest del snapshot y commit de aplicación en las notas del release.
- [ ] Adjuntar `content-lock.json`, `SHA256SUMS` y reporte de validación junto con los instaladores.
- [x] Dejar el release como draft después de compilar; nunca publicarlo automáticamente por push.
- [ ] Descargar desde GitHub y probar los paquetes finales, no sólo las copias locales.
- [ ] Obtener una segunda aprobación humana explícita para el release draft.
- [ ] Publicar manualmente el draft y marcarlo como `Latest` sólo después de aprobarlo.
- [ ] Confirmar que GitHub genera automáticamente los archivos Source code del tag.
- [ ] Cerrar el issue `#5` únicamente después de que el release público contenga la corrección.

## 9. Operación posterior y rollback

- [ ] Scheduler incremental: domingo a las 03:00, zona `America/Chicago`.
- [ ] Reconciliación full: día 1 a las 03:00, sin coincidir con builds.
- [ ] Poder pausar globalmente scheduler e idiomas desde el dashboard.
- [ ] No generar automáticamente un release nuevo cada semana; acumular cambios y crear candidato con
  la periodicidad aprobada.
- [ ] Definir alertas por run fallido, almacenamiento, backup, import y build.
- [ ] Probar retención de snapshots y candidatos sin eliminar la fuente de un release publicado.
- [ ] Conservar referencia a la imagen anterior, snapshot anterior y backup SQLite antes de cada
  despliegue.
- [x] Documentar rollback mediante broker sin acceso directo al host.
- [ ] Verificar que rollback de aplicación no revierta ni corrompa automáticamente el volumen de datos.

## Compuertas finales

### Aprobación 1: candidato local

- [ ] Snapshot full aprobado.
- [ ] Aplicación offline aprobada en los 12 idiomas.
- [ ] Paquetes Linux locales aprobados.

### Aprobación 2: bootstrap production

- [ ] Snapshot importado con worker deshabilitado.
- [ ] Persistencia, seguridad, recursos y backups aprobados.
- [ ] Worker habilitado solamente después de la aprobación.

### Aprobación 3: GitHub Release draft

- [ ] Builds Linux y Windows aprobados.
- [ ] Tag, commit, snapshot digest, checksums y notas verificados.
- [ ] Publicación manual autorizada.

Referencias del proyecto:

- [Pruebas locales](docs/local-testing.md)
- [Arquitectura](docs/architecture.md)
- [Despliegue de production](docs/production-deployment.md)
- [Migración del repositorio](docs/repository-migration.md)
