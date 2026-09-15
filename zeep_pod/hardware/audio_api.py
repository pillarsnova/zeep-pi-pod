"""HTTP-facing audio controls independent from the Pi composition root.

The player adapter owns subprocess and MPV IPC details.  This module owns the
small amount of product policy around those controls: track containment,
repeat-versus-queue semantics, the post-Stop restart guard, and Admin-only
Brainwave previews.  Every runtime dependency is injected so these rules can
be tested without importing :mod:`app` or opening audio hardware.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api_models import BrainwavePreviewCommand, TrackCommand, VolumeCommand
from zeep_pod.hardware.audio import contained_audio_paths

PREVIEW_MAX_VOLUME = 60


class AudioControlService:
    """Apply ZEEP audio policy around one injected player instance."""

    def __init__(
        self,
        *,
        player: Any,
        music_dir: Path,
        preview_dir: Path,
        command_lock: Any,
        stop_guard_seconds: float,
        occupancy_token: Callable[[], str | None],
        safety_guard: Callable[[str], None],
        snapshot_music: Callable[[], dict[str, Any]],
        note_activity: Callable[[str, Any], None],
        logger: Callable[..., None],
        presets: Callable[[], dict[str, Any]],
        render_preview: Callable[[str, int, Path], dict[str, Any]],
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.player = player
        self.music_dir = music_dir
        self.preview_dir = preview_dir
        self.command_lock = command_lock
        self.stop_guard_seconds = max(0.0, float(stop_guard_seconds))
        self.occupancy_token = occupancy_token
        self.safety_guard = safety_guard
        self.snapshot_music = snapshot_music
        self.note_activity = note_activity
        self.log = logger
        self.presets_catalog = presets
        self.render_preview = render_preview
        self.monotonic = monotonic
        self.preview_render_lock = threading.Lock()
        # Preserve the existing startup falling-edge protection for legacy
        # tablets that might otherwise replay their stale queue command.
        self.stop_guard_until = self.monotonic() + self.stop_guard_seconds

    def brainwave_presets(self) -> dict[str, Any]:
        """Return the versioned design catalog and current hardware context."""
        return {
            **self.presets_catalog(),
            "occupied": self.occupancy_token() is not None,
            "player": self.player.backend,
        }

    def brainwave_preview(
        self,
        cmd: BrainwavePreviewCommand,
        principal: Any,
    ) -> dict[str, Any]:
        """Render and play one bounded preview through the Pi speaker."""
        self.safety_guard("ทดสอบเสียง Brainwave")
        occupancy_token = self.occupancy_token()
        occupied = occupancy_token is not None
        if occupied and not cmd.confirm_occupied:
            raise HTTPException(
                409,
                {
                    "code": "occupied_confirmation_required",
                    "message": "มีผู้ใช้งานอยู่ใน ZEEP ต้องยืนยันก่อนเล่นเสียงทดสอบ",
                },
            )
        volume = self._preview_volume(cmd.volume)
        rendered = self._render_single_flight(cmd)
        with self.command_lock:
            # Rendering may take several seconds. Re-check both the emergency
            # latch and the exact occupant immediately before audio starts so
            # confirmation for one Session can never carry into another.
            self.safety_guard("ทดสอบเสียง Brainwave")
            if self.occupancy_token() != occupancy_token:
                raise HTTPException(
                    409,
                    {
                        "code": "occupancy_changed_during_preview",
                        "message": "สถานะผู้ใช้งานเปลี่ยนระหว่างเตรียมเสียง กรุณายืนยันใหม่",
                    },
                )
            try:
                self.player.set_volume(volume)
                self.player.play(rendered["path"], loop=False, queue=False)
            except Exception as exc:
                raise HTTPException(500, str(exc)) from exc

        detail = self._preview_detail(cmd, rendered, volume, occupied)
        self.note_activity("music", detail)
        self.log(
            "brainwave_audio",
            "preview_play",
            operator=principal.username,
            **detail,
        )
        return {
            "ok": True,
            "render": {key: value for key, value in rendered.items() if key != "path"},
            "volume": volume,
            "occupied": occupied,
            "state": self.snapshot_music(),
        }

    def list_music(self) -> dict[str, Any]:
        """List supported local tracks without exposing filesystem paths."""
        tracks = [path.name for path in contained_audio_paths(self.music_dir)]
        return {
            "tracks": tracks,
            "state": self.snapshot_music(),
            "player": self.player.backend,
        }

    def play(self, cmd: TrackCommand) -> dict[str, Any]:
        """Play one contained track, respecting the legacy restart guard."""
        self.safety_guard("เล่นเพลง")
        candidate = self._contained_track(cmd.track)
        with self.command_lock:
            guard_remaining = self.stop_guard_until - self.monotonic()
            if guard_remaining > 0 and not cmd.user_initiated:
                raise HTTPException(
                    409,
                    "Music was stopped by the user; legacy automatic restart blocked",
                )
            try:
                self.player.play(
                    candidate,
                    loop=cmd.resolved_loop,
                    queue=bool(cmd.queue),
                )
            except Exception as exc:
                raise HTTPException(500, str(exc)) from exc

        detail = {
            "action": "play",
            "track": candidate.name,
            "loop": cmd.resolved_loop,
            "queue": bool(cmd.queue),
        }
        self.note_activity("music", detail)
        self.log(
            "music",
            "play",
            **{key: value for key, value in detail.items() if key != "action"},
        )
        return {
            "ok": True,
            "track": candidate.name,
            "loop": cmd.resolved_loop,
            "queue": bool(cmd.queue),
            "player": self.player.backend,
            "state": self.snapshot_music(),
        }

    def stop(self) -> dict[str, Any]:
        """Stop immediately and block stale automatic restart commands."""
        with self.command_lock:
            self.player.stop()
            self.stop_guard_until = self.monotonic() + self.stop_guard_seconds
        return {
            "ok": True,
            "state": self.snapshot_music(),
            "restart_guard_seconds": self.stop_guard_seconds,
        }

    def pause(self) -> dict[str, Any]:
        """Toggle pause when the selected player backend supports live IPC."""
        self.safety_guard("เล่นต่อ/พักเพลง")
        if not self.player.pause_toggle():
            if self.player.backend != "mpv":
                raise HTTPException(
                    501,
                    f"โหมด fallback ({self.player.backend}) ไม่รองรับ pause — "
                    "ใช้ stop แล้วเล่นใหม่",
                )
            raise HTTPException(503, "Player IPC not ready — try again")
        return {"ok": True, "state": self.snapshot_music()}

    def set_volume(self, cmd: VolumeCommand) -> dict[str, Any]:
        """Apply the typed digital-volume command through the player adapter."""
        self.player.set_volume(cmd.volume)
        return {"ok": True, "volume": self.snapshot_music()["volume"]}

    def _contained_track(self, track: str) -> Path:
        root = self.music_dir.resolve()
        candidate = (root / track).resolve()
        if root not in candidate.parents or not candidate.is_file():
            raise HTTPException(404, "Track not found")
        return candidate

    @staticmethod
    def _preview_volume(value: int) -> int:
        volume = max(0, min(PREVIEW_MAX_VOLUME, int(value)))
        if volume != int(value):
            raise HTTPException(
                422,
                "Sound Lab จำกัดระดับ Digital Volume ที่ 0–60%",
            )
        return volume

    def _render(self, cmd: BrainwavePreviewCommand) -> dict[str, Any]:
        try:
            return self.render_preview(
                cmd.preset_id,
                cmd.duration_seconds,
                self.preview_dir,
            )
        except ValueError as exc:
            if str(exc) == "unknown_preset":
                raise HTTPException(404, "ไม่พบ Brainwave preset") from exc
            raise HTTPException(
                422,
                "ระยะ Preview ต้องอยู่ในช่วง 10–90 วินาที",
            ) from exc

    def _render_single_flight(
        self,
        cmd: BrainwavePreviewCommand,
    ) -> dict[str, Any]:
        """Allow only one CPU-heavy preview render at a time on the Pi."""
        if not self.preview_render_lock.acquire(blocking=False):
            raise HTTPException(
                429,
                {
                    "code": "brainwave_render_busy",
                    "message": "กำลังเตรียมเสียงทดสอบรายการก่อนหน้า กรุณารอสักครู่",
                },
            )
        try:
            return self._render(cmd)
        finally:
            self.preview_render_lock.release()

    @staticmethod
    def _preview_detail(
        cmd: BrainwavePreviewCommand,
        rendered: dict[str, Any],
        volume: int,
        occupied: bool,
    ) -> dict[str, Any]:
        return {
            "action": "brainwave_preview",
            "preset_id": cmd.preset_id,
            "version": rendered["version"],
            "duration_seconds": rendered["duration_seconds"],
            "volume": volume,
            "confirmed_while_occupied": bool(occupied),
        }


def create_audio_router(
    service: AudioControlService,
    *,
    require_admin: Any,
    require_pod_operator: Any,
) -> APIRouter:
    """Build the existing audio endpoints around an injected service."""
    router = APIRouter()
    _add_brainwave_routes(router, service, require_admin)
    _add_music_routes(router, service, require_pod_operator)
    return router


def _add_brainwave_routes(
    router: APIRouter,
    service: AudioControlService,
    require_admin: Any,
) -> None:
    @router.get(
        "/api/admin/brainwave/presets",
        dependencies=[Depends(require_admin)],
    )
    def brainwave_presets():
        """Return the versioned Admin Sound Lab preset catalog."""
        return service.brainwave_presets()

    @router.post("/api/admin/brainwave/preview")
    def brainwave_preview(
        cmd: BrainwavePreviewCommand,
        principal: Any = Depends(require_admin),  # noqa: B008
    ):
        """Render and play an Admin-confirmed preview on the Pi speaker."""
        return service.brainwave_preview(cmd, principal)


def _add_music_routes(
    router: APIRouter,
    service: AudioControlService,
    require_pod_operator: Any,
) -> None:
    @router.get(
        "/api/music",
        dependencies=[Depends(require_pod_operator)],
    )
    async def music_list():
        return service.list_music()

    # These remain plain ``def`` endpoints so FastAPI runs blocking player IPC
    # in its thread pool instead of freezing WebSocket updates.
    @router.post(
        "/api/music/play",
        dependencies=[Depends(require_pod_operator)],
    )
    def music_play(cmd: TrackCommand):
        return service.play(cmd)

    @router.post(
        "/api/music/stop",
        dependencies=[Depends(require_pod_operator)],
    )
    def music_stop():
        return service.stop()

    @router.post(
        "/api/music/pause",
        dependencies=[Depends(require_pod_operator)],
    )
    def music_pause():
        return service.pause()

    @router.post(
        "/api/music/volume",
        dependencies=[Depends(require_pod_operator)],
    )
    def music_volume(cmd: VolumeCommand):
        return service.set_volume(cmd)
