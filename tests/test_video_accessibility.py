from __future__ import annotations

from app.services.video_accessibility import analyze_video_accessibility, run_video_accessibility_scan


def _status_by_check(resource: dict[str, object], context: str | None = None) -> dict[str, str]:
    checks = analyze_video_accessibility(resource, context)
    return {check.checkId: check.status for check in checks}


def test_video_accessibility_identifies_provider_and_requires_manual_review() -> None:
    statuses = _status_by_check(
        {
            "id": "video-1",
            "title": "Video de apoyo",
            "type": "VIDEO",
            "origin": "EXTERNAL_URL",
            "url": "https://www.youtube.com/watch?v=demo123",
            "accessStatus": "OK",
        }
    )

    assert statuses["video.provider"] == "PASS"
    assert statuses["video.captions"] == "WARNING"
    assert statuses["video.transcript"] == "WARNING"
    assert statuses["video.iframe_title"] == "WARNING"
    assert statuses["video.manual_review"] == "WARNING"


def test_video_accessibility_passes_detectable_signals() -> None:
    statuses = _status_by_check(
        {
            "id": "video-2",
            "title": "Clase con transcript y subtitles",
            "type": "VIDEO",
            "origin": "EXTERNAL_URL",
            "url": "https://vimeo.com/12345?captions=1",
            "accessStatus": "OK",
            "details": {
                "iframeTitle": "Vídeo de presentación",
                "transcriptUrl": "transcript.txt",
            },
        }
    )

    assert statuses["video.provider"] == "PASS"
    assert statuses["video.captions"] == "PASS"
    assert statuses["video.transcript"] == "PASS"
    assert statuses["video.iframe_title"] == "PASS"


def test_video_accessibility_passes_youtube_iframe_with_title() -> None:
    statuses = _status_by_check(
        {
            "id": "video-iframe",
            "title": "Clase incrustada",
            "type": "VIDEO",
            "origin": "EXTERNAL_URL",
            "url": "https://www.youtube.com/watch?v=demo123",
            "accessStatus": "OK",
        },
        '<iframe title="Clase 1: presentación" src="https://www.youtube.com/embed/demo123"></iframe>',
    )

    assert statuses["video.provider"] == "PASS"
    assert statuses["video.iframe_title"] == "PASS"


def test_video_accessibility_fails_iframe_without_title() -> None:
    statuses = _status_by_check(
        {
            "id": "video-iframe-missing-title",
            "title": "Clase incrustada",
            "type": "VIDEO",
            "origin": "EXTERNAL_URL",
            "url": "https://www.youtube.com/watch?v=demo123",
            "accessStatus": "OK",
        },
        '<iframe src="https://www.youtube.com/embed/demo123"></iframe>',
    )

    assert statuses["video.iframe_title"] == "FAIL"


def test_video_accessibility_detects_local_video_controls_and_captions() -> None:
    statuses = _status_by_check(
        {
            "id": "local-video",
            "title": "Demostración del laboratorio",
            "type": "VIDEO",
            "origin": "INTERNAL_FILE",
            "localPath": "media/lab.mp4",
            "accessStatus": "OK",
            "canDownload": True,
        },
        '<video controls src="media/lab.mp4"><track kind="captions" src="media/lab.vtt"></video>',
    )

    assert statuses["video.captions"] == "PASS"
    assert statuses["video.controls"] == "PASS"


def test_video_accessibility_flags_autoplay_without_controls() -> None:
    statuses = _status_by_check(
        {
            "id": "autoplay-video",
            "title": "Demo autoplay",
            "type": "VIDEO",
            "origin": "INTERNAL_FILE",
            "localPath": "media/demo.mp4",
            "accessStatus": "OK",
            "canDownload": True,
        },
        '<video autoplay src="media/demo.mp4"></video>',
    )

    assert statuses["video.controls"] == "FAIL"
    assert statuses["video.autoplay"] == "FAIL"


def test_video_accessibility_marks_ralti_sso_as_not_applicable() -> None:
    statuses = _status_by_check(
        {
            "id": "video-sso",
            "title": "Video protegido",
            "type": "VIDEO",
            "origin": "RALTI",
            "url": "https://ralti.uoc.edu/video/abc",
            "accessStatus": "REQUIERE_SSO",
            "canAccess": False,
        }
    )

    assert statuses["video.accessible"] == "NOT_APPLICABLE"


def test_video_accessibility_job_scan_analyzes_accessible_external_video(test_settings) -> None:
    report = run_video_accessibility_scan(
        settings=test_settings,
        job_id="66666666-6666-6666-6666-666666666666",
        resources=[
            {
                "id": "video-guide",
                "title": "Video de apoyo",
                "type": "VIDEO",
                "origin": "EXTERNAL_URL",
                "url": "https://www.youtube.com/watch?v=demo123",
                "accessStatus": "OK",
                "canAccess": True,
                "contentAvailable": False,
            }
        ],
    )

    assert report.summary.videoResourcesTotal == 1
    assert report.summary.videoResourcesAnalyzed == 1
    assert report.summary.byType["VIDEO"].warningCount >= 1
    assert report.modules[0].resources[0].analysisType == "VIDEO"


def test_video_accessibility_job_scan_skips_sso_video(test_settings) -> None:
    report = run_video_accessibility_scan(
        settings=test_settings,
        job_id="77777777-7777-7777-7777-777777777777",
        resources=[
            {
                "id": "video-sso",
                "title": "Video protegido",
                "type": "VIDEO",
                "origin": "RALTI",
                "url": "https://ralti.uoc.edu/video/abc",
                "accessStatus": "REQUIERE_SSO",
                "canAccess": False,
            }
        ],
    )

    assert report.summary.videoResourcesTotal == 0
    assert report.modules == []
