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
