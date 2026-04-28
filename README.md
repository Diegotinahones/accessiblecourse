# AccessibleCourse

Aplicación full-stack para subir paquetes `.imscc/.zip`, extraer recursos, revisar un checklist de accesibilidad y generar informes descargables en PDF y DOCX.

## Arranque rápido con Docker

```bash
cp .env.example .env
docker compose up --build
```

Servicios:

- Frontend: `http://localhost:8080`
- Backend API: `http://localhost:8000`
- Health: `http://localhost:8000/api/health`
- Docs OpenAPI: `http://localhost:8000/docs`

La persistencia queda en `./data`:

- `data/jobs/<job_id>/upload`
- `data/jobs/<job_id>/extracted`
- `data/jobs/<job_id>/reports`
- `data/jobs/<job_id>/job.log`

`docker-compose.yml` monta `./data:/app/data`, para que uploads, extraidos e informes no se pierdan al recrear contenedores y haya espacio fuera de la capa efimera de la imagen.

## Desarrollo local sin Docker

Backend:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
```

Frontend:

```bash
npm install
npm run dev
```

## Variables de entorno

Ejemplo en [`.env.example`](/Users/diegolopez/Documents/Proyectos/Accesible%20Course/.env.example).

Variables principales:

- `CORS_ORIGINS`
- `MAX_UPLOAD_MB`
- `DATABASE_URL`
- `STORAGE_ROOT`
- `LOG_LEVEL`
- `REPORT_BRAND_NAME`

Variables para validar Canvas API:

- `CANVAS_BASE_URL`, por ejemplo `https://aula.uoc.edu`
- `CANVAS_API_PREFIX`, por ejemplo `/api/v1`
- `CANVAS_TOKEN`, token secreto de Canvas
- `CANVAS_PER_PAGE`, por ejemplo `100`
- `CANVAS_TIMEOUT_SECONDS`, por ejemplo `20`

## Validar token Canvas

Con el backend levantado y las variables `CANVAS_*` configuradas:

```bash
curl -sS http://localhost:8000/api/canvas/health
curl -sS http://localhost:8000/api/canvas/profile | head
curl -sS http://localhost:8000/api/canvas/courses | head
```

## Subidas IMSCC grandes

La configuracion por defecto queda alineada para aceptar paquetes de hasta 13 GB:

- Nginx: `client_max_body_size 13g;` en [`nginx.conf`](/Users/diegolopez/Documents/Proyectos/Accesible%20Course/nginx.conf)
- Backend FastAPI: `MAX_UPLOAD_MB=13000` en [`.env.example`](/Users/diegolopez/Documents/Proyectos/Accesible%20Course/.env.example)

Si necesitas subir mas de 13 GB, cambia ambos limites y vuelve a levantar la pila:

```bash
docker compose up --build
```

Puntos a revisar:

- `nginx.conf`: sube `client_max_body_size`
- `.env`: sube `MAX_UPLOAD_MB`
- Si ya existia un `.env`, actualizalo tambien: Compose prioriza ese valor frente al default del `docker-compose.yml`
- Reinicia los contenedores para que ambos cambios entren en vigor

Si el backend detecta que el archivo supera `MAX_UPLOAD_MB`, responde con `413` y un JSON con `code=UPLOAD_TOO_LARGE`, `message`, `maxMB` y `actualMB`.

Para desarrollo conviene usar un IMSCC pequeno o una muestra reducida, porque un paquete de varios gigas hace mas lenta la iteracion local y ocupa mucho espacio en `./data`.

## Flujo API con curl

Subir curso:

```bash
curl -X POST http://localhost:8000/api/jobs \
  -F "file=@./curso.imscc"
```

Consultar estado:

```bash
curl http://localhost:8000/api/jobs/<job_id>
```

Listar recursos cuando el job termine:

```bash
curl http://localhost:8000/api/jobs/<job_id>/resources
```

Guardar checklist de un recurso:

```bash
curl -X PUT http://localhost:8000/api/jobs/<job_id>/checklist/<resource_id> \
  -H "Content-Type: application/json" \
  -d '{"items":{"structure":"fail","ocr":"pass"}}'
```

Generar informe:

```bash
curl -X POST http://localhost:8000/api/reports/<job_id>
```

Descargar PDF y DOCX:

```bash
curl -L http://localhost:8000/api/reports/<job_id>/download/pdf --output report.pdf
curl -L http://localhost:8000/api/reports/<job_id>/download/docx --output report.docx
```

## Calidad

Backend:

```bash
ruff check app tests
pytest
```

Frontend:

```bash
npm run lint
npm run build
```

Generar `openapi.json`:

```bash
python -m app.export_openapi
```

## Deploy recomendado: VPS con Docker Compose

1. Instala Docker y Docker Compose Plugin en el VPS.
2. Clona el repositorio en el servidor.
3. Copia el entorno:

```bash
cp .env.example .env
```

4. Ajusta en `.env` al menos:

- `CORS_ORIGINS` con tu dominio final
- `DATABASE_URL` si vas a usar Postgres en vez de SQLite
- `STORAGE_ROOT=/app/data`
- `LOG_LEVEL=INFO`

5. Levanta la aplicación:

```bash
docker compose up -d --build
```

6. Comprueba salud:

```bash
curl http://localhost:8000/api/health
```

7. Expón `8080` detrás de tu proxy/reverse proxy o cambia el mapeo de puertos si quieres publicar en `80/443`.

### Postgres opcional

El `docker-compose.yml` incluye un servicio `db` bajo el perfil `postgres`. Para usarlo:

```bash
docker compose --profile postgres up -d --build
```

Y define `DATABASE_URL` apuntando a `postgresql+psycopg://accessiblecourse:accessiblecourse@db:5432/accessiblecourse`.
