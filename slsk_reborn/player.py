"""Built-in audio player.

MP3, FLAC, WAV and Ogg Vorbis are decoded in-process by miniaudio (bundled
wheels, no system libraries). Anything else (M4A/AAC, Opus, WMA, APE, ALAC...)
is handed to mpv or ffplay when one of them is installed.

The audio device pulls PCM from a generator on miniaudio's own thread; the UI
only flips flags and reads counters, so nothing here blocks the event loop.
"""
from __future__ import annotations

import array
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

RATE, CHANNELS = 44100, 2
NATIVE = {".mp3", ".flac", ".wav", ".ogg", ".oga"}
AUDIO = NATIVE | {".m4a", ".aac", ".mp4", ".opus", ".wma", ".ape", ".alac", ".aiff", ".aif",
                  ".wv", ".mpc", ".dsf", ".webm"}


def is_audio(path: str) -> bool:
    return Path(path).suffix.lower() in AUDIO


def external_player() -> list[str] | None:
    if (mpv := shutil.which("mpv")):
        return [mpv, "--no-video", "--really-quiet", "--no-terminal"]
    if (ffplay := shutil.which("ffplay")):
        return [ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet"]
    return None


@dataclass
class TrackInfo:
    path: str
    title: str
    artist: str = ""
    album: str = ""
    duration: float = 0.0


def track_info(path: str) -> TrackInfo:
    """Tags when mutagen can read them, otherwise the file and folder names."""
    p = Path(path)
    info = TrackInfo(path, p.stem, album=p.parent.name)
    try:
        import mutagen
        f = mutagen.File(path, easy=True)
        if f is not None:
            tags = f.tags or {}
            pick = lambda k: (tags.get(k) or [""])[0] if hasattr(tags, "get") else ""  # noqa: E731
            info.title = pick("title") or info.title
            info.artist = pick("artist") or pick("albumartist")
            info.album = pick("album") or info.album
            if getattr(f, "info", None) and getattr(f.info, "length", None):
                info.duration = float(f.info.length)
    except Exception:
        pass
    if not info.duration and p.suffix.lower() in NATIVE:
        try:
            import miniaudio
            info.duration = miniaudio.get_file_info(path).duration
        except Exception:
            pass
    return info


class Player:
    """Queue + transport. State: 'stopped', 'playing' or 'paused'."""

    def __init__(self):
        self.queue: list[str] = []
        self.index = -1
        self.state = "stopped"
        self.volume = 0.8
        self.track: TrackInfo | None = None
        self.error = ""
        self._device = None
        self._stream = None
        self._frames = 0          # frames played in the current track
        self._ended = False       # set by the audio thread at end of track
        self._proc: subprocess.Popen | None = None
        # position = wall clock since (re)start; decoded frames run ahead by the device buffer
        self._base = 0.0          # track position at _t0
        self._t0 = 0.0
        self._paused_at = 0.0

    # ------------------------------------------------------------------ queue
    def play_files(self, paths: list[str], start: int = 0) -> bool:
        self.queue = list(paths)
        return self.play_index(start)

    def play_index(self, i: int) -> bool:
        if not 0 <= i < len(self.queue):
            self.stop()
            return False
        self.index = i
        return self._open(self.queue[i])

    def next(self) -> bool:
        return self.play_index(self.index + 1)

    def prev(self) -> bool:
        if self.position > 3:  # like most players: first restart the track
            self.seek(0)
            return True
        return self.play_index(max(self.index - 1, 0))

    # ------------------------------------------------------------------ transport
    def _open(self, path: str) -> bool:
        self._halt()
        self.error = ""
        self.track = track_info(path)
        self._frames, self._ended, self._paused_at = 0, False, 0.0
        self.state = "stopped"
        try:
            if Path(path).suffix.lower() in NATIVE and self._native_ok():
                self._start_native(path, 0)
            else:
                self._start_external(path)
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            self.state = "stopped"
            return False
        self.state = "playing"
        return True

    @staticmethod
    def _native_ok() -> bool:
        try:
            import miniaudio  # noqa: F401
            return True
        except Exception:
            return False

    def _start_native(self, path: str, frame: int) -> None:
        import miniaudio
        self._stream = miniaudio.stream_file(path, nchannels=CHANNELS, sample_rate=RATE, seek_frame=frame)
        self._frames = frame
        self._clock(frame / RATE)
        if self._device is None:
            # SLSK_REBORN_AUDIO=null: decode in real time without a sound card (tests, CI)
            backends = [miniaudio.Backend.NULL] if os.environ.get("SLSK_REBORN_AUDIO") == "null" else None
            self._device = miniaudio.PlaybackDevice(nchannels=CHANNELS, sample_rate=RATE,
                                                    app_name="slsk-reborn", backends=backends)
            feed = self._feed()
            next(feed)
            self._device.start(feed)

    def _feed(self):
        """Runs on the audio thread for the lifetime of the device."""
        want = yield b""
        while True:
            stream = self._stream
            chunk = None
            if stream is not None and self.state == "playing":
                try:
                    chunk = stream.send(want)
                except StopIteration:
                    if self._stream is stream:
                        self._stream, self._ended = None, True
                except Exception:
                    if self._stream is stream:
                        self._stream, self._ended = None, True
            if chunk is None or not len(chunk):
                want = yield array.array("h", bytes(want * CHANNELS * 2))
                continue
            self._frames += len(chunk) // CHANNELS
            vol = self.volume
            if vol < 0.999:
                chunk = array.array("h", [int(s * vol) for s in chunk])
            want = yield chunk

    def _start_external(self, path: str) -> None:
        cmd = external_player()
        if not cmd:
            raise RuntimeError(f"can't play {Path(path).suffix} files: install mpv or ffmpeg (ffplay)")
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        vol = ["--volume=" + str(int(self.volume * 100))] if "mpv" in Path(cmd[0]).name else [
            "-volume", str(int(self.volume * 100))]
        self._proc = subprocess.Popen(cmd + vol + [path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL, creationflags=flags)
        self._clock(0.0)

    def _clock(self, at: float) -> None:
        self._base, self._t0 = at, time.monotonic()
        if self.state == "paused":
            self._paused_at = self._t0

    def _halt(self) -> None:
        self._stream = None
        if self._proc is not None:
            if self._paused_at and hasattr(signal, "SIGCONT"):
                try:
                    self._proc.send_signal(signal.SIGCONT)
                except OSError:
                    pass
            self._proc.terminate()
            self._proc = None

    def toggle(self) -> None:
        if self.state == "playing":
            self.pause()
        elif self.state == "paused":
            self.resume()
        elif self.queue:
            self.play_index(max(self.index, 0))

    def pause(self) -> None:
        if self.state != "playing":
            return
        if self._proc is not None:
            if not hasattr(signal, "SIGSTOP"):
                self.error = "pause needs the built-in decoder (MP3/FLAC/WAV/OGG) on Windows"
                return
            self._proc.send_signal(signal.SIGSTOP)
        self._paused_at = time.monotonic()
        self.state = "paused"

    def resume(self) -> None:
        if self.state != "paused":
            return
        if self._proc is not None:
            self._proc.send_signal(signal.SIGCONT)
        if self._paused_at:
            self._t0 += time.monotonic() - self._paused_at
            self._paused_at = 0.0
        self.state = "playing"

    def stop(self) -> None:
        self._halt()
        self.state = "stopped"
        self._frames = 0

    def seek(self, seconds: float) -> None:
        if not self.track or self._proc is not None or self.state == "stopped":
            return
        dur = self.track.duration or 0
        seconds = max(0.0, min(seconds, dur - 0.5 if dur else seconds))
        try:
            self._start_native(self.track.path, int(seconds * RATE))
        except Exception as e:
            self.error = f"seek failed: {e}"

    def seek_by(self, delta: float) -> None:
        self.seek(self.position + delta)

    def set_volume(self, v: float) -> None:
        self.volume = max(0.0, min(1.0, round(v, 2)))

    # ------------------------------------------------------------------ status
    @property
    def position(self) -> float:
        if self.state == "stopped":
            return 0.0
        pos = self._base + (self._paused_at or time.monotonic()) - self._t0
        if self._proc is None:
            pos = min(pos, self._frames / RATE)
        return max(0.0, pos)

    @property
    def native(self) -> bool:
        return self._proc is None

    def poll(self) -> bool:
        """Call regularly from the UI. Advances the queue; True if the track changed."""
        ended = self._ended or (self._proc is not None and self._proc.poll() is not None)
        if not ended or self.state == "stopped":
            return False
        self._ended = False
        if self._proc is not None:
            self._proc = None
        if self.index + 1 < len(self.queue):
            self.next()
        else:
            self.stop()
        return True

    def close(self) -> None:
        self._halt()
        if self._device is not None:
            try:
                self._device.close()
            except Exception:
                pass
            self._device = None
        self.state = "stopped"


def album_queue(path: str) -> tuple[list[str], int]:
    """The playable files in the same folder (sorted), and where `path` is in it."""
    p = Path(path)
    try:
        files = sorted((str(f) for f in p.parent.iterdir() if f.is_file() and is_audio(f.name)),
                       key=lambda s: os.path.basename(s).lower())
    except OSError:
        files = []
    if str(p) not in files:
        files = [str(p)] + files
    return files, files.index(str(p))
