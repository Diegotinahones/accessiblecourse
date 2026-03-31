from __future__ import annotations

import shutil
from pathlib import Path

from app.models.job import JobStatus
from app.services.imscc_parser import IMSCCParser, ParserError
from app.services.job_store import JobStore


class JobProcessor:
    def __init__(self, store: JobStore, parser: IMSCCParser | None = None) -> None:
        self.store = store
        self.parser = parser or IMSCCParser()

    def process(self, job_id: str) -> None:
        job = self.store.get_job(job_id)
        if not job.archive_path:
            self.store.update_job(
                job_id,
                status=JobStatus.ERROR.value,
                message="No se encontró el archivo IMSCC asociado al job.",
                error_detail="archive_path vacío",
            )
            return

        archive_path = Path(job.archive_path)
        job_dir = self.store.job_dir(job_id)
        extracted_dir = job_dir / "extracted"

        try:
            if extracted_dir.exists():
                shutil.rmtree(extracted_dir)
            extracted_dir.mkdir(parents=True, exist_ok=True)

            self.store.update_job(job_id, status=JobStatus.RUNNING.value, progress=10, message="Descomprimiendo paquete IMSCC…", error_detail=None)
            self.store.append_log(job_id, event="started", message="Procesamiento del job iniciado.")
            self.parser.safe_extract_archive(archive_path, extracted_dir)

            self.store.update_job(job_id, progress=30, message="Localizando imsmanifest.xml…")
            self.store.append_log(job_id, event="progress", message="Localizando imsmanifest.xml…", details={"progress": 30})
            manifest_path = self.parser.find_manifest(extracted_dir)

            self.store.update_job(job_id, progress=55, message="Parseando manifest y estructura…")
            self.store.append_log(job_id, event="progress", message="Parseando manifest y estructura…", details={"progress": 55})
            parsed_manifest = self.parser.parse_manifest(manifest_path, extracted_dir)

            self.store.update_job(job_id, progress=75, message="Resolviendo recursos internos/externos…")
            self.store.append_log(job_id, event="progress", message="Resolviendo recursos internos/externos…", details={"progress": 75})
            resources = self.parser.build_resource_inventory(parsed_manifest, manifest_path, extracted_dir)

            self.store.update_job(job_id, progress=90, message="Generando inventario…")
            self.store.append_log(job_id, event="progress", message="Generando inventario…", details={"progress": 90})
            self.store.save_resources(job_id, resources)
            self.store.save_structure(job_id, parsed_manifest.structure)

            self.store.update_job(
                job_id,
                status=JobStatus.DONE.value,
                progress=100,
                message="Inventario generado.",
                resources_count=len(resources),
                structure_available=bool(parsed_manifest.structure),
                manifest_path=manifest_path.relative_to(job_dir).as_posix(),
                error_detail=None,
            )
            self.store.append_log(job_id, event="finished", message="Inventario generado.", details={"resourceCount": len(resources)})
        except (ParserError, FileNotFoundError) as exc:
            self.store.update_job(
                job_id,
                status=JobStatus.ERROR.value,
                message="No se pudo procesar el paquete IMSCC.",
                error_detail=str(exc),
            )
            self.store.append_log(job_id, event="error", message="No se pudo procesar el paquete IMSCC.", details={"error": str(exc)})
        except Exception as exc:
            self.store.update_job(
                job_id,
                status=JobStatus.ERROR.value,
                message="Error inesperado procesando el paquete IMSCC.",
                error_detail=str(exc),
            )
            self.store.append_log(job_id, event="error", message="Error inesperado procesando el paquete IMSCC.", details={"error": str(exc)})
