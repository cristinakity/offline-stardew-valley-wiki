# Runbook de production y release v1.3.0

Este procedimiento usa únicamente nombres genéricos. Sustituye los valores `<...>` en interfaces
privadas; no los escribas en Git. El despliegue de la aplicación se realiza con GitHub OIDC y el
broker, sin llaves de acceso remoto en este repositorio.

## 0. Valores que debes preparar

```text
<OWNER>                       propietario de GitHub
<REPOSITORY>                  repositorio de la wiki
<SNAPSHOT_PACKAGE>            nombre del package OCI de contenido
<UPDATER_IMAGE>               nombre del package de la imagen del updater
<PRODUCTION_APP_HOST>         hostname público del dashboard
<BROKER_HOST>                 hostname público del broker
<BROKER_OIDC_AUDIENCE>        audience configurado por el broker
<APP_ID>                      identificador del grant
<PRODUCTION_CONTAINER_NAME>   nombre genérico del contenedor
<PERSISTENT_VOLUME_NAME>      volumen nombrado para /data
<ALLOWED_GITHUB_USERS>        logins separados por coma
<OPERATOR_CONTACT>            contacto incluido en el User-Agent del crawler
```

La versión aprobada es `v1.3.0`, el snapshot es
`20260811T015121Z-7206e5e0cacc` y el archivo local esperado es:

```text
.local-data/candidates/v1.3.0/wiki-content-20260811T015121Z-7206e5e0cacc.tar.zst
```

## 1. Comprobar el candidato local

```bash
cd .local-data/candidates/v1.3.0
sha256sum --check SHA256SUMS
cd ../../..
sha256sum .local-data/candidates/v1.3.0/wiki-content-*.tar.zst
```

El SHA-256 del archivo debe ser:

```text
02e230d28581086d3bd8a1fe7925ef39d200fc2a301e999ef9d5d87d484baeb7
```

Revisa que `content-lock.json` conserve 25,852 páginas, cero enlaces rotos, cero assets requeridos
ausentes, cero recursos remotos y 30 descargas opcionales aceptadas. No uses el sample `v1.3.1`.

## 2. Publicar el snapshot público en GHCR

Instala ORAS y crea un token temporal con permiso para escribir packages. Evita incluir el token en
el comando o historial:

```bash
read -rsp 'Registry token: ' REGISTRY_TOKEN
echo
export REGISTRY_TOKEN
printf '%s' "$REGISTRY_TOKEN" | oras login ghcr.io -u '<OWNER>' --password-stdin
```

Publica una sola vez:

```bash
export SNAPSHOT_TAG='ghcr.io/<OWNER>/<SNAPSHOT_PACKAGE>:v1.3.0'
export SNAPSHOT_ARCHIVE='.local-data/candidates/v1.3.0/wiki-content-20260811T015121Z-7206e5e0cacc.tar.zst'
scripts/publish-snapshot.sh "$SNAPSHOT_ARCHIVE" "$SNAPSHOT_TAG"
export SNAPSHOT_DIGEST="$(oras resolve "$SNAPSHOT_TAG")"
export SNAPSHOT_REF="${SNAPSHOT_TAG}@${SNAPSHOT_DIGEST}"
printf '%s\n' "$SNAPSHOT_REF"
```

En GitHub abre **Packages → `<SNAPSHOT_PACKAGE>` → Package settings**:

1. Conecta el package con este repositorio.
2. Cambia su visibilidad a **Public**.
3. Concede al repositorio acceso de Actions para lectura y escritura.

Prueba una descarga anónima:

```bash
temporary="$(mktemp -d)"
oras logout ghcr.io || true
oras pull "$SNAPSHOT_REF" -o "$temporary"
downloaded_archive="$(find "$temporary" -type f -name 'wiki-content-20260811T015121Z-7206e5e0cacc.tar.zst' -print -quit)"
sha256sum "$downloaded_archive"
```

Edita `content-lock.json` y sustituye solamente:

```json
"oci_ref": "ghcr.io/<OWNER>/<SNAPSHOT_PACKAGE>:v1.3.0@sha256:<DIGEST>"
```

Ejecuta `npm run content:pull` en un clon limpio. El comando debe verificar el SHA-256 antes de
importar. Elimina el token temporal de tu cuenta y ejecuta `unset REGISTRY_TOKEN`.

## 3. Actualizar y configurar el broker

Primero libera la versión de infraestructura que admite `volume_mounts`, `resources`, timeouts y
`runtime_env`. Ejecuta sus pruebas y su workflow protegido habitual. No agregues la wiki al Compose
compartido.

En la UI administrativa privada crea un grant **Single container**:

```text
App ID: <APP_ID>
Display name: Offline Stardew Valley Wiki Updater
GitHub repository: <OWNER>/<REPOSITORY>
GitHub ref: refs/heads/master
Allowed GHCR image prefix: ghcr.io/<OWNER>/<UPDATER_IMAGE>
Domain: <PRODUCTION_APP_HOST>
Container name: <PRODUCTION_CONTAINER_NAME>
Upstream port: 8080
Health path: /api/health
Database enabled: no
Email enabled: no
Image pull timeout: 1800
Startup timeout: 1800
```

Named volume mounts JSON:

```json
[
  {
    "volume_name": "<PERSISTENT_VOLUME_NAME>",
    "mount_path": "/data",
    "read_only": false
  }
]
```

Resource limits JSON:

```json
{
  "cpus": 1.0,
  "memory": "1024m",
  "memory_swap": "1536m",
  "pids_limit": 256
}
```

Allowed runtime environment JSON:

```json
[
  "APP_ENV", "BIND_HOST", "DATA_DIR", "DATABASE_PATH", "WORKER_ENABLED",
  "BUILDER_ENABLED", "BOOTSTRAP_VALIDATION", "ENABLED", "ENABLED_LANGUAGES", "STORAGE_LIMIT_GB",
  "MIN_FREE_GB", "SNAPSHOT_RETENTION", "TIMEZONE", "HTTP_CONCURRENCY",
  "PAGE_CONCURRENCY", "USER_AGENT", "OAUTH_CLIENT_ID",
  "OAUTH_CLIENT_SECRET", "OAUTH_ALLOWED_USERS", "SESSION_SECRET"
]
```

Deja **Environment JSON** como `{}`. Los secretos llegarán de manera efímera desde el environment de
GitHub y no se almacenarán en `grants.json`.

## 4. Crear la OAuth App

En GitHub abre **Settings → Developer settings → OAuth Apps → New OAuth App**:

```text
Application name: Offline Stardew Valley Wiki Updater
Homepage URL: https://<PRODUCTION_APP_HOST>
Authorization callback URL: https://<PRODUCTION_APP_HOST>/auth/callback
```

Guarda el Client ID y genera un Client Secret. No copies el secret a archivos locales del proyecto.

## 5. Crear el environment `production`

En el repositorio abre **Settings → Environments → New environment** y crea `production`.

Configura required reviewers, restringe deployment branches a `master` y evita self-review cuando la
organización lo permita.

Variables:

```text
DEPLOY_BROKER_URL=https://<BROKER_HOST>
DEPLOY_BROKER_AUDIENCE=<BROKER_OIDC_AUDIENCE>
DEPLOY_BROKER_APP_ID=<APP_ID>
BROKER_PERSISTENT_DATA_READY=true
PRODUCTION_APP_URL=https://<PRODUCTION_APP_HOST>
APP_ENV=production
BIND_HOST=0.0.0.0
DATA_DIR=/data
DATABASE_PATH=/data/updater.sqlite3
WORKER_ENABLED=false
BUILDER_ENABLED=false
BOOTSTRAP_VALIDATION=quick
ENABLED=false
ENABLED_LANGUAGES=en,es,de,fr,it,ja,ko,hu,pt,ru,tr,zh
STORAGE_LIMIT_GB=15
MIN_FREE_GB=3
SNAPSHOT_RETENTION=3
TIMEZONE=America/Chicago
HTTP_CONCURRENCY=1
PAGE_CONCURRENCY=1
USER_AGENT=OfflineStardewValleyWiki/1.3 (<OPERATOR_CONTACT>)
OAUTH_CLIENT_ID=<OAUTH_CLIENT_ID>
OAUTH_ALLOWED_USERS=<ALLOWED_GITHUB_USERS>
```

Secrets:

```text
GHCR_READ_TOKEN=<TOKEN_WITH_READ_PACKAGES>
OAUTH_CLIENT_SECRET=<OAUTH_CLIENT_SECRET>
SESSION_SECRET=<RANDOM_SECRET_AT_LEAST_48_CHARACTERS>
```

GitHub no permite crear variables ni secretos cuyo nombre empiece con `GITHUB_`. Los nombres
`OAUTH_*` se conservan sin traducción desde GitHub Settings hasta el payload efímero del broker y el
contenedor. El grant debe permitir exactamente esos tres nombres en **Allowed runtime environment JSON**.

El broker responde `202 Accepted` con un `deployment_id`; GitHub Actions termina después de registrar
ese identificador. La extracción, validación rápida, healthcheck y sustitución del contenedor continúan
en el broker. Consulta **Deployment Broker → Deployments** hasta ver `completed` o `failed`.

Genera `SESSION_SECRET` fuera del repositorio, por ejemplo con un gestor de contraseñas. El token de
GHCR sólo necesita leer la imagen privada del updater.

## 6. Bootstrap con worker apagado

Fusiona los cambios aprobados a `master`. Abre **Actions → Deploy updater to production → Run
workflow** y escribe:

```text
DEPLOY-PRODUCTION
```

El workflow valida primero `content-lock.json`; después descarga el snapshot, verifica su checksum,
construye la imagen y la publica por commit. El stage **Deploy to production** queda entonces a la
espera del environment protegido. Antes de aprobarlo revisa el commit y los stages anteriores; al
aprobarlo, el workflow pide al broker desplegar el digest inmutable de la imagen.

Comprueba:

- `/api/health` responde `status=ok`, `environment=production` y versión esperada.
- OAuth sólo admite los usuarios configurados.
- Status muestra `Bootstrap mode / Worker disabled`.
- El snapshot activo coincide con `20260811T015121Z-7206e5e0cacc`.
- Navegación y búsqueda funcionan en los doce idiomas.
- Un reinicio conserva SQLite y el snapshot.
- El uso de almacenamiento está debajo del límite.
- Logs y auditoría no contienen secretos.

No continúes si falla cualquier comprobación.

## 7. Activar incremental y scheduler

En el environment `production` cambia:

```text
WORKER_ENABLED=true
ENABLED=false
```

Vuelve a ejecutar el deployment y lanza un incremental manual. Comprueba que utiliza el snapshot
existente y procesa sólo cambios. Después cambia `ENABLED=true` y despliega una tercera vez.

El scheduler queda configurado para incremental el domingo a las 03:00 y reconciliación full el día
1 a las 03:00, zona `America/Chicago`. `BUILDER_ENABLED` permanece siempre `false` en production.

## 8. Crear el environment `release`

Crea `release` en **Settings → Environments**, con required reviewers y rama `master`.

Variables:

```text
RELEASE_VERSION=v1.3.0
RELEASE_SNAPSHOT_REF=<THE_EXACT_OCI_REF_FROM_CONTENT_LOCK>
```

En **Settings → Actions → General** permite que `GITHUB_TOKEN` escriba contents/packages. Los
workflows restringen los permisos de cada job.

Ejecuta manualmente **Actions → Verify approved snapshot**, escribe `VERIFY-SNAPSHOT` y aprueba el
environment `release`. Esta compuerta vuelve a descargar públicamente el OCI por digest y verifica
el archivo antes de permitir que continúes con los builds.

## 9. Crear y probar el release draft

Abre **Actions → Build v1.3.0 release draft**, escribe `BUILD-RELEASE` y aprueba el environment.
Se crearán 39 paquetes Linux y 26 Windows, directamente en un draft. Los jobs no concentran todos
los binarios en un solo runner.

Descarga desde el draft y prueba:

- ZIP, DEB y RPM multilingües.
- Un paquete Linux de idioma individual.
- ZIP y Squirrel multilingües.
- Un paquete Windows de idioma individual.
- `SHA256SUMS`, `content-lock.json` y el reporte de validación.
- Uso real sin red.

Comprueba que cada asset es menor de 2 GiB y que existen exactamente 65 checksums. Publica el draft
manualmente, márcalo Latest y cierra el issue relacionado sólo después de verificar los assets
públicos.

## 10. Rollback sin acceso remoto

Conserva el digest de la imagen anterior mostrado en el summary de cada deployment y el backup de
SQLite previo. Abre **Actions → Roll back production updater**, proporciona la imagen anterior como
`ghcr.io/...@sha256:...` y escribe `ROLLBACK-PRODUCTION`.

El rollback reemplaza únicamente la imagen. No elimina ni sobrescribe `/data`. Para detener un
crawler problemático, cambia antes `WORKER_ENABLED=false` en el environment y ejecuta el rollback o
deployment protegido.
