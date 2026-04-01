from __future__ import annotations

import logging
import re
import shutil
import stat
from pathlib import Path, PurePosixPath
from zipfile import ZipFile, is_zipfile

from fastapi import UploadFile, status

from app.core.config import Settings
from app.core.errors import AppError

ALLOWED_EXTENSIONS = {'.imscc', '.zip'}
SAFE_NAME_RE = re.compile(r'[^A-Za-z0-9._-]+')
SAFE_JOB_ID_RE = re.compile(r'^[A-Fa-f0-9-]{36}$')
logger = logging.getLogger('accessiblecourse.upload')


def ensure_storage_layout(settings: Settings) -> None:
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    (settings.storage_root / 'jobs').mkdir(parents=True, exist_ok=True)


def sanitize_filename(filename: str) -> str:
    name = Path(filename).name.strip() or 'upload.zip'
    suffix = Path(name).suffix.lower()
    stem = SAFE_NAME_RE.sub('-', Path(name).stem).strip('-._') or 'upload'
    return f'{stem}{suffix}'


def validate_extension(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise AppError(
            code='invalid_extension',
            message='Solo se admiten ficheros .imscc o .zip.',
            details={'allowedExtensions': sorted(ALLOWED_EXTENSIONS)},
        )
    return suffix


def validate_job_id(job_id: str) -> str:
    if not SAFE_JOB_ID_RE.fullmatch(job_id):
        raise AppError(code='invalid_job_id', message='El identificador del analisis no es valido.')
    return job_id


def get_job_dir(settings: Settings, job_id: str) -> Path:
    validate_job_id(job_id)
    return settings.storage_root / 'jobs' / job_id


def get_upload_path(settings: Settings, job_id: str, original_filename: str) -> Path:
    return get_job_dir(settings, job_id) / 'upload' / sanitize_filename(original_filename)


def get_extracted_dir(settings: Settings, job_id: str) -> Path:
    return get_job_dir(settings, job_id) / 'extracted'


def get_reports_dir(settings: Settings, job_id: str) -> Path:
    return settings.storage_root / 'jobs' / job_id / 'report'


def get_job_log_path(settings: Settings, job_id: str) -> Path:
    return get_job_dir(settings, job_id) / 'job.log'


def _bytes_to_mb(size_bytes: int) -> float | int:
    value = round(size_bytes / (1024 * 1024), 3)
    return int(value) if value.is_integer() else value


async def save_upload_file(
    *,
    upload: UploadFile,
    destination: Path,
    max_size_bytes: int,
    job_id: str | None = None,
) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    total_size = 0

    try:
        with destination.open('wb') as output:
            while chunk := await upload.read(1024 * 1024):
                total_size += len(chunk)
                if total_size > max_size_bytes:
                    logger.warning(
                        'upload_rejected_too_large',
                        extra={
                            'event': 'upload_rejected_too_large',
                            'job_id': job_id,
                            'details': {
                                'filename': sanitize_filename(upload.filename or destination.name),
                                'actualBytes': total_size,
                                'actualMB': _bytes_to_mb(total_size),
                                'maxBytes': max_size_bytes,
                                'maxMB': _bytes_to_mb(max_size_bytes),
                            },
                        },
                    )
                    raise AppError(
                        code='UPLOAD_TOO_LARGE',
                        message='El archivo supera el l\u00edmite configurado',
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        details={
                            'maxMB': _bytes_to_mb(max_size_bytes),
                            'actualMB': _bytes_to_mb(total_size),
                        },
                        job_id=job_id,
                    )
                output.write(chunk)
    except AppError:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()

    if not is_zipfile(destination):
        destination.unlink(missing_ok=True)
        raise AppError(code='invalid_archive', message='El fichero subido no es un paquete ZIP/IMSCC valido.')

    logger.info(
        'upload_received',
        extra={
            'event': 'upload_received',
            'job_id': job_id,
            'details': {
                'filename': sanitize_filename(upload.filename or destination.name),
                'actualBytes': total_size,
                'actualMB': _bytes_to_mb(total_size),
                'maxBytes': max_size_bytes,
                'maxMB': _bytes_to_mb(max_size_bytes),
            },
        },
    )
    return total_size


def validate_member_path(base_dir: Path, member_name: str) -> Path:
    normalized = PurePosixPath(member_name)
    if normalized.is_absolute() or any(part == '..' for part in normalized.parts):
        raise AppError(
            code='unsafe_archive_path',
            message='El paquete contiene rutas no permitidas.',
            details={'path': member_name},
        )

    target_path = (base_dir / Path(*normalized.parts)).resolve()
    if not str(target_path).startswith(str(base_dir.resolve())):
        raise AppError(
            code='unsafe_archive_path',
            message='El paquete contiene rutas fuera del directorio permitido.',
            details={'path': member_name},
        )
    return target_path


def extract_archive(*, source: Path, destination: Path, settings: Settings) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    extracted_paths: list[Path] = []
    total_uncompressed_size = 0
    extracted_files = 0

    with ZipFile(source) as archive:
        for member in archive.infolist():
            unix_mode = member.external_attr >> 16
            if stat.S_ISLNK(unix_mode):
                raise AppError(
                    code='unsafe_archive_symlink',
                    message='El paquete contiene enlaces simbolicos no permitidos.',
                    details={'path': member.filename},
                )

            if member.is_dir():
                validate_member_path(destination, member.filename).mkdir(parents=True, exist_ok=True)
                continue

            extracted_files += 1
            total_uncompressed_size += member.file_size
            if extracted_files > settings.max_extracted_files:
                raise AppError(
                    code='too_many_extracted_files',
                    message='El paquete contiene demasiados ficheros para procesarlo de forma segura.',
                    details={'maxExtractedFiles': settings.max_extracted_files},
                )
            if total_uncompressed_size > settings.max_extracted_bytes:
                raise AppError(
                    code='extracted_size_limit_exceeded',
                    message='El contenido extraido supera el tamano maximo permitido.',
                    details={'maxExtractedMb': settings.max_extracted_mb},
                )

            target_path = validate_member_path(destination, member.filename)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source_handle, target_path.open('wb') as target_handle:
                shutil.copyfileobj(source_handle, target_handle)
            extracted_paths.append(target_path)

    return extracted_paths
