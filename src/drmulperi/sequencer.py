import heapq
import json
import os
import random
import shutil
import threading
import time
import warnings

import numpy as np
from scipy.io import wavfile
from scipy.signal import sosfilt, butter

from .audio_engine import AudioEngine, MidiOut
from .config import (
    ACCENT_BOOST,
    ACCENT_TRACK,
    CHAIN_MAX_STEPS,
    MIDI_NOTES,
    PATTERNS,
    TRACKS,
)
from . import ui_texts as texts

class Sequencer:
    """Pattern sequencer state, persistence, scheduling, and high-level actions."""
    DEFAULT_PATTERN_NAME = "new pattern"

    def __init__(
        self,
        kit_path,
        pattern_path,
        samplerate=44100,
        duplex_mode="off",
        default_new_project_kit=None,
        follow_song=False,
        default_step_count=16,
        max_step_count=32,
        default_pattern_count=1,
        humanize_amount=50,
        track_shift_step_ms=5,
    ):
        self.kit_path = kit_path
        self.default_new_project_kit = default_new_project_kit if default_new_project_kit is not None else kit_path
        self.follow_song = bool(follow_song)
        self.pattern_path = pattern_path
        self.pattern_name = os.path.basename(pattern_path)
        self.engine = AudioEngine(kit_path=self.kit_path, samplerate=int(samplerate), duplex_mode=duplex_mode)
        try:
            parsed_default_steps = int(default_step_count)
        except Exception:
            parsed_default_steps = 16
        try:
            parsed_max_steps = int(max_step_count)
        except Exception:
            parsed_max_steps = 32
        self.max_step_count = max(1, parsed_max_steps)
        self.default_step_count = max(1, min(self.max_step_count, parsed_default_steps))
        try:
            self.default_pattern_count = max(1, int(default_pattern_count))
        except Exception:
            self.default_pattern_count = 1
        try:
            self.humanize_amount = max(0, min(100, int(humanize_amount)))
        except Exception:
            self.humanize_amount = 50
        try:
            self.track_shift_step_ms = max(1, min(50, int(track_shift_step_ms)))
        except Exception:
            self.track_shift_step_ms = 5

        self.grid = [self._new_pattern_grid() for _ in range(PATTERNS)]
        self.ratchet_grid = [self._new_pattern_ratchet() for _ in range(PATTERNS)]
        self.detune_grid = [self._new_pattern_detune() for _ in range(PATTERNS)]
        self.pan_grid = [self._new_pattern_pan() for _ in range(PATTERNS)]

        self.pattern = 0
        self.view_pattern = 0
        self.next_pattern = None
        self.pending_events = []
        self.pending_midi_off = []
        self.chain_enabled = False
        self.chain = [0]
        self.chain_pos = 0
        self.song_audio_started = False

        self.step = 0

        self.playing = False
        self.bpm = 120
        self.steps_per_beat = 4
        self.transport_resync = True
        self.transport_lock = threading.RLock()

        self.last_velocity = 9
        self.seq_track_pan = [5 for _ in range(TRACKS)]
        self.seq_track_volume = [9 for _ in range(TRACKS)]
        self.seq_track_humanize = [0 for _ in range(TRACKS)]
        self.seq_track_probability = [0 for _ in range(TRACKS)]
        self.seq_track_group = [0 for _ in range(TRACKS)]
        self.seq_track_pitch = [0 for _ in range(TRACKS)]
        self.seq_track_shift = [5 for _ in range(TRACKS)]
        self.audio_track_slot_pan = [[5 for _ in range(TRACKS - 1)] for _ in range(PATTERNS)]
        self.audio_track_slot_volume = [[9 for _ in range(TRACKS - 1)] for _ in range(PATTERNS)]
        self.audio_track_slot_shift = [[12 for _ in range(TRACKS - 1)] for _ in range(PATTERNS)]
        self.audio_track_slot_sample_paths = [[None for _ in range(TRACKS - 1)] for _ in range(PATTERNS)]
        self.audio_track_slot_sample_names = [["-" for _ in range(TRACKS - 1)] for _ in range(PATTERNS)]
        self.audio_track_slot_samples = [[None for _ in range(TRACKS - 1)] for _ in range(PATTERNS)]
        self.audio_track_slot_channels = [[1 for _ in range(TRACKS - 1)] for _ in range(PATTERNS)]
        self.audio_track_mode = [0 for _ in range(TRACKS - 1)]  # 0=Pattern, 1=Song
        self.audio_track_free_pan = [5 for _ in range(TRACKS - 1)]
        self.audio_track_free_volume = [9 for _ in range(TRACKS - 1)]
        self.audio_track_free_shift = [12 for _ in range(TRACKS - 1)]
        self.audio_track_free_sample_paths = [None for _ in range(TRACKS - 1)]
        self.audio_track_free_sample_names = ["-" for _ in range(TRACKS - 1)]
        self.audio_track_free_samples = [None for _ in range(TRACKS - 1)]
        self.audio_track_free_channels = [1 for _ in range(TRACKS - 1)]
        self.pattern_length = [self.default_step_count for _ in range(PATTERNS)]
        self.pattern_swing = [50 for _ in range(PATTERNS)]
        self.pattern_humanize = [False for _ in range(PATTERNS)]
        self.pattern_names = [self.DEFAULT_PATTERN_NAME for _ in range(PATTERNS)]
        self.muted_rows = [False for _ in range(TRACKS)]
        self.pattern_clipboard = None
        self.midi = MidiOut()
        self.midi_out_enabled = False
        self.pitch_semitones = 0
        self.seq_track_trigger_until = [0.0 for _ in range(TRACKS)]
        self.audio_track_trigger_until = [0.0 for _ in range(TRACKS)]
        self.trigger_flash_seconds = 0.12
        self.chop_preview_path = None
        self.chop_preview_samples = []
        self.chop_preview_names = []

        self.enter_held = False
        self.draw_mode = None

        # ---------- SAVE SYSTEM ----------
        self.dirty = False
        self.last_save_time = time.time()

        self.load()

        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    # ---------- SAVE ----------
    def _new_pattern_grid(self):
        return [[0 for _ in range(self.max_step_count)] for _ in range(TRACKS)]

    def _new_pattern_ratchet(self):
        data = [[1 for _ in range(self.max_step_count)] for _ in range(TRACKS)]
        data[ACCENT_TRACK] = [1 for _ in range(self.max_step_count)]
        return data

    def _new_pattern_detune(self):
        data = [[5 for _ in range(self.max_step_count)] for _ in range(TRACKS)]
        data[ACCENT_TRACK] = [5 for _ in range(self.max_step_count)]
        return data

    def _new_pattern_pan(self):
        data = [[5 for _ in range(self.max_step_count)] for _ in range(TRACKS)]
        data[ACCENT_TRACK] = [5 for _ in range(self.max_step_count)]
        return data

    def pattern_count(self):
        return len(self.grid)

    def _sanitize_pattern_name(self, name):
        """Normalize a pattern name for UI/storage."""
        text = str(name or "").strip()
        if not text:
            text = self.DEFAULT_PATTERN_NAME
        return text[:64]

    def get_pattern_name(self, pattern_index):
        """Return pattern name for index with safe fallback."""
        if pattern_index < 0 or pattern_index >= self.pattern_count():
            return self.DEFAULT_PATTERN_NAME
        if pattern_index >= len(self.pattern_names):
            return self.DEFAULT_PATTERN_NAME
        return self._sanitize_pattern_name(self.pattern_names[pattern_index])

    def set_pattern_name(self, pattern_index, name):
        """Set pattern name for index and mark project dirty when changed."""
        if pattern_index < 0 or pattern_index >= self.pattern_count():
            return
        target = self._sanitize_pattern_name(name)
        while len(self.pattern_names) < self.pattern_count():
            self.pattern_names.append(self.DEFAULT_PATTERN_NAME)
        if self.pattern_names[pattern_index] != target:
            self.pattern_names[pattern_index] = target
            self.dirty = True

    def pattern_note_count(self, pattern_index):
        """Return count of non-accent active steps for one pattern."""
        if pattern_index < 0 or pattern_index >= self.pattern_count():
            return 0
        count = 0
        for t in range(TRACKS - 1):
            for s in range(self.max_step_count):
                if self.grid[pattern_index][t][s] > 0:
                    count += 1
        return count

    def pattern_has_data(self, pattern_index):
        """Return True when a pattern has notes or non-default timing settings."""
        if pattern_index < 0 or pattern_index >= self.pattern_count():
            return False
        if self.pattern_note_count(pattern_index) > 0:
            return True
        if any(self.grid[pattern_index][ACCENT_TRACK][s] > 0 for s in range(self.max_step_count)):
            return True
        if self.pattern_length[pattern_index] != self.max_step_count:
            return True
        if self.pattern_swing[pattern_index] != 50:
            return True
        if self.pattern_humanize[pattern_index]:
            return True
        for t in range(TRACKS - 1):
            for s in range(self.max_step_count):
                if int(self.pan_grid[pattern_index][t][s]) != 5:
                    return True
        return False

    def prepare_chop_candidates_from_file(self, path, slices=8):
        """Analyze a long WAV file and prepare up to 8 chopped one-shot candidates."""
        if not os.path.isfile(path) or not path.lower().endswith(".wav"):
            return False, texts.backend.sequencer.chop.select_wav

        try:
            mono, src_sr, sr, resampled, _ = self._read_wav_mono_info(path)
        except Exception as exc:
            return False, texts.fmt(texts.backend.sequencer.chop.load_failed, error=exc)

        mono = np.asarray(mono, dtype=np.float32)
        if mono.size < 64:
            return False, texts.backend.sequencer.chop.too_short

        slices = max(1, min(8, int(slices)))
        starts = self._detect_chop_starts(mono, sr, slices)
        if len(starts) < slices:
            starts = np.linspace(0, max(0, len(mono) - 1), num=slices, endpoint=False, dtype=np.int32).tolist()
        starts = sorted(max(0, min(len(mono) - 1, int(v))) for v in starts[:slices])

        candidates = []
        names = []
        min_len = max(64, int(sr * 0.02))
        for i in range(slices):
            start = starts[i]
            end = starts[i + 1] if i + 1 < len(starts) else len(mono)
            if end - start < min_len:
                end = min(len(mono), start + min_len)
            chunk = np.copy(mono[start:end])
            if chunk.size <= 0:
                chunk = np.zeros(min_len, dtype=np.float32)
            chunk = self._cleanup_chop_chunk(chunk)
            candidates.append(chunk)
            names.append(f"{os.path.splitext(os.path.basename(path))[0]}_{i+1:02d}.wav")

        self.chop_preview_path = path
        self.chop_preview_samples = candidates
        self.chop_preview_names = names
        sr_hint = f" (SR {src_sr}->{sr})" if resampled else ""
        return True, texts.fmt(texts.backend.sequencer.chop.prepared, count=len(candidates), sr_hint=sr_hint)

    def _detect_chop_starts(self, samples, sr, slices):
        """Detect transient start positions from amplitude envelope for chop preview."""
        if samples.size < 64:
            return [0]
        env = np.abs(samples)
        win = max(1, int(sr * 0.004))
        if win > 1:
            kernel = np.ones(win, dtype=np.float32) / float(win)
            env = np.convolve(env, kernel, mode="same")
        peak = float(np.max(env))
        if peak <= 1e-9:
            return [0]
        threshold = peak * 0.25
        min_gap = max(1, int(sr * 0.04))
        starts = [0]
        last = 0
        idx = 1
        end_limit = samples.size - min_gap
        while idx < end_limit and len(starts) < slices:
            if env[idx] >= threshold and env[idx - 1] < threshold and (idx - last) >= min_gap:
                starts.append(idx)
                last = idx
                idx += min_gap
                continue
            idx += 1
        return starts

    def _cleanup_chop_chunk(self, chunk):
        """Trim leading/trailing silence, normalize, and apply tiny fades."""
        if chunk.size <= 1:
            return chunk
        chunk = self._trim_silence_edges(chunk)
        if chunk.size <= 1:
            return chunk
        peak = float(np.max(np.abs(chunk)))
        if peak > 1e-9:
            chunk = np.clip(chunk * (0.9 / peak), -1.0, 1.0)
        fade = min(64, chunk.size // 8)
        if fade > 1:
            ramp = np.linspace(0.0, 1.0, num=fade, endpoint=True, dtype=np.float32)
            chunk[:fade] *= ramp
            chunk[-fade:] *= ramp[::-1]
        return chunk.astype(np.float32)

    @staticmethod
    def _resample_mono_linear(data, src_sr, dst_sr):
        """Resample mono float signal with linear interpolation."""
        mono = np.asarray(data, dtype=np.float32)
        if mono.size <= 1 or src_sr <= 0 or dst_sr <= 0 or src_sr == dst_sr:
            return mono
        ratio = float(dst_sr) / float(src_sr)
        out_len = max(1, int(round(mono.size * ratio)))
        src_idx = np.arange(mono.size, dtype=np.float32)
        dst_idx = np.linspace(0.0, float(mono.size - 1), num=out_len, dtype=np.float32)
        return np.interp(dst_idx, src_idx, mono).astype(np.float32)

    def _read_wav_mono_info(self, path):
        """Read WAV mono and return (data, source_sr, engine_sr, was_resampled)."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", wavfile.WavFileWarning)
            sr, data = wavfile.read(path)
        if data.dtype == np.int16:
            data = data.astype(np.float32) / 32768.0
        elif data.dtype == np.int32:
            data = data.astype(np.float32) / 2147483648.0
        else:
            data = data.astype(np.float32)
        channels = 2 if len(data.shape) == 2 and data.shape[1] > 1 else 1
        if len(data.shape) == 2:
            data = data.mean(axis=1)
        source_sr = int(sr) if int(sr) > 0 else int(self.engine.sr)
        engine_sr = int(self.engine.sr)
        resampled = source_sr != engine_sr
        if resampled:
            data = self._resample_mono_linear(data, source_sr, engine_sr)
        return data, source_sr, engine_sr, resampled, channels

    def _read_wav_audio_info(self, path):
        """Read WAV as float32, preserve stereo when present, and resample to engine SR."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", wavfile.WavFileWarning)
            sr, data = wavfile.read(path)
        if data.dtype == np.int16:
            data = data.astype(np.float32) / 32768.0
        elif data.dtype == np.int32:
            data = data.astype(np.float32) / 2147483648.0
        else:
            data = data.astype(np.float32)
        channels = 2 if len(data.shape) == 2 and data.shape[1] > 1 else 1
        source_sr = int(sr) if int(sr) > 0 else int(self.engine.sr)
        engine_sr = int(self.engine.sr)
        resampled = source_sr != engine_sr
        if resampled:
            if channels >= 2:
                left = self._resample_mono_linear(data[:, 0], source_sr, engine_sr)
                right = self._resample_mono_linear(data[:, 1], source_sr, engine_sr)
                n = min(len(left), len(right))
                data = np.column_stack((left[:n], right[:n])).astype(np.float32)
            else:
                data = self._resample_mono_linear(data, source_sr, engine_sr)
        if channels >= 2:
            data = np.asarray(data[:, :2], dtype=np.float32)
        else:
            data = np.asarray(data, dtype=np.float32)
        return data, source_sr, engine_sr, resampled, channels

    def _read_wav_mono(self, path):
        """Read WAV as mono float32 and resample to engine sample rate."""
        data, _, _, _, _ = self._read_wav_mono_info(path)
        return data

    def _trim_silence_edges(self, chunk):
        """Trim near-silence from both chunk ends using relative amplitude threshold."""
        if chunk.size <= 1:
            return chunk
        abs_chunk = np.abs(chunk)
        peak = float(np.max(abs_chunk))
        if peak <= 1e-9:
            return chunk
        # Slightly aggressive trim so imported chops start/end tighter.
        threshold = max(2e-4, peak * 0.04)
        idx = np.flatnonzero(abs_chunk >= threshold)
        if idx.size == 0:
            return chunk
        start = int(idx[0])
        end = int(idx[-1]) + 1
        trimmed = chunk[start:end]
        return trimmed if trimmed.size > 0 else chunk

    def preview_chop_candidate(self, index, track=None):
        """Preview one prepared chop candidate in-place from the chop overlay."""
        if index < 0 or index >= len(self.chop_preview_samples):
            return False, texts.backend.sequencer.chop.invalid_index
        pan = 5
        if track is not None and 0 <= track < TRACKS - 1:
            pan = self.seq_track_pan[track]
            self._mark_track_trigger(track, source="seq")
        return self.engine.preview_mono_buffer(
            self.chop_preview_samples[index],
            self.engine.sr,
            velocity=self.last_velocity / 9.0,
            pan=pan,
            name=self.chop_preview_names[index] if index < len(self.chop_preview_names) else f"chop_{index+1}",
        )

    def apply_chop_candidates_to_kit(self):
        """Commit prepared chop candidates into a generated 8-sample kit folder and load it."""
        if not self.chop_preview_samples:
            return False, texts.backend.sequencer.chop.no_prepared
        base = os.path.splitext(os.path.basename(self.chop_preview_path or "chop"))[0]
        ts = time.strftime("%Y%m%d_%H%M%S")
        kit_dir = os.path.join(os.getcwd(), "generated_kits", f"{base}_chop_{ts}")
        try:
            os.makedirs(kit_dir, exist_ok=True)
            for i in range(min(8, len(self.chop_preview_samples))):
                sample = np.asarray(self.chop_preview_samples[i], dtype=np.float32)
                out = np.clip(sample * 32767.0, -32768, 32767).astype(np.int16)
                name = self.chop_preview_names[i] if i < len(self.chop_preview_names) else f"{base}_{i+1:02d}.wav"
                wavfile.write(os.path.join(kit_dir, name), self.engine.sr, out)
        except Exception as exc:
            return False, texts.fmt(texts.backend.sequencer.chop.save_failed, error=exc)
        ok, message = self.load_kit_folder(kit_dir)
        if ok:
            self.dirty = True
        return ok, (texts.fmt(texts.backend.sequencer.chop.loaded_from_chop, message=message) if ok else message)

    @staticmethod
    def swing_ui_to_internal(ui_value):
        """Convert user-facing swing value (0..10) into internal timing value (50..75)."""
        ui = max(0, min(10, int(ui_value)))
        return int(round(50 + (ui * 2.5)))

    @staticmethod
    def swing_internal_to_ui(internal_value):
        """Convert internal timing swing value (50..75) into user-facing value (0..10)."""
        val = max(50, min(75, int(internal_value)))
        return max(0, min(10, int(round((val - 50) / 2.5))))

    @staticmethod
    def _path_for_save(path, base_dir):
        """Return path saved relative to base_dir when possible."""
        if not isinstance(path, str) or not path.strip():
            return None
        src = path
        try:
            if base_dir:
                return os.path.relpath(src, base_dir)
        except Exception:
            pass
        return src

    def _serialize(self, base_dir=None):
        """Return JSON-serializable project state."""
        if base_dir is None:
            base_dir = os.path.dirname(self.pattern_path) if self.pattern_path else os.getcwd()
        audio_tracks = []
        for t in range(TRACKS - 1):
            audio_tracks.append(
                {
                    "mode": "free" if self.audio_track_mode[t] == 1 else "slot",
                    "slot": {
                        "pan": [self.audio_track_slot_pan[p][t] for p in range(self.pattern_count())],
                        "volume": [self.audio_track_slot_volume[p][t] for p in range(self.pattern_count())],
                        "shift": [self.audio_track_slot_shift[p][t] for p in range(self.pattern_count())],
                        "sample_paths": [
                            self._path_for_save(self.audio_track_slot_sample_paths[p][t], base_dir)
                            for p in range(self.pattern_count())
                        ],
                        "sample_names": [self.audio_track_slot_sample_names[p][t] for p in range(self.pattern_count())],
                        "channels": [self.audio_track_slot_channels[p][t] for p in range(self.pattern_count())],
                    },
                    "free": {
                        "pan": self.audio_track_free_pan[t],
                        "volume": self.audio_track_free_volume[t],
                        "shift": self.audio_track_free_shift[t],
                        "sample_path": self._path_for_save(self.audio_track_free_sample_paths[t], base_dir),
                        "sample_name": self.audio_track_free_sample_names[t],
                        "channels": self.audio_track_free_channels[t],
                    },
                }
            )
        seq_sample_paths = []
        seq_sample_names = []
        for t in range(TRACKS - 1):
            src = self.engine.sample_paths[t] if t < len(self.engine.sample_paths) else None
            name = self.engine.sample_names[t] if t < len(self.engine.sample_names) else "-"
            seq_sample_paths.append(self._path_for_save(src, base_dir))
            seq_sample_names.append(name if isinstance(name, str) and name.strip() else "-")
        return {
            "pattern_count": self.pattern_count(),
            "bpm": self.bpm,
            "last_velocity": self.last_velocity,
            "pattern": self.pattern,
            "view_pattern": self.view_pattern,
            "grid": self.grid,
            "seq_samples": {
                "sample_paths": seq_sample_paths,
                "sample_names": seq_sample_names,
            },
            "track_pan": self.seq_track_pan,
            "track_volume": self.seq_track_volume,
            "track_probability": self.seq_track_probability,
            "track_group": self.seq_track_group,
            "track_pitch": self.seq_track_pitch,
            "track_shift": self.seq_track_shift,
            "audio_tracks": audio_tracks,
            "pattern_length": self.pattern_length,
            "pattern_swing": [self.swing_internal_to_ui(v) for v in self.pattern_swing],
            "pattern_humanize": self.pattern_humanize,
            "patterns": [
                {
                    "name": self.get_pattern_name(i),
                }
                for i in range(self.pattern_count())
            ],
            "ratchet_grid": self.ratchet_grid,
            "detune_grid": self.detune_grid,
            "pan_grid": self.pan_grid,
            "chain_enabled": self.chain_enabled,
            "chain": self.chain,
            "midi_out_enabled": self.midi_out_enabled,
            "pitch_semitones": self.pitch_semitones,
        }

    def _apply_loaded_data(self, data):
        """Apply and sanitize loaded project data into runtime state."""
        self.bpm = data.get("bpm", 120)
        try:
            self.last_velocity = max(1, min(9, int(data.get("last_velocity", 9))))
        except (TypeError, ValueError):
            self.last_velocity = 9
        loaded_grid = data.get("grid", self.grid)
        pattern_count = PATTERNS
        if isinstance(data.get("pattern_count"), int):
            pattern_count = max(1, int(data["pattern_count"]))
        if isinstance(loaded_grid, list) and loaded_grid:
            pattern_count = max(pattern_count, len(loaded_grid))

        normalized_grid = [self._new_pattern_grid() for _ in range(pattern_count)]
        if isinstance(loaded_grid, list):
            for p in range(min(pattern_count, len(loaded_grid))):
                if not isinstance(loaded_grid[p], list):
                    continue
                for t in range(min(TRACKS, len(loaded_grid[p]))):
                    if not isinstance(loaded_grid[p][t], list):
                        continue
                    for s in range(min(self.max_step_count, len(loaded_grid[p][t]))):
                        try:
                            val = int(loaded_grid[p][t][s])
                        except (TypeError, ValueError):
                            val = 0
                        if t == ACCENT_TRACK:
                            normalized_grid[p][t][s] = 1 if val > 0 else 0
                        else:
                            normalized_grid[p][t][s] = max(0, min(9, val))
        self.grid = normalized_grid

        loaded_ratchet = data.get("ratchet_grid", self.ratchet_grid)
        normalized_ratchet = [self._new_pattern_ratchet() for _ in range(pattern_count)]
        if isinstance(loaded_ratchet, list):
            for p in range(min(pattern_count, len(loaded_ratchet))):
                if not isinstance(loaded_ratchet[p], list):
                    continue
                for t in range(min(TRACKS, len(loaded_ratchet[p]))):
                    if not isinstance(loaded_ratchet[p][t], list):
                        continue
                    for s in range(min(self.max_step_count, len(loaded_ratchet[p][t]))):
                        try:
                            ratchet = int(loaded_ratchet[p][t][s])
                        except (ValueError, TypeError):
                            ratchet = 1
                        normalized_ratchet[p][t][s] = max(1, min(4, ratchet))
                normalized_ratchet[p][ACCENT_TRACK] = [1 for _ in range(self.max_step_count)]
        self.ratchet_grid = normalized_ratchet
        loaded_detune = data.get("detune_grid", self.detune_grid)
        normalized_detune = [self._new_pattern_detune() for _ in range(pattern_count)]
        if isinstance(loaded_detune, list):
            for p in range(min(pattern_count, len(loaded_detune))):
                if not isinstance(loaded_detune[p], list):
                    continue
                for t in range(min(TRACKS, len(loaded_detune[p]))):
                    if not isinstance(loaded_detune[p][t], list):
                        continue
                    for s in range(min(self.max_step_count, len(loaded_detune[p][t]))):
                        try:
                            det = int(loaded_detune[p][t][s])
                        except (TypeError, ValueError):
                            det = 5
                        normalized_detune[p][t][s] = max(0, min(9, det))
                normalized_detune[p][ACCENT_TRACK] = [5 for _ in range(self.max_step_count)]
        self.detune_grid = normalized_detune
        loaded_step_pan = data.get("pan_grid", self.pan_grid)
        normalized_step_pan = [self._new_pattern_pan() for _ in range(pattern_count)]
        if isinstance(loaded_step_pan, list):
            for p in range(min(pattern_count, len(loaded_step_pan))):
                if not isinstance(loaded_step_pan[p], list):
                    continue
                for t in range(min(TRACKS, len(loaded_step_pan[p]))):
                    if not isinstance(loaded_step_pan[p][t], list):
                        continue
                    for s in range(min(self.max_step_count, len(loaded_step_pan[p][t]))):
                        try:
                            pan = int(loaded_step_pan[p][t][s])
                        except (TypeError, ValueError):
                            pan = 5
                        normalized_step_pan[p][t][s] = max(0, min(9, pan))
                normalized_step_pan[p][ACCENT_TRACK] = [5 for _ in range(self.max_step_count)]
        self.pan_grid = normalized_step_pan

        try:
            self.pattern = max(0, min(pattern_count - 1, int(data.get("pattern", self.pattern))))
        except (TypeError, ValueError):
            self.pattern = 0
        try:
            self.view_pattern = max(0, min(pattern_count - 1, int(data.get("view_pattern", self.pattern))))
        except (TypeError, ValueError):
            self.view_pattern = self.pattern

        loaded_pan = data.get("track_pan", self.seq_track_pan)
        normalized_pan = [5 for _ in range(TRACKS)]
        if isinstance(loaded_pan, list):
            for i in range(min(TRACKS, len(loaded_pan))):
                try:
                    normalized_pan[i] = max(1, min(9, int(loaded_pan[i])))
                except (ValueError, TypeError):
                    normalized_pan[i] = 5
        normalized_pan[ACCENT_TRACK] = 5
        self.seq_track_pan = normalized_pan

        loaded_vol = data.get("track_volume", self.seq_track_volume)
        normalized_vol = [9 for _ in range(TRACKS)]
        if isinstance(loaded_vol, list):
            for i in range(min(TRACKS, len(loaded_vol))):
                try:
                    normalized_vol[i] = max(0, min(9, int(loaded_vol[i])))
                except (ValueError, TypeError):
                    normalized_vol[i] = 9
        normalized_vol[ACCENT_TRACK] = 9
        self.seq_track_volume = normalized_vol

        loaded_pattern_humanize = data.get("pattern_humanize", [])
        normalized_pattern_humanize = [False for _ in range(pattern_count)]
        if isinstance(loaded_pattern_humanize, list):
            for i in range(min(pattern_count, len(loaded_pattern_humanize))):
                value = loaded_pattern_humanize[i]
                if isinstance(value, bool):
                    normalized_pattern_humanize[i] = value
                    continue
                try:
                    normalized_pattern_humanize[i] = int(value) > 0
                except (ValueError, TypeError):
                    normalized_pattern_humanize[i] = False
        else:
            # Backward compatibility: if old per-track humanize exists, map it into one value per pattern.
            loaded_humanize = data.get("track_humanize", [])
            derived = 0
            if isinstance(loaded_humanize, list):
                values = []
                for i in range(min(TRACKS - 1, len(loaded_humanize))):
                    try:
                        values.append(max(0, min(100, int(loaded_humanize[i]))))
                    except (ValueError, TypeError):
                        pass
                if values:
                    derived = int(round(sum(values) / len(values)))
            normalized_pattern_humanize = [derived > 0 for _ in range(pattern_count)]
        self.pattern_humanize = normalized_pattern_humanize

        loaded_pattern_names = [self.DEFAULT_PATTERN_NAME for _ in range(pattern_count)]
        loaded_patterns = data.get("patterns", [])
        if isinstance(loaded_patterns, list):
            for i in range(min(pattern_count, len(loaded_patterns))):
                item = loaded_patterns[i]
                if isinstance(item, dict):
                    loaded_pattern_names[i] = self._sanitize_pattern_name(item.get("name", self.DEFAULT_PATTERN_NAME))
        else:
            # Backward compatibility: older format may store plain list of names.
            legacy_names = data.get("pattern_names", [])
            if isinstance(legacy_names, list):
                for i in range(min(pattern_count, len(legacy_names))):
                    loaded_pattern_names[i] = self._sanitize_pattern_name(legacy_names[i])
        self.pattern_names = loaded_pattern_names

        loaded_prob = data.get("track_probability", self.seq_track_probability)
        normalized_prob = [100 for _ in range(TRACKS)]
        if isinstance(loaded_prob, list):
            for i in range(min(TRACKS, len(loaded_prob))):
                try:
                    normalized_prob[i] = max(0, min(100, int(loaded_prob[i])))
                except (ValueError, TypeError):
                    normalized_prob[i] = 100
        normalized_prob[ACCENT_TRACK] = 100
        self.seq_track_probability = normalized_prob

        loaded_group = data.get("track_group", self.seq_track_group)
        normalized_group = [0 for _ in range(TRACKS)]
        if isinstance(loaded_group, list):
            for i in range(min(TRACKS, len(loaded_group))):
                try:
                    normalized_group[i] = max(0, min(9, int(loaded_group[i])))
                except (ValueError, TypeError):
                    normalized_group[i] = 0
        normalized_group[ACCENT_TRACK] = 0
        self.seq_track_group = normalized_group

        loaded_track_pitch = data.get("track_pitch", self.seq_track_pitch)
        normalized_track_pitch = [0 for _ in range(TRACKS)]
        if isinstance(loaded_track_pitch, list):
            for i in range(min(TRACKS, len(loaded_track_pitch))):
                try:
                    normalized_track_pitch[i] = max(-12, min(12, int(loaded_track_pitch[i])))
                except (ValueError, TypeError):
                    normalized_track_pitch[i] = 0
        normalized_track_pitch[ACCENT_TRACK] = 0
        self.seq_track_pitch = normalized_track_pitch

        loaded_track_shift = data.get("track_shift", self.seq_track_shift)
        normalized_track_shift = [5 for _ in range(TRACKS)]
        if isinstance(loaded_track_shift, list):
            for i in range(min(TRACKS, len(loaded_track_shift))):
                try:
                    normalized_track_shift[i] = max(0, min(9, int(loaded_track_shift[i])))
                except (ValueError, TypeError):
                    normalized_track_shift[i] = 5
        normalized_track_shift[ACCENT_TRACK] = 5
        self.seq_track_shift = normalized_track_shift

        base_dir = os.path.dirname(self.pattern_path) if self.pattern_path else os.getcwd()
        loaded_seq_samples = data.get("seq_samples", {})
        if isinstance(loaded_seq_samples, dict) and isinstance(loaded_seq_samples.get("sample_paths"), list):
            raw_paths = loaded_seq_samples.get("sample_paths", [])
            raw_names = loaded_seq_samples.get("sample_names", [])
            # When embedded sample paths exist, project should restore those exact sequencer samples.
            for t in range(TRACKS - 1):
                self.engine.samples[t] = None
                self.engine.sample_paths[t] = None
                self.engine.sample_names[t] = "-"
                raw_name = raw_names[t] if (isinstance(raw_names, list) and t < len(raw_names)) else "-"
                if isinstance(raw_name, str) and raw_name.strip():
                    self.engine.sample_names[t] = raw_name
            for t in range(min(TRACKS - 1, len(raw_paths))):
                raw_path = raw_paths[t]
                if not isinstance(raw_path, str) or not raw_path.strip():
                    continue
                path = raw_path if os.path.isabs(raw_path) else os.path.join(base_dir, raw_path)
                if not os.path.isfile(path):
                    continue
                try:
                    mono = self._read_wav_mono(path)
                except Exception:
                    continue
                self.engine.samples[t] = mono
                self.engine.sample_paths[t] = path
                if self.engine.sample_names[t] == "-":
                    self.engine.sample_names[t] = os.path.basename(path)

        loaded_tracks = data.get("audio_tracks", [])
        normalized_audio_pan = [[5 for _ in range(TRACKS - 1)] for _ in range(pattern_count)]
        normalized_audio_vol = [[9 for _ in range(TRACKS - 1)] for _ in range(pattern_count)]
        normalized_audio_shift = [[12 for _ in range(TRACKS - 1)] for _ in range(pattern_count)]
        normalized_audio_paths = [[None for _ in range(TRACKS - 1)] for _ in range(pattern_count)]
        normalized_audio_names = [["-" for _ in range(TRACKS - 1)] for _ in range(pattern_count)]
        normalized_audio_channels = [[1 for _ in range(TRACKS - 1)] for _ in range(pattern_count)]
        normalized_mode = [0 for _ in range(TRACKS - 1)]
        normalized_free_pan = [5 for _ in range(TRACKS - 1)]
        normalized_free_vol = [9 for _ in range(TRACKS - 1)]
        normalized_free_shift = [12 for _ in range(TRACKS - 1)]
        normalized_free_paths = [None for _ in range(TRACKS - 1)]
        normalized_free_names = ["-" for _ in range(TRACKS - 1)]
        normalized_free_channels = [1 for _ in range(TRACKS - 1)]

        if isinstance(loaded_tracks, list):
            for t in range(min(TRACKS - 1, len(loaded_tracks))):
                track_obj = loaded_tracks[t] if isinstance(loaded_tracks[t], dict) else {}
                mode = str(track_obj.get("mode", "slot")).strip().lower()
                normalized_mode[t] = 1 if mode == "free" else 0

                pattern_obj = track_obj.get("slot", {})
                pattern_pan = pattern_obj.get("pan", [])
                pattern_vol = pattern_obj.get("volume", [])
                pattern_shift = pattern_obj.get("shift", [])
                pattern_paths = pattern_obj.get("sample_paths", [])
                pattern_names = pattern_obj.get("sample_names", [])
                pattern_channels = pattern_obj.get("channels", [])
                for p in range(pattern_count):
                    if isinstance(pattern_pan, list) and p < len(pattern_pan):
                        try:
                            normalized_audio_pan[p][t] = max(1, min(9, int(pattern_pan[p])))
                        except (TypeError, ValueError):
                            pass
                    if isinstance(pattern_vol, list) and p < len(pattern_vol):
                        try:
                            normalized_audio_vol[p][t] = max(0, min(9, int(pattern_vol[p])))
                        except (TypeError, ValueError):
                            pass
                    if isinstance(pattern_shift, list) and p < len(pattern_shift):
                        try:
                            normalized_audio_shift[p][t] = max(0, min(50, int(pattern_shift[p])))
                        except (TypeError, ValueError):
                            pass
                    if isinstance(pattern_channels, list) and p < len(pattern_channels):
                        try:
                            normalized_audio_channels[p][t] = 2 if int(pattern_channels[p]) >= 2 else 1
                        except (TypeError, ValueError):
                            normalized_audio_channels[p][t] = 1
                    name_val = "-"
                    path_val = None
                    if isinstance(pattern_names, list) and p < len(pattern_names):
                        raw_name = pattern_names[p]
                        if isinstance(raw_name, str) and raw_name.strip():
                            name_val = raw_name
                    if isinstance(pattern_paths, list) and p < len(pattern_paths):
                        raw_path = pattern_paths[p]
                        if isinstance(raw_path, str) and raw_path.strip():
                            path_val = raw_path if os.path.isabs(raw_path) else os.path.join(base_dir, raw_path)
                    if path_val and os.path.isfile(path_val):
                        normalized_audio_paths[p][t] = path_val
                        if name_val == "-":
                            name_val = os.path.basename(path_val)
                    normalized_audio_names[p][t] = name_val

                free_obj = track_obj.get("free", {})
                try:
                    normalized_free_pan[t] = max(1, min(9, int(free_obj.get("pan", 5))))
                except (TypeError, ValueError):
                    pass
                try:
                    normalized_free_vol[t] = max(0, min(9, int(free_obj.get("volume", 9))))
                except (TypeError, ValueError):
                    pass
                try:
                    normalized_free_shift[t] = max(0, min(50, int(free_obj.get("shift", 12))))
                except (TypeError, ValueError):
                    pass
                name_val = free_obj.get("sample_name", "-")
                if not isinstance(name_val, str) or not name_val.strip():
                    name_val = "-"
                path_val = free_obj.get("sample_path")
                if isinstance(path_val, str) and path_val.strip():
                    path_val = path_val if os.path.isabs(path_val) else os.path.join(base_dir, path_val)
                else:
                    path_val = None
                if path_val and os.path.isfile(path_val):
                    normalized_free_paths[t] = path_val
                    if name_val == "-":
                        name_val = os.path.basename(path_val)
                normalized_free_names[t] = name_val
                try:
                    normalized_free_channels[t] = 2 if int(free_obj.get("channels", 1)) >= 2 else 1
                except (TypeError, ValueError):
                    normalized_free_channels[t] = 1

        self.audio_track_slot_pan = normalized_audio_pan
        self.audio_track_slot_volume = normalized_audio_vol
        self.audio_track_slot_shift = normalized_audio_shift
        self.audio_track_slot_sample_paths = normalized_audio_paths
        self.audio_track_slot_sample_names = normalized_audio_names
        self.audio_track_slot_channels = normalized_audio_channels
        self.audio_track_slot_samples = [[None for _ in range(TRACKS - 1)] for _ in range(pattern_count)]
        for p in range(pattern_count):
            for t in range(TRACKS - 1):
                path = self.audio_track_slot_sample_paths[p][t]
                if path and os.path.isfile(path):
                    sample, _, _, _, channels = self._read_wav_audio_info(path)
                    self.audio_track_slot_samples[p][t] = sample
                    self.audio_track_slot_channels[p][t] = 2 if channels >= 2 else 1
        self.audio_track_mode = normalized_mode
        self.audio_track_free_pan = normalized_free_pan
        self.audio_track_free_volume = normalized_free_vol
        self.audio_track_free_shift = normalized_free_shift
        self.audio_track_free_sample_paths = normalized_free_paths
        self.audio_track_free_sample_names = normalized_free_names
        self.audio_track_free_channels = normalized_free_channels
        self.audio_track_free_samples = [None for _ in range(TRACKS - 1)]
        for t in range(TRACKS - 1):
            path = self.audio_track_free_sample_paths[t]
            if path and os.path.isfile(path):
                sample, _, _, _, channels = self._read_wav_audio_info(path)
                self.audio_track_free_samples[t] = sample
                self.audio_track_free_channels[t] = 2 if channels >= 2 else 1

        loaded_lengths = data.get("pattern_length", self.pattern_length)
        normalized_lengths = [self.default_step_count for _ in range(pattern_count)]
        if isinstance(loaded_lengths, list):
            for i in range(min(pattern_count, len(loaded_lengths))):
                try:
                    normalized_lengths[i] = max(1, min(self.max_step_count, int(loaded_lengths[i])))
                except (ValueError, TypeError):
                    normalized_lengths[i] = self.default_step_count
        self.pattern_length = normalized_lengths

        loaded_swing = data.get("pattern_swing", self.pattern_swing)
        normalized_swing = [50 for _ in range(pattern_count)]
        if isinstance(loaded_swing, list):
            for i in range(min(pattern_count, len(loaded_swing))):
                try:
                    raw = int(loaded_swing[i])
                    # Backward compatibility:
                    # old projects stored internal 50..75, new projects store UI 0..10.
                    if raw > 10:
                        normalized_swing[i] = max(50, min(75, raw))
                    else:
                        normalized_swing[i] = self.swing_ui_to_internal(raw)
                except (ValueError, TypeError):
                    normalized_swing[i] = 50
        self.pattern_swing = normalized_swing

        loaded_chain = data.get("chain", self.chain)
        normalized_chain = []
        if isinstance(loaded_chain, list):
            raw = []
            for item in loaded_chain[:CHAIN_MAX_STEPS]:
                try:
                    raw.append(int(item))
                except (ValueError, TypeError):
                    continue

            # Support both formats:
            # - zero-based [0..pattern_count-1] (current saves)
            # - one-based  [1..pattern_count]   (legacy/manual edits)
            if raw:
                has_zero = any(v == 0 for v in raw)
                for value in raw:
                    idx = value if has_zero else (value - 1)
                    if 0 <= idx < pattern_count:
                        normalized_chain.append(idx)
        if not normalized_chain:
            normalized_chain = [0]
        self.chain = normalized_chain
        raw_chain_enabled = data.get("chain_enabled", False)
        if isinstance(raw_chain_enabled, str):
            self.chain_enabled = raw_chain_enabled.strip().lower() in ["1", "true", "yes", "on"]
        else:
            self.chain_enabled = bool(raw_chain_enabled)
        if self.chain_enabled:
            # Always start chain from the first slot after loading a project.
            if not self.chain:
                self.chain = [0]
            self.chain_pos = 0
            self.pattern = self.chain[0]
            if self.follow_song:
                self.view_pattern = self.pattern
            self.next_pattern = None
            self.step = 0

        raw_midi_enabled = data.get("midi_out_enabled", False)
        if isinstance(raw_midi_enabled, str):
            target_midi = raw_midi_enabled.strip().lower() in ["1", "true", "yes", "on"]
        else:
            target_midi = bool(raw_midi_enabled)
        self._set_midi_out_enabled(target_midi)
        try:
            self.pitch_semitones = max(-12, min(12, int(data.get("pitch_semitones", 0))))
        except (TypeError, ValueError):
            self.pitch_semitones = 0
        self._sync_chain_pos_to_pattern()

    def save(self):
        """Save current pattern bank to `self.pattern_path`."""
        base_dir = os.path.dirname(self.pattern_path) if self.pattern_path else os.getcwd()
        data = self._serialize(base_dir=base_dir)

        with open(self.pattern_path, "w") as f:
            json.dump(data, f)

    def autosave_path(self):
        """Return autosave target path for current project."""
        base = os.path.splitext(os.path.basename(self.pattern_path or "project.json"))[0]
        autosave_dir = os.path.join(os.getcwd(), "autosave")
        return os.path.join(autosave_dir, f"{base}_autosave.json")

    def save_autosave(self):
        """Save autosave snapshot without touching the main project file."""
        target = self.autosave_path()
        autosave_dir = os.path.dirname(target)
        os.makedirs(autosave_dir, exist_ok=True)
        with open(target, "w") as f:
            json.dump(self._serialize(base_dir=autosave_dir), f)

    def load(self):
        """Load pattern bank from `self.pattern_path`, creating one if missing."""
        if not os.path.exists(self.pattern_path):
            self.save()
            return

        with open(self.pattern_path, "r") as f:
            data = json.load(f)

        self._apply_loaded_data(data)

    def load_project_file(self, filename):
        """Load a pattern bank JSON file and reset runtime playback state."""
        target = filename.strip()
        if not target:
            return False, texts.backend.sequencer.project.load_canceled

        if not target.lower().endswith(".json"):
            target = f"{target}.json"

        path = target if os.path.isabs(target) else os.path.join(os.getcwd(), target)
        if not os.path.exists(path):
            return False, texts.fmt(texts.backend.sequencer.project.pattern_not_found, name=os.path.basename(path))

        try:
            with open(path, "r") as f:
                data = json.load(f)
        except Exception as exc:
            return False, texts.fmt(texts.backend.sequencer.project.load_failed, error=exc)

        self.pattern_path = path
        self._apply_loaded_data(data)
        self.pattern_name = os.path.basename(path)
        self.playing = False
        self.step = 0
        self.next_pattern = None
        self.pending_events.clear()
        self.pending_midi_off.clear()
        self.dirty = False
        self._sync_chain_pos_to_pattern()
        return True, texts.fmt(texts.backend.sequencer.project.loaded, name=self.pattern_name)

    def new_project(self, filename="new_project.json", kit=None):
        """Reset to a fresh project state and save it to a new JSON file."""
        target = str(filename or "").strip()
        if not target:
            target = "new_project.json"
        if not target.lower().endswith(".json"):
            target = f"{target}.json"
        path = target if os.path.isabs(target) else os.path.join(os.getcwd(), target)

        self.playing = False
        self.engine.stop_all()
        self.pending_events.clear()
        self.pending_midi_off.clear()
        self.step = 0

        n = self.default_pattern_count
        self.grid = [self._new_pattern_grid() for _ in range(n)]
        self.ratchet_grid = [self._new_pattern_ratchet() for _ in range(n)]
        self.detune_grid = [self._new_pattern_detune() for _ in range(n)]
        self.pan_grid = [self._new_pattern_pan() for _ in range(n)]
        self.pattern = 0
        self.view_pattern = 0
        self.next_pattern = None
        self.chain_enabled = False
        self.chain = [0]
        self.chain_pos = 0

        self.bpm = 120
        self.last_velocity = 9
        self.seq_track_pan = [5 for _ in range(TRACKS)]
        self.seq_track_volume = [9 for _ in range(TRACKS)]
        self.seq_track_humanize = [0 for _ in range(TRACKS)]
        self.seq_track_probability = [0 for _ in range(TRACKS)]
        self.seq_track_group = [0 for _ in range(TRACKS)]
        self.seq_track_pitch = [0 for _ in range(TRACKS)]
        self.seq_track_shift = [5 for _ in range(TRACKS)]
        self.pattern_length = [self.default_step_count for _ in range(n)]
        self.pattern_swing = [50 for _ in range(n)]
        self.pattern_humanize = [False for _ in range(n)]
        self.pattern_names = [self.DEFAULT_PATTERN_NAME for _ in range(n)]
        self.muted_rows = [False for _ in range(TRACKS)]
        self.pattern_clipboard = None
        self.pitch_semitones = 0

        self.audio_track_slot_pan = [[5 for _ in range(TRACKS - 1)] for _ in range(n)]
        self.audio_track_slot_volume = [[9 for _ in range(TRACKS - 1)] for _ in range(n)]
        self.audio_track_slot_shift = [[12 for _ in range(TRACKS - 1)] for _ in range(n)]
        self.audio_track_slot_sample_paths = [[None for _ in range(TRACKS - 1)] for _ in range(n)]
        self.audio_track_slot_sample_names = [["-" for _ in range(TRACKS - 1)] for _ in range(n)]
        self.audio_track_slot_samples = [[None for _ in range(TRACKS - 1)] for _ in range(n)]
        self.audio_track_slot_channels = [[1 for _ in range(TRACKS - 1)] for _ in range(n)]
        self.audio_track_mode = [0 for _ in range(TRACKS - 1)]
        self.audio_track_free_pan = [5 for _ in range(TRACKS - 1)]
        self.audio_track_free_volume = [9 for _ in range(TRACKS - 1)]
        self.audio_track_free_shift = [12 for _ in range(TRACKS - 1)]
        self.audio_track_free_sample_paths = [None for _ in range(TRACKS - 1)]
        self.audio_track_free_sample_names = ["-" for _ in range(TRACKS - 1)]
        self.audio_track_free_samples = [None for _ in range(TRACKS - 1)]
        self.audio_track_free_channels = [1 for _ in range(TRACKS - 1)]
        self.seq_track_trigger_until = [0.0 for _ in range(TRACKS)]
        self.audio_track_trigger_until = [0.0 for _ in range(TRACKS)]

        selected_kit = self.default_new_project_kit if kit is None else kit
        selected_kit = str(selected_kit or "").strip()
        if selected_kit:
            kit_path = selected_kit if os.path.isabs(selected_kit) else os.path.join(os.getcwd(), selected_kit)
        else:
            kit_path = ""
        self.kit_path = kit_path
        self.engine.reload_kit(self.kit_path)

        self.pattern_path = path
        self.pattern_name = os.path.basename(path)
        self.dirty = False
        self.last_save_time = time.time()
        try:
            self.save()
        except Exception as exc:
            return False, texts.fmt(texts.backend.sequencer.project.new_failed, error=exc)
        return True, texts.fmt(texts.backend.sequencer.project.new_created, name=self.pattern_name)

    def save_project_file(self, filename):
        """Save pattern bank JSON to a user-provided filename."""
        target = filename.strip()
        if not target:
            return False, texts.backend.sequencer.project.save_canceled

        if not target.lower().endswith(".json"):
            target = f"{target}.json"

        path = target if os.path.isabs(target) else os.path.join(os.getcwd(), target)
        base_dir = os.path.dirname(path) if path else os.getcwd()
        try:
            with open(path, "w") as f:
                json.dump(self._serialize(base_dir=base_dir), f)
        except Exception as exc:
            return False, texts.fmt(texts.backend.sequencer.project.save_failed, error=exc)

        return True, texts.fmt(texts.backend.sequencer.project.saved, name=os.path.basename(path))

    def load_kit_folder(self, foldername):
        """Load a sample kit folder (first 8 alphabetical WAV files)."""
        target = foldername.strip()
        if not target:
            return False, texts.backend.sequencer.project.load_canceled

        path = target if os.path.isabs(target) else os.path.join(os.getcwd(), target)
        if not os.path.isdir(path):
            return False, texts.fmt(texts.backend.sequencer.kit.folder_not_found, name=os.path.basename(path))

        self.kit_path = path
        loaded_count = self.engine.reload_kit(path)
        return True, texts.fmt(texts.backend.sequencer.kit.loaded, name=os.path.basename(path), loaded_count=loaded_count)

    def load_single_sample_to_track(self, track, path):
        """Load one drum sample into a track and trim silence at both edges."""
        if track < 0 or track >= TRACKS - 1:
            return False, texts.backend.sequencer.sample.invalid_track
        if not os.path.isfile(path) or not path.lower().endswith(".wav"):
            return False, texts.backend.sequencer.sample.select_wav
        try:
            sample, src_sr, dst_sr, resampled, _ = self._read_wav_mono_info(path)
        except Exception as exc:
            return False, texts.fmt(texts.backend.sequencer.sample.load_failed, error=exc)
        trimmed = self._trim_silence_edges(np.asarray(sample, dtype=np.float32))
        if trimmed.size > 1:
            sample = trimmed
        ok, message = self.engine.load_single_sample_buffer(
            track,
            sample,
            os.path.basename(path),
            source_path=path,
        )
        if ok:
            self.dirty = True
            if resampled:
                message = texts.fmt(texts.backend.sequencer.sample.with_sr_hint, message=message, src_sr=src_sr, dst_sr=dst_sr)
        return ok, message

    def load_audio_track_sample(self, pattern_index, track, path):
        """Assign a sample file to a track-view lane for a specific pattern."""
        if track < 0 or track >= TRACKS - 1:
            return False, texts.backend.sequencer.sample.invalid_track
        if not os.path.isfile(path) or not path.lower().endswith(".wav"):
            return False, texts.backend.sequencer.sample.select_wav
        try:
            sample, src_sr, dst_sr, resampled, channels = self._read_wav_audio_info(path)
        except Exception as exc:
            return False, texts.fmt(texts.backend.sequencer.sample.load_failed, error=exc)
        if self.audio_track_mode[track] == 1:
            self.audio_track_free_sample_paths[track] = path
            self.audio_track_free_sample_names[track] = os.path.basename(path)
            self.audio_track_free_samples[track] = sample
            self.audio_track_free_channels[track] = channels
            loaded_name = self.audio_track_free_sample_names[track]
        else:
            if pattern_index < 0 or pattern_index >= self.pattern_count():
                return False, texts.backend.sequencer.audio_track.invalid_pattern
            self.audio_track_slot_sample_paths[pattern_index][track] = path
            self.audio_track_slot_sample_names[pattern_index][track] = os.path.basename(path)
            self.audio_track_slot_samples[pattern_index][track] = sample
            self.audio_track_slot_channels[pattern_index][track] = channels
            loaded_name = self.audio_track_slot_sample_names[pattern_index][track]
        self.dirty = True
        msg = texts.fmt(texts.backend.sequencer.sample.loaded_track_sample, name=loaded_name)
        if resampled:
            msg = texts.fmt(texts.backend.sequencer.sample.with_sr_hint, message=msg, src_sr=src_sr, dst_sr=dst_sr)
        return True, msg

    def _is_audio_path_used_elsewhere(self, path, exclude_pattern_index=None, exclude_track=None):
        """Return True when an audio-track sample path is referenced by another audio slot."""
        if not path:
            return False
        for p in range(self.pattern_count()):
            for t in range(TRACKS - 1):
                if p == exclude_pattern_index and t == exclude_track:
                    continue
                if self.audio_track_slot_sample_paths[p][t] == path:
                    return True
        for t in range(TRACKS - 1):
            if exclude_pattern_index is None and t == exclude_track:
                continue
            if self.audio_track_free_sample_paths[t] == path:
                return True
        return False

    def _remove_audio_path_references(self, path):
        """Clear every audio-track reference that points to `path`."""
        if not path:
            return 0
        removed = 0
        for p in range(self.pattern_count()):
            for t in range(TRACKS - 1):
                if self.audio_track_slot_sample_paths[p][t] == path:
                    self.audio_track_slot_sample_paths[p][t] = None
                    self.audio_track_slot_sample_names[p][t] = "-"
                    self.audio_track_slot_samples[p][t] = None
                    self.audio_track_slot_channels[p][t] = 1
                    self.audio_track_slot_pan[p][t] = 5
                    self.audio_track_slot_volume[p][t] = 9
                    self.audio_track_slot_shift[p][t] = 12
                    removed += 1
        for t in range(TRACKS - 1):
            if self.audio_track_free_sample_paths[t] == path:
                self.audio_track_free_sample_paths[t] = None
                self.audio_track_free_sample_names[t] = "-"
                self.audio_track_free_samples[t] = None
                self.audio_track_free_channels[t] = 1
                self.audio_track_free_pan[t] = 5
                self.audio_track_free_volume[t] = 9
                self.audio_track_free_shift[t] = 12
                removed += 1
        return removed

    def force_delete_audio_path(self, path):
        """Delete a sample file and remove all audio-track references to it."""
        target = str(path or "").strip()
        if not target:
            return False, texts.backend.sequencer.sample.no_file_force_delete
        removed = self._remove_audio_path_references(target)
        self.dirty = True
        if os.path.isfile(target):
            try:
                os.remove(target)
                return True, texts.fmt(texts.backend.sequencer.sample.force_deleted, removed=removed)
            except Exception as exc:
                return True, texts.fmt(texts.backend.sequencer.sample.force_removed_delete_failed, removed=removed, error=exc)
        return True, texts.fmt(texts.backend.sequencer.sample.force_removed_missing, removed=removed)

    def clear_audio_track_sample(self, pattern_index, track, delete_file=False):
        """Clear assigned audio-track sample from one pattern/track slot.

        If `delete_file` is True, the source WAV is removed from disk when safe.
        """
        if track < 0 or track >= TRACKS - 1:
            return False, texts.backend.sequencer.sample.invalid_track
        old_path = self.get_audio_track_path(pattern_index, track)
        if self.audio_track_mode[track] == 1:
            self.audio_track_free_sample_paths[track] = None
            self.audio_track_free_sample_names[track] = "-"
            self.audio_track_free_samples[track] = None
            self.audio_track_free_channels[track] = 1
            self.audio_track_free_shift[track] = 12
        else:
            if pattern_index < 0 or pattern_index >= self.pattern_count():
                return False, texts.backend.sequencer.audio_track.invalid_pattern
            self.audio_track_slot_sample_paths[pattern_index][track] = None
            self.audio_track_slot_sample_names[pattern_index][track] = "-"
            self.audio_track_slot_samples[pattern_index][track] = None
            self.audio_track_slot_channels[pattern_index][track] = 1
            self.audio_track_slot_shift[pattern_index][track] = 12
        self.dirty = True
        if delete_file and old_path and os.path.isfile(old_path):
            used_elsewhere = self._is_audio_path_used_elsewhere(
                old_path,
                exclude_pattern_index=(None if self.audio_track_mode[track] == 1 else pattern_index),
                exclude_track=track,
            )
            if used_elsewhere:
                return True, texts.fmt(texts.backend.sequencer.sample.cleared_kept, track_num=track + 1), True
            try:
                os.remove(old_path)
                return True, texts.fmt(texts.backend.sequencer.sample.cleared_deleted, track_num=track + 1), False
            except Exception as exc:
                return True, texts.fmt(texts.backend.sequencer.sample.cleared_delete_failed, track_num=track + 1, error=exc), False
        return True, texts.fmt(texts.backend.sequencer.sample.cleared, track_num=track + 1), False

    def preview_audio_track_file(self, path, pattern_index=None, track=None):
        """Preview any sample file with track-view pan/volume when track is provided."""
        pan = 5
        velocity = self.last_velocity / 9.0
        if (
            pattern_index is not None
            and track is not None
            and 0 <= pattern_index < self.pattern_count()
            and 0 <= track < TRACKS - 1
        ):
            pan = self.get_audio_track_pan(pattern_index, track)
            velocity = max(0.0, min(1.0, self.get_audio_track_volume(pattern_index, track) / 9.0))
            self._mark_track_trigger(track, source="audio")
        return self.engine.preview_wav_file(path, velocity=velocity, pan=pan)

    def preview_audio_track_slot(self, pattern_index, track):
        """Preview the currently assigned sample in one track-view lane."""
        if pattern_index < 0 or pattern_index >= self.pattern_count():
            return False, texts.backend.sequencer.audio_track.invalid_pattern
        if track < 0 or track >= TRACKS - 1:
            return False, texts.backend.sequencer.sample.invalid_track
        path = self.get_audio_track_path(pattern_index, track)
        if not path or not os.path.isfile(path):
            return False, texts.backend.sequencer.sample.no_sample_loaded
        return self.preview_audio_track_file(path, pattern_index=pattern_index, track=track)

    def preview_sample_file(self, path, track=None):
        """Preview a sample file from browser without assigning it."""
        pan = 5
        if track is not None and 0 <= track < TRACKS - 1:
            pan = self.seq_track_pan[track]
            self._mark_track_trigger(track, source="seq")
        return self.engine.preview_wav_file(path, velocity=self.last_velocity / 9.0, pan=pan)

    def save_project_as(self, foldername):
        """Save project into a portable folder containing JSON + referenced samples."""
        target = foldername.strip()
        if not target:
            return False, texts.backend.sequencer.project.save_as_canceled

        project_dir = target if os.path.isabs(target) else os.path.join(os.getcwd(), target)
        try:
            os.makedirs(project_dir, exist_ok=True)
        except Exception as exc:
            return False, texts.fmt(texts.backend.sequencer.project.folder_create_failed, error=exc)

        copied = 0
        for t in range(TRACKS - 1):
            src = self.engine.sample_paths[t] if t < len(self.engine.sample_paths) else None
            if not src or not os.path.isfile(src):
                continue
            dst = os.path.join(project_dir, f"{t+1:02d}_{self.engine.sample_names[t]}")
            try:
                shutil.copy2(src, dst)
                copied += 1
            except Exception:
                continue

        # Copy Track-view audio samples (across every pattern), deduplicated by source path.
        track_audio_map = {}
        track_audio_count = 0
        for p in range(self.pattern_count()):
            for t in range(TRACKS - 1):
                src = self.audio_track_slot_sample_paths[p][t]
                if not src or not os.path.isfile(src):
                    continue
                if src in track_audio_map:
                    continue
                base = os.path.basename(src)
                safe_name = f"trk_{p+1:02d}_{t+1:02d}_{base}"
                dst = os.path.join(project_dir, safe_name)
                # Keep deterministic unique names.
                suffix = 2
                while os.path.exists(dst):
                    stem, ext = os.path.splitext(safe_name)
                    dst = os.path.join(project_dir, f"{stem}_{suffix}{ext}")
                    suffix += 1
                try:
                    shutil.copy2(src, dst)
                    track_audio_map[src] = os.path.basename(dst)
                    track_audio_count += 1
                except Exception:
                    continue
        for t in range(TRACKS - 1):
            src = self.audio_track_free_sample_paths[t]
            if not src or not os.path.isfile(src):
                continue
            if src in track_audio_map:
                continue
            base = os.path.basename(src)
            safe_name = f"song_{t+1:02d}_{base}"
            dst = os.path.join(project_dir, safe_name)
            suffix = 2
            while os.path.exists(dst):
                stem, ext = os.path.splitext(safe_name)
                dst = os.path.join(project_dir, f"{stem}_{suffix}{ext}")
                suffix += 1
            try:
                shutil.copy2(src, dst)
                track_audio_map[src] = os.path.basename(dst)
                track_audio_count += 1
            except Exception:
                continue

        project_name = os.path.basename(os.path.normpath(project_dir)) or "project"
        pattern_filename = f"{project_name}_data.json"
        pattern_path = os.path.join(project_dir, pattern_filename)
        project_data = self._serialize(base_dir=project_dir)
        # Rewrite embedded sequencer sample paths to local copied kit sample files.
        if "seq_samples" in project_data and isinstance(project_data["seq_samples"], dict):
            seq_paths = [None for _ in range(TRACKS - 1)]
            seq_names = [self.engine.sample_names[t] if t < len(self.engine.sample_names) else "-" for t in range(TRACKS - 1)]
            for t in range(TRACKS - 1):
                src = self.engine.sample_paths[t] if t < len(self.engine.sample_paths) else None
                if src and os.path.isfile(src):
                    seq_paths[t] = f"{t+1:02d}_{self.engine.sample_names[t]}"
            project_data["seq_samples"]["sample_paths"] = seq_paths
            project_data["seq_samples"]["sample_names"] = seq_names
        # Rewrite track-view sample paths to local project-relative names when available.
        if "audio_tracks" in project_data and isinstance(project_data["audio_tracks"], list):
            for t in range(min(TRACKS - 1, len(project_data["audio_tracks"]))):
                track_obj = project_data["audio_tracks"][t]
                if not isinstance(track_obj, dict):
                    continue
                pattern_obj = track_obj.get("slot")
                if isinstance(pattern_obj, dict):
                    src_paths = pattern_obj.get("sample_paths")
                    if isinstance(src_paths, list):
                        rewritten = []
                        for p in range(self.pattern_count()):
                            src = self.audio_track_slot_sample_paths[p][t]
                            rewritten.append(track_audio_map.get(src, None))
                        pattern_obj["sample_paths"] = rewritten
                free_obj = track_obj.get("free")
                if isinstance(free_obj, dict):
                    src = self.audio_track_free_sample_paths[t]
                    free_obj["sample_path"] = track_audio_map.get(src, None)
        try:
            with open(pattern_path, "w") as f:
                json.dump(project_data, f)
        except Exception as exc:
            return False, texts.fmt(texts.backend.sequencer.project.pattern_save_failed, error=exc)

        # Open the freshly saved project so UI/project context points at the new folder.
        ok_loaded, load_message = self.load_project_file(pattern_path)
        if not ok_loaded:
            return False, texts.fmt(texts.backend.sequencer.project.reload_failed, message=load_message)

        return True, texts.fmt(
            texts.backend.sequencer.project.saved_portable,
            name=os.path.basename(project_dir),
            kit_count=copied,
            track_audio_count=track_audio_count,
            pattern_filename=pattern_filename,
        )

    def export_current_kit(self, foldername, options=None):
        """Export current sequencer kit samples into a folder with format options."""
        target = str(foldername or "").strip()
        if not target:
            return False, texts.backend.sequencer.kit.export_canceled

        out_dir = target if os.path.isabs(target) else os.path.join(os.getcwd(), target)
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception as exc:
            return False, texts.fmt(texts.backend.sequencer.kit.export_failed, error=exc)

        opts = options or {}
        try:
            bit_depth = int(opts.get("bit_depth", 16))
        except (TypeError, ValueError):
            bit_depth = 16
        bit_depth = 8 if bit_depth == 8 else (12 if bit_depth == 12 else 16)

        try:
            target_sr = int(opts.get("sample_rate", self.engine.sr))
        except (TypeError, ValueError):
            target_sr = self.engine.sr
        target_sr = max(8000, min(192000, target_sr))

        try:
            channels = int(opts.get("channels", 1))
        except (TypeError, ValueError):
            channels = 1
        channels = 2 if channels == 2 else 1

        exported = 0
        for t in range(TRACKS - 1):
            sample = self.engine.samples[t] if t < len(self.engine.samples) else None
            if sample is None or len(sample) <= 0:
                continue
            out = np.asarray(sample, dtype=np.float32)
            if target_sr != self.engine.sr:
                out = self._resample_audio_mono(out, self.engine.sr, target_sr)
            if channels == 2:
                out = np.column_stack((out, out))
            name = self.engine.sample_names[t] if t < len(self.engine.sample_names) else f"track_{t+1:02d}.wav"
            if not str(name).lower().endswith(".wav"):
                name = f"{name}.wav"
            dst = os.path.join(out_dir, f"{t+1:02d}_{os.path.basename(name)}")
            try:
                if bit_depth == 8:
                    wav_data = np.clip(((out + 1.0) * 127.5), 0, 255).astype(np.uint8)
                elif bit_depth == 12:
                    quantized = np.round(out * 2047.0).astype(np.int32)
                    quantized = np.clip(quantized, -2048, 2047)
                    wav_data = (quantized * 16).astype(np.int16)
                else:
                    wav_data = np.clip(out * 32767.0, -32768, 32767).astype(np.int16)
                wavfile.write(dst, target_sr, wav_data)
                exported += 1
            except Exception:
                continue

        if exported <= 0:
            return False, texts.backend.sequencer.kit.no_samples
        chan_label = "stereo" if channels == 2 else "mono"
        return True, texts.fmt(texts.backend.sequencer.kit.exported, name=os.path.basename(out_dir), exported=exported, sample_rate=target_sr, bit_depth=bit_depth, channels=chan_label)

    def export_current_pattern_audio(self, filename, options=None):
        """Offline-render the viewed pattern as one-loop WAV with export options.

        Supported options:
            bit_depth: 8 or 16
            sample_rate: output sample rate in Hz
            channels: 1 (mono) or 2 (stereo)
            scope: "pattern" (viewed pattern) or "chain" (one full song pass)
        """
        target = filename.strip()
        if not target:
            return False, texts.backend.sequencer.export.audio_canceled

        if not target.lower().endswith(".wav"):
            target = f"{target}.wav"

        path = target if os.path.isabs(target) else os.path.join(os.getcwd(), target)
        opts = options or {}
        try:
            bit_depth = int(opts.get("bit_depth", 16))
        except (TypeError, ValueError):
            bit_depth = 16
        bit_depth = 8 if bit_depth == 8 else (12 if bit_depth == 12 else 16)

        try:
            target_sr = int(opts.get("sample_rate", self.engine.sr))
        except (TypeError, ValueError):
            target_sr = self.engine.sr
        target_sr = max(8000, min(192000, target_sr))

        try:
            channels = int(opts.get("channels", 2))
        except (TypeError, ValueError):
            channels = 2
        channels = 1 if channels == 1 else 2

        scope = str(opts.get("scope", "pattern")).strip().lower()
        if scope not in ["pattern", "chain"]:
            scope = "pattern"

        sr = self.engine.sr
        base_step_time = (60.0 / self.bpm) / self.steps_per_beat
        def pitch_sample(sample, rate):
            if sample is None:
                return None
            if abs(rate - 1.0) < 1e-6:
                return sample
            arr = np.asarray(sample, dtype=np.float32)
            if arr.ndim == 2 and arr.shape[1] >= 2:
                left = pitch_sample(arr[:, 0], rate)
                right = pitch_sample(arr[:, 1], rate)
                if left is None or right is None:
                    return None
                n = min(len(left), len(right))
                return np.column_stack((left[:n], right[:n])).astype(np.float32)
            src_len = len(arr)
            if src_len < 2:
                return arr
            out_len = max(1, int(((src_len - 1) / rate) + 1))
            pos = np.arange(out_len, dtype=np.float32) * rate
            idx0 = np.minimum(pos.astype(np.int32), src_len - 2)
            frac = pos - idx0
            idx1 = idx0 + 1
            return ((1.0 - frac) * arr[idx0]) + (frac * arr[idx1])

        pitched_samples = [pitch_sample(self.engine.samples[t], self.pitch_rate(t)) for t in range(TRACKS - 1)]

        if scope == "chain" and self.chain:
            max_index = max(0, self.pattern_count() - 1)
            pattern_order = [max(0, min(max_index, int(p))) for p in self.chain]
        else:
            pattern_order = [self.view_pattern]

        # Build timeline segments: (pattern_index, step_index, step_start_seconds, step_duration_seconds).
        timeline = []
        t_cursor = 0.0
        for pattern in pattern_order:
            current_length = self.pattern_length[pattern]
            for s in range(current_length):
                step_time = self._step_duration_for(pattern, s, base_step_time)
                timeline.append((pattern, s, t_cursor, step_time))
                t_cursor += step_time

        # Export exactly one loop length (no extra tail after the loop end).
        total_seconds = t_cursor
        total_samples = max(1, int(total_seconds * sr))
        mix = np.zeros((total_samples, 2), dtype=np.float32)

        for pattern, s, step_start, step_time in timeline:
            accent_on = (
                not self.muted_rows[ACCENT_TRACK]
                and self.grid[pattern][ACCENT_TRACK][s] > 0
            )
            for t in range(TRACKS - 1):
                if self.muted_rows[t]:
                    continue
                vel = self.grid[pattern][t][s]
                if vel <= 0:
                    continue
                sample = pitched_samples[t]
                if sample is None:
                    continue

                v = vel / 9.0
                if accent_on:
                    v = min(1.0, v + ACCENT_BOOST)
                v = max(0.0, min(1.0, v * (self.seq_track_volume[t] / 9.0)))

                step_pan = max(0, min(9, int(self.pan_grid[pattern][t][s])))
                pan_pos = step_pan / 9.0
                pan_l = float(np.cos(pan_pos * (np.pi / 2)))
                pan_r = float(np.sin(pan_pos * (np.pi / 2)))

                ratchet = max(1, min(4, self.ratchet_grid[pattern][t][s]))
                interval = step_time / ratchet
                detune_ui = max(0, min(9, int(self.detune_grid[pattern][t][s])))
                detune_rate = float(2.0 ** ((detune_ui - 5) / 12.0))
                step_sample = pitch_sample(sample, detune_rate)
                if step_sample is None:
                    continue
                for i in range(ratchet):
                    hit_t = step_start + (i * interval)
                    start = int(hit_t * sr)
                    if start >= total_samples:
                        continue
                    n = min(len(step_sample), total_samples - start)
                    if n <= 0:
                        continue
                    chunk = step_sample[:n] * v
                    mix[start:start + n, 0] += chunk * pan_l
                    mix[start:start + n, 1] += chunk * pan_r

        # Apply EQ before normalization so shelves don't cause clipping.
        if opts.get("eq_enabled"):
            mix = self._apply_export_eq(mix, sr, opts)

        # Louder export: normalize peak to near full scale.
        peak = float(np.max(np.abs(mix))) if mix.size > 0 else 0.0
        if peak > 1e-9:
            out = np.clip(mix * (0.95 / peak), -1.0, 1.0)
        else:
            out = mix

        # Convert channel count.
        if channels == 1:
            out = out.mean(axis=1)

        # Resample final output if needed.
        if target_sr != sr:
            if out.ndim == 1:
                out = self._resample_audio_mono(out, sr, target_sr)
            else:
                left = self._resample_audio_mono(out[:, 0], sr, target_sr)
                right = self._resample_audio_mono(out[:, 1], sr, target_sr)
                n = min(len(left), len(right))
                out = np.column_stack((left[:n], right[:n]))

        if bit_depth == 8:
            out_wav = np.clip(((out + 1.0) * 127.5), 0, 255).astype(np.uint8)
        elif bit_depth == 12:
            quantized = np.round(out * 2047.0).astype(np.int32)
            quantized = np.clip(quantized, -2048, 2047)
            out_wav = (quantized * 16).astype(np.int16)
        else:
            out_wav = (out * 32767.0).astype(np.int16)

        try:
            wavfile.write(path, target_sr, out_wav)
        except Exception as exc:
            return False, texts.fmt(texts.backend.sequencer.export.audio_failed, error=exc)
        chan_label = "mono" if channels == 1 else "stereo"
        scope_label = "song" if scope == "chain" else "pattern"
        return True, texts.fmt(texts.backend.sequencer.export.audio_exported, name=os.path.basename(path), scope=scope_label, sample_rate=target_sr, bit_depth=bit_depth, channels=chan_label)

    @staticmethod
    def _apply_export_eq(audio: np.ndarray, sr: int, opts=None) -> np.ndarray:
        """Apply EQ (shelving filters) and optional tape warble.
        
        opts dict keys:
            eq_low_freq, eq_low_gain, eq_high_freq, eq_high_gain: EQ parameters
            tape_enabled: if True, apply subtle pitch warble like vintage tape
        """
        opts = opts or {}
        
        def _shelf_sos(freq, gain_db, shelf_type, sr):
            """Build a first-order shelving filter as SOS (second-order sections)."""
            A = 10.0 ** (gain_db / 40.0)
            w0 = 2.0 * np.pi * freq / sr
            if shelf_type == "low":
                b0 = A * ((A + 1) - (A - 1) * np.cos(w0) + 2 * np.sqrt(A) * np.sin(w0) / np.sqrt(2))
                b1 = 2 * A * ((A - 1) - (A + 1) * np.cos(w0))
                b2 = A * ((A + 1) - (A - 1) * np.cos(w0) - 2 * np.sqrt(A) * np.sin(w0) / np.sqrt(2))
                a0 = (A + 1) + (A - 1) * np.cos(w0) + 2 * np.sqrt(A) * np.sin(w0) / np.sqrt(2)
                a1 = -2 * ((A - 1) + (A + 1) * np.cos(w0))
                a2 = (A + 1) + (A - 1) * np.cos(w0) - 2 * np.sqrt(A) * np.sin(w0) / np.sqrt(2)
            else:  # high
                b0 = A * ((A + 1) + (A - 1) * np.cos(w0) + 2 * np.sqrt(A) * np.sin(w0) / np.sqrt(2))
                b1 = -2 * A * ((A - 1) + (A + 1) * np.cos(w0))
                b2 = A * ((A + 1) + (A - 1) * np.cos(w0) - 2 * np.sqrt(A) * np.sin(w0) / np.sqrt(2))
                a0 = (A + 1) - (A - 1) * np.cos(w0) + 2 * np.sqrt(A) * np.sin(w0) / np.sqrt(2)
                a1 = 2 * ((A - 1) - (A + 1) * np.cos(w0))
                a2 = (A + 1) - (A - 1) * np.cos(w0) - 2 * np.sqrt(A) * np.sin(w0) / np.sqrt(2)
            return np.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]])

        float_audio = np.asarray(audio, dtype=np.float32)
        stereo = float_audio.ndim == 2
        if not stereo:
            float_audio = float_audio[:, np.newaxis]

        # Get EQ parameters from opts or defaults
        eq_low_freq = float(opts.get("eq_low_freq", 70))
        eq_low_gain = float(opts.get("eq_low_gain", 4))
        eq_high_freq = float(opts.get("eq_high_freq", 9000))
        eq_high_gain = float(opts.get("eq_high_gain", 3))
        
        bass_sos = _shelf_sos(eq_low_freq, eq_low_gain, "low", sr)
        treble_sos = _shelf_sos(eq_high_freq, eq_high_gain, "high", sr)

        out = np.empty_like(float_audio)
        for ch in range(float_audio.shape[1]):
            ch_data = float_audio[:, ch]
            ch_data = sosfilt(bass_sos, ch_data).astype(np.float32)
            ch_data = sosfilt(treble_sos, ch_data).astype(np.float32)
            out[:, ch] = ch_data

        # Apply tape warble: subtle pitch modulation with low-frequency LFO
        if opts.get("tape_enabled"):
            tape_lfo_freq = 0.3  # Hz: slow flutter/wow
            tape_depth = 0.002  # ±0.2% pitch variation (max ~2 cents)
            t = np.arange(len(out)) / sr
            lfo = tape_depth * (0.5 * np.sin(2 * np.pi * tape_lfo_freq * t) + 0.3 * np.sin(2 * np.pi * 0.7 * tape_lfo_freq * t))
            
            for ch in range(out.shape[1]):
                ch_data = out[:, ch]
                # Simple pitch-shift via variable resampling: stretch/compress each grain
                warped = np.zeros_like(ch_data)
                for i in range(1, len(ch_data)):
                    rate_mod = 1.0 + lfo[i]
                    idx = i / rate_mod
                    if idx < len(ch_data) - 1:
                        idx_floor = int(idx)
                        idx_frac = idx - idx_floor
                        warped[i] = ((1 - idx_frac) * ch_data[idx_floor] + idx_frac * ch_data[min(idx_floor + 1, len(ch_data) - 1)])
                    else:
                        warped[i] = ch_data[i]
                out[:, ch] = warped

        if not stereo:
            out = out[:, 0]
        return out

    def render_record_backing(self, precount_pattern, take_pattern, scope="pattern", include_precount=True):
        """Render a deterministic record backing buffer (precount + take) at engine sample rate.

        Returns:
            (buffer_mono, trim_seconds, total_seconds)
            `trim_seconds` indicates how much leading precount should be removed
            from captured input audio after recording.
        """
        sr = int(self.engine.sr)
        scope_norm = str(scope or "pattern").strip().lower()
        if scope_norm not in {"pattern", "song"}:
            scope_norm = "pattern"

        max_idx = max(0, self.pattern_count() - 1)
        pre_idx = max(0, min(max_idx, int(precount_pattern)))
        take_idx = max(0, min(max_idx, int(take_pattern)))

        take_order = []
        if scope_norm == "song" and self.chain:
            take_order = [max(0, min(max_idx, int(v))) for v in self.chain]
        else:
            take_order = [take_idx]

        play_order = []
        trim_seconds = 0.0
        if include_precount:
            play_order.append(pre_idx)
            trim_seconds += self.pattern_duration_seconds(pre_idx)
        play_order.extend(take_order)

        if not play_order:
            return np.zeros((1,), dtype=np.float32), 0.0, 0.0

        base_step_time = (60.0 / self.bpm) / self.steps_per_beat
        timeline = []
        pattern_starts = []
        t_cursor = 0.0
        for pattern in play_order:
            pattern_starts.append((pattern, t_cursor))
            current_length = self.pattern_length[pattern]
            for s in range(current_length):
                step_time = self._step_duration_for(pattern, s, base_step_time)
                timeline.append((pattern, s, t_cursor, step_time))
                t_cursor += step_time

        total_seconds = max(0.01, float(t_cursor))
        total_samples = max(1, int(round(total_seconds * sr)))
        mix = np.zeros((total_samples, 2), dtype=np.float32)

        def pitch_sample(sample, rate):
            if sample is None:
                return None
            if abs(rate - 1.0) < 1e-6:
                return sample
            arr = np.asarray(sample, dtype=np.float32)
            if arr.ndim == 2 and arr.shape[1] >= 2:
                left = pitch_sample(arr[:, 0], rate)
                right = pitch_sample(arr[:, 1], rate)
                if left is None or right is None:
                    return None
                n = min(len(left), len(right))
                return np.column_stack((left[:n], right[:n])).astype(np.float32)
            src_len = len(arr)
            if src_len < 2:
                return arr
            out_len = max(1, int(((src_len - 1) / rate) + 1))
            pos = np.arange(out_len, dtype=np.float32) * rate
            idx0 = np.minimum(pos.astype(np.int32), src_len - 2)
            frac = pos - idx0
            idx1 = idx0 + 1
            return ((1.0 - frac) * arr[idx0]) + (frac * arr[idx1])

        pitched_seq_samples = [pitch_sample(self.engine.samples[t], self.pitch_rate(t)) for t in range(TRACKS - 1)]

        # Pattern/song audio tracks fire once at pattern start.
        for pattern, start_t in pattern_starts:
            start = int(round(start_t * sr))
            if start >= total_samples:
                continue
            for t in range(TRACKS - 1):
                if self.audio_track_mode[t] == 1:
                    # Song audio is only part of song takes.
                    if scope_norm != "song":
                        continue
                    sample = self.audio_track_free_samples[t]
                    vol = max(0.0, min(1.0, self.audio_track_free_volume[t] / 9.0))
                    pan = self.audio_track_free_pan[t]
                    shift_ui = self.audio_track_free_shift[t]
                else:
                    sample = self.audio_track_slot_samples[pattern][t]
                    vol = max(0.0, min(1.0, self.audio_track_slot_volume[pattern][t] / 9.0))
                    pan = self.audio_track_slot_pan[pattern][t]
                    shift_ui = self.audio_track_slot_shift[pattern][t]
                if sample is None or vol <= 0.0:
                    continue
                pitched = pitch_sample(sample, self.pitch_rate())
                pitched = self._apply_audio_track_start_shift(pitched, shift_ui)
                if pitched is None:
                    continue
                n = min(len(pitched), total_samples - start)
                if n <= 0:
                    continue
                pan_pos = (pan - 1) / 8.0
                pan_l = float(np.cos(pan_pos * (np.pi / 2)))
                pan_r = float(np.sin(pan_pos * (np.pi / 2)))
                chunk = pitched[:n] * vol
                if np.asarray(chunk).ndim == 2 and chunk.shape[1] >= 2:
                    mix[start:start + n, 0] += chunk[:, 0] * pan_l
                    mix[start:start + n, 1] += chunk[:, 1] * pan_r
                else:
                    mix[start:start + n, 0] += chunk * pan_l
                    mix[start:start + n, 1] += chunk * pan_r

        # Sequencer track events.
        for pattern, s, step_start, step_time in timeline:
            accent_on = (
                not self.muted_rows[ACCENT_TRACK]
                and self.grid[pattern][ACCENT_TRACK][s] > 0
            )
            for t in range(TRACKS - 1):
                if self.muted_rows[t]:
                    continue
                vel = self.grid[pattern][t][s]
                if vel <= 0:
                    continue
                sample = pitched_seq_samples[t]
                if sample is None:
                    continue

                v = vel / 9.0
                if accent_on:
                    v = min(1.0, v + ACCENT_BOOST)
                v = max(0.0, min(1.0, v * (self.seq_track_volume[t] / 9.0)))

                step_pan = max(0, min(9, int(self.pan_grid[pattern][t][s])))
                pan_pos = step_pan / 9.0
                pan_l = float(np.cos(pan_pos * (np.pi / 2)))
                pan_r = float(np.sin(pan_pos * (np.pi / 2)))

                ratchet = max(1, min(4, self.ratchet_grid[pattern][t][s]))
                interval = step_time / ratchet
                detune_ui = max(0, min(9, int(self.detune_grid[pattern][t][s])))
                detune_rate = float(2.0 ** ((detune_ui - 5) / 12.0))
                step_sample = pitch_sample(sample, detune_rate)
                if step_sample is None:
                    continue
                for i in range(ratchet):
                    shift_sec = self.seq_shift_ui_to_ms(self.seq_track_shift[t]) / 1000.0
                    event_time = step_start + (i * interval) + shift_sec
                    start = int(round(event_time * sr))
                    sample_offset = 0
                    if start < 0:
                        sample_offset = -start
                        start = 0
                    if start >= total_samples:
                        continue
                    if sample_offset >= len(step_sample):
                        continue
                    n = min(len(step_sample) - sample_offset, total_samples - start)
                    if n <= 0:
                        continue
                    chunk = step_sample[sample_offset:sample_offset + n] * v
                    mix[start:start + n, 0] += chunk * pan_l
                    mix[start:start + n, 1] += chunk * pan_r

        # Keep healthy headroom to avoid clipping in realtime callback.
        peak = float(np.max(np.abs(mix))) if mix.size > 0 else 0.0
        if peak > 1e-9:
            mix = np.clip(mix * min(1.0, 0.8 / peak), -1.0, 1.0)

        mono = mix.mean(axis=1).astype(np.float32)
        return mono, float(trim_seconds), float(total_seconds)

    @staticmethod
    def _resample_audio_mono(samples, src_sr, dst_sr):
        """Linear-resample mono audio to a new sample rate."""
        if src_sr == dst_sr or len(samples) <= 1:
            return samples
        ratio = float(dst_sr) / float(src_sr)
        new_len = max(1, int(round(len(samples) * ratio)))
        src_pos = np.linspace(0, len(samples) - 1, num=new_len, endpoint=True)
        idx0 = np.floor(src_pos).astype(np.int32)
        idx1 = np.minimum(idx0 + 1, len(samples) - 1)
        frac = src_pos - idx0
        return ((1.0 - frac) * samples[idx0]) + (frac * samples[idx1])

    # ---------- AUDIO LOOP ----------
    def run(self):
        """Sequencer scheduler loop for timed triggering and autosave debounce."""
        next_time = time.perf_counter()

        while True:
            with self.transport_lock:
                base_step_time = (60.0 / self.bpm) / self.steps_per_beat
                now = time.perf_counter()
                if self.transport_resync:
                    next_time = now
                    self.transport_resync = False

                while self.pending_events and self.pending_events[0][0] <= now:
                    event = heapq.heappop(self.pending_events)
                    if len(event) >= 5:
                        _, track, vel, rate, pan = event
                    elif len(event) >= 4:
                        _, track, vel, rate = event
                        pan = self.seq_track_pan[track] if 0 <= track < len(self.seq_track_pan) else 5
                    else:
                        _, track, vel = event
                        rate = self.pitch_rate(track if 0 <= track < TRACKS - 1 else None)
                        pan = self.seq_track_pan[track] if 0 <= track < len(self.seq_track_pan) else 5
                    self._mark_track_trigger(track, source="seq")
                    if self.midi_out_enabled:
                        self._trigger_midi(track, vel, 0.05)
                    else:
                        group_id = self.seq_track_group[track] if 0 <= track < len(self.seq_track_group) else 0
                        if group_id > 0:
                            self.engine.choke_group(group_id, self.seq_track_group)
                        vol = self.seq_track_volume[track] / 9.0 if 0 <= track < len(self.seq_track_volume) else 1.0
                        self.engine.trigger(track, vel * vol, pan, rate=rate)

                while self.pending_midi_off and self.pending_midi_off[0][0] <= now:
                    _, channel, note = heapq.heappop(self.pending_midi_off)
                    self.midi.send_note_off(channel, note)

                if self.playing:
                    if now >= next_time:
                        step_time = self._step_duration_for(self.pattern, self.step, base_step_time)
                        current_length = self.pattern_length[self.pattern]

                        if self.step == 0 and not self.midi_out_enabled:
                            trigger_song_tracks = self.chain_enabled and (not self.song_audio_started)
                            self._trigger_audio_tracks_for_pattern(
                                self.pattern,
                                include_song_tracks=trigger_song_tracks,
                                include_pattern_tracks=True,
                            )
                            if trigger_song_tracks:
                                self.song_audio_started = True

                        accent_on = (
                            not self.muted_rows[ACCENT_TRACK]
                            and self.grid[self.pattern][ACCENT_TRACK][self.step] > 0
                        )

                        for t in range(TRACKS - 1):
                            if self.muted_rows[t]:
                                continue

                            vel = self.grid[self.pattern][t][self.step]

                            if vel > 0:
                                prob = self.seq_track_probability[t]
                                if prob > 0:
                                    # prob 0=100%, 9=10%; map to actual percent: 100 - prob*10
                                    threshold = 100 - prob * 10
                                    if (random.random() * 100.0) >= threshold:
                                        continue

                                v = vel / 9.0

                                if accent_on:
                                    v = min(1.0, v + ACCENT_BOOST)
                                v = max(0.0, min(1.0, v * (self.seq_track_volume[t] / 9.0)))

                                humanize = (self.humanize_amount / 100.0) if self.pattern_humanize[self.pattern] else 0.0
                                if humanize > 0.0:
                                    vel_jitter = 1.0 + (random.uniform(-0.3, 0.3) * humanize)
                                    v = max(0.0, min(1.0, v * vel_jitter))

                                ratchet = self.ratchet_grid[self.pattern][t][self.step]
                                ratchet = max(1, min(4, ratchet))
                                interval = step_time / ratchet
                                step_rate = self.pitch_rate(t) * self.step_detune_rate(t, self.step)
                                step_pan = max(0, min(9, int(self.pan_grid[self.pattern][t][self.step])))
                                shift_seconds = self.seq_shift_ui_to_ms(self.seq_track_shift[t]) / 1000.0

                                for i in range(ratchet):
                                    fire_time = next_time + (i * interval) + shift_seconds
                                    if humanize > 0.0:
                                        jitter_max = min(step_time * 0.2, interval * 0.45) * humanize
                                        fire_time += random.uniform(-jitter_max, jitter_max)
                                    heapq.heappush(self.pending_events, (fire_time, t, v, step_rate, step_pan))

                        self.step += 1

                        if self.step >= current_length:
                            self.step = 0
                            if self.chain_enabled and self.chain:
                                self.chain_pos = (self.chain_pos + 1) % len(self.chain)
                                if self.chain_pos == 0:
                                    # Song wrapped to the start: allow one-shot song tracks to fire again.
                                    self.song_audio_started = False
                                self.pattern = self.chain[self.chain_pos]
                                if self.follow_song:
                                    self.view_pattern = self.pattern
                                self.next_pattern = None
                            elif self.next_pattern is not None:
                                self.pattern = self.next_pattern
                                self.view_pattern = self.pattern
                                self.next_pattern = None

                        next_time += step_time
                else:
                    self.step = 0
                    self.pending_events.clear()
                    self.song_audio_started = False
                    if self.pending_midi_off:
                        self.midi.all_notes_off()
                        self.pending_midi_off.clear()
                    next_time = time.perf_counter()

            # ---------- AUTO SAVE (debounce) ----------
            if self.dirty and (time.time() - self.last_save_time > 1.5):
                self.save_autosave()
                self.dirty = False
                self.last_save_time = time.time()

            time.sleep(0.0005)

    def toggle_playback(self):
        """Start/stop playback and clear queued/pending events on stop."""
        with self.transport_lock:
            if not self.playing:
                if self.chain_enabled:
                    if not self.chain:
                        self.chain = [0]
                    self.chain_pos = 0
                    self.pattern = self.chain[0]
                    self.next_pattern = None
                    self.step = 0
                    self.pending_events.clear()
                    self.pending_midi_off.clear()
                else:
                    self.pattern = self.view_pattern
                    self.next_pattern = None
                self.song_audio_started = False
            self.playing = not self.playing
            self.transport_resync = True
            if not self.playing:
                self.step = 0
                self.next_pattern = None
                self.song_audio_started = False
                if self.chain_enabled:
                    self.chain_pos = 0
                    if not self.chain:
                        self.chain = [0]
                    self.pattern = self.chain[0]
                self.pending_events.clear()
                self.engine.stop_all()
                if self.pending_midi_off:
                    self.midi.all_notes_off()
                    self.pending_midi_off.clear()

    def _sync_chain_pos_to_pattern(self):
        if not self.chain:
            self.chain = [0]
            self.chain_pos = 0
            return
        if self.pattern in self.chain:
            self.chain_pos = self.chain.index(self.pattern)
        else:
            self.chain_pos = 0

    def toggle_chain(self):
        """Toggle chain mode and reset playback position at mode boundaries."""
        with self.transport_lock:
            self.chain_enabled = not self.chain_enabled
            if self.chain_enabled:
                if not self.chain:
                    self.chain = [0]
                self.chain_pos = 0
                self.pattern = self.chain[0]
                if self.follow_song:
                    self.view_pattern = self.pattern
                self.next_pattern = None
                self.step = 0
                self.pending_events.clear()
                self.pending_midi_off.clear()
                self.song_audio_started = False
                self.dirty = True
                return True, texts.backend.sequencer.song.on
            self.pattern = self.view_pattern
            self.next_pattern = None
            self.step = 0
            self.pending_events.clear()
            self.pending_midi_off.clear()
            self.song_audio_started = False
            self._sync_chain_pos_to_pattern()
            self.dirty = True
            return True, texts.backend.sequencer.song.off

    def _set_midi_out_enabled(self, enabled):
        if enabled == self.midi_out_enabled and not (enabled and self.midi.port is None):
            return True, (texts.backend.sequencer.midi.on if enabled else texts.backend.sequencer.midi.off)
        if enabled:
            ok, message = self.midi.enable()
            if not ok:
                self.midi_out_enabled = False
                return False, message
            self.midi_out_enabled = True
            self.engine.stop_all()
            self.dirty = True
            return True, message
        self.midi.all_notes_off()
        self.pending_midi_off.clear()
        ok, message = self.midi.disable()
        self.midi_out_enabled = False
        self.dirty = True
        return ok, message

    def toggle_midi_out(self):
        """Toggle MIDI output mode on/off."""
        return self._set_midi_out_enabled(not self.midi_out_enabled)

    def pitch_rate(self, track=None):
        """Return playback rate multiplier for global+track semitone transpose."""
        semitones = self.pitch_semitones
        if track is not None and 0 <= track < TRACKS - 1:
            semitones += self.seq_track_pitch[track]
        return float(2.0 ** (semitones / 12.0))

    def change_pitch_semitones(self, delta):
        """Adjust global transpose in semitones within [-12, +12]."""
        new_val = max(-12, min(12, self.pitch_semitones + int(delta)))
        if new_val != self.pitch_semitones:
            self.pitch_semitones = new_val
            self.dirty = True

    def _trigger_midi(self, track, velocity_norm, gate_seconds):
        if not self.midi_out_enabled:
            return
        if track < 0 or track >= TRACKS - 1:
            return
        velocity = max(1, min(127, int(round(velocity_norm * 127))))
        channel = track
        note = MIDI_NOTES[track] if track < len(MIDI_NOTES) else 36
        self.midi.send_note_on(channel, note, velocity)
        heapq.heappush(self.pending_midi_off, (time.perf_counter() + max(0.01, gate_seconds), channel, note))

    def _trigger_audio_tracks_for_pattern(self, pattern_index, include_song_tracks=True, include_pattern_tracks=True):
        """Trigger all loaded Tracks-view lanes for the given pattern once."""
        if pattern_index < 0 or pattern_index >= self.pattern_count():
            return
        include_song_tracks = bool(include_song_tracks)
        include_pattern_tracks = bool(include_pattern_tracks)
        for t in range(TRACKS - 1):
            if self.audio_track_mode[t] == 1:
                # Song tracks only fire while song mode (chain) is active.
                if not self.chain_enabled:
                    continue
                if not include_song_tracks:
                    continue
                sample = self.audio_track_free_samples[t]
                vol = max(0.0, min(1.0, self.audio_track_free_volume[t] / 9.0))
                pan = self.audio_track_free_pan[t]
                shift_ui = self.audio_track_free_shift[t]
            else:
                if not include_pattern_tracks:
                    continue
                sample = self.audio_track_slot_samples[pattern_index][t]
                vol = max(0.0, min(1.0, self.audio_track_slot_volume[pattern_index][t] / 9.0))
                pan = self.audio_track_slot_pan[pattern_index][t]
                shift_ui = self.audio_track_slot_shift[pattern_index][t]
            if sample is None:
                continue
            if vol <= 0.0:
                continue
            sample = self._apply_audio_track_start_shift(sample, shift_ui)
            if sample is None or len(sample) <= 1:
                continue
            self._mark_track_trigger(t, source="audio")
            # Replace previous voice on this audio lane to keep long loops stable.
            self.engine.trigger_buffer(sample, vol, pan, rate=self.pitch_rate(), track=100 + t, replace=True)

    def _apply_audio_track_start_shift(self, sample, shift_ui):
        """Apply audio-track start shift to sample data.

        UI scale is 0..50 where 12 is neutral:
        - >12 trims sample start (earlier perceived hit)
        - <12 adds silence before sample (later perceived hit)
        """
        if sample is None:
            return None
        ms = self.audio_shift_ui_to_ms(shift_ui)
        if ms == 0:
            return sample
        n = int(round(abs(ms) * self.engine.sr / 1000.0))
        if n <= 0:
            return sample
        if ms > 0:
            if n >= len(sample):
                return None
            return sample[n:]
        arr = np.asarray(sample, dtype=np.float32)
        if arr.ndim == 2 and arr.shape[1] >= 2:
            pad = np.zeros((n, arr.shape[1]), dtype=np.float32)
            return np.concatenate((pad, arr), axis=0)
        return np.concatenate((np.zeros((n,), dtype=np.float32), arr))

    def _mark_track_trigger(self, track, source="seq"):
        """Mark a track flash indicator for seq/audio lanes independently."""
        if 0 <= track < TRACKS:
            until = time.perf_counter() + self.trigger_flash_seconds
            if source == "audio":
                self.audio_track_trigger_until[track] = until
            else:
                self.seq_track_trigger_until[track] = until

    def set_chain_from_text(self, text):
        """Parse text chain input (e.g. `1 2 3 2`) and store it."""
        with self.transport_lock:
            src = text.strip()
            if not src:
                return False, texts.backend.sequencer.song.canceled

            values = []
            max_patterns = self.pattern_count()
            src_norm = src.replace(">", " ").replace("-", " ").replace(",", " ")
            parts = [p for p in src_norm.split() if p]
            if not parts:
                # Back-compat compact format like "1232"
                parts = list(src)
            for part in parts:
                if not part.isdigit():
                    return False, texts.fmt(texts.backend.sequencer.song.invalid_chain_use, max_patterns=max_patterns)
                n = int(part)
                if n < 1 or n > max_patterns:
                    return False, texts.fmt(texts.backend.sequencer.song.invalid_chain_range, max_patterns=max_patterns)
                values.append(n - 1)

            if not values:
                return False, texts.backend.sequencer.song.invalid_chain_empty

            if len(values) > CHAIN_MAX_STEPS:
                values = values[:CHAIN_MAX_STEPS]
                clipped = True
            else:
                clipped = False

            self.chain = values
            self.chain_enabled = True
            # Always restart chain from first slot when user sets a new sequence.
            self.chain_pos = 0
            self.pattern = self.chain[0]
            self.next_pattern = None
            self.step = 0
            self.pending_events.clear()
            self.pending_midi_off.clear()
            self.dirty = True
            if clipped:
                return True, texts.fmt(texts.backend.sequencer.song.set_max, max_steps=CHAIN_MAX_STEPS)
            return True, texts.backend.sequencer.song.set

    def append_pattern_to_chain(self, pattern_index):
        """Append one pattern to the song chain without opening text input."""
        with self.transport_lock:
            idx = int(pattern_index)
            if idx < 0 or idx >= self.pattern_count():
                return False, texts.backend.sequencer.audio_track.invalid_pattern
            if len(self.chain) >= CHAIN_MAX_STEPS:
                return False, texts.fmt(texts.backend.sequencer.song.full, max_steps=CHAIN_MAX_STEPS)
            self.chain.append(idx)
            if len(self.chain) == 1:
                self.chain_pos = 0
                if self.chain_enabled:
                    self.pattern = self.chain[0]
            elif self.pattern in self.chain:
                self.chain_pos = self.chain.index(self.pattern)
            else:
                self.chain_pos = min(self.chain_pos, len(self.chain) - 1)
            self.dirty = True
            return True, texts.fmt(texts.backend.sequencer.song.appended, pattern_num=idx + 1)

    def remove_chain_item(self, chain_index):
        """Remove one item from the song chain by chain-list position."""
        with self.transport_lock:
            if chain_index < 0 or chain_index >= len(self.chain):
                return False, texts.backend.sequencer.song.invalid_chain_empty

            removed_pattern = int(self.chain[chain_index])
            del self.chain[chain_index]

            if not self.chain:
                self.chain_enabled = False
                self.chain_pos = 0
                self.pattern = self.view_pattern
                self.next_pattern = None
                self.step = 0
                self.pending_events.clear()
                self.pending_midi_off.clear()
                self.song_audio_started = False
                self.dirty = True
                return True, texts.backend.sequencer.song.removed_last

            if self.chain_enabled:
                self.chain_pos = min(self.chain_pos, len(self.chain) - 1)
                self.pattern = self.chain[self.chain_pos]
                if self.follow_song:
                    self.view_pattern = self.pattern
                self.next_pattern = None
            else:
                self._sync_chain_pos_to_pattern()

            self.dirty = True
            return True, texts.fmt(texts.backend.sequencer.song.removed, pattern_num=removed_pattern + 1)

    def chain_display(self):
        if not self.chain_enabled:
            return "OFF"
        if not self.chain:
            return "OFF"
        parts = []
        for idx, pat in enumerate(self.chain):
            label = str(pat + 1)
            if idx == self.chain_pos:
                parts.append(f"[{label}]")
            else:
                parts.append(label)
        return "-".join(parts)

    def change_current_pattern_length(self, delta):
        """Increase or decrease viewed pattern length within 1..max_step_count."""
        current = self.pattern_length[self.view_pattern]
        new_length = max(1, min(self.max_step_count, current + delta))
        if new_length != current:
            self.pattern_length[self.view_pattern] = new_length
            if self.step >= new_length:
                self.step = 0
            self.dirty = True

    def _step_duration_for(self, pattern_index, step_index, base_step_time):
        swing = self.pattern_swing[pattern_index]
        if swing <= 50:
            return base_step_time

        pair_total = base_step_time * 2.0
        even_duration = pair_total * (swing / 100.0)
        odd_duration = pair_total - even_duration
        return even_duration if (step_index % 2 == 0) else odd_duration

    def pattern_duration_seconds(self, pattern_index):
        """Return one loop duration in seconds for a pattern index."""
        if pattern_index < 0 or pattern_index >= self.pattern_count():
            return 0.0
        base_step_time = (60.0 / self.bpm) / self.steps_per_beat
        total = 0.0
        length = self.pattern_length[pattern_index]
        for s in range(length):
            total += self._step_duration_for(pattern_index, s, base_step_time)
        return max(0.0, total)

    def chain_duration_seconds(self):
        """Return one full song-chain duration in seconds."""
        if not self.chain:
            return self.pattern_duration_seconds(self.pattern)
        total = 0.0
        max_idx = max(0, self.pattern_count() - 1)
        for p in self.chain:
            idx = max(0, min(max_idx, int(p)))
            total += self.pattern_duration_seconds(idx)
        return max(0.0, total)

    def current_pattern_swing_ui(self):
        """Return user-facing swing value in 0..10 scale."""
        internal = self.pattern_swing[self.view_pattern]
        return self.swing_internal_to_ui(internal)

    def set_current_pattern_swing(self, value):
        swing = max(50, min(75, int(value)))
        if self.pattern_swing[self.view_pattern] != swing:
            self.pattern_swing[self.view_pattern] = swing
            self.dirty = True

    def set_current_pattern_swing_ui(self, ui_value):
        """Set swing from user-facing 0..10 scale."""
        self.set_current_pattern_swing(self.swing_ui_to_internal(ui_value))

    def change_current_pattern_swing(self, delta):
        """Increase or decrease viewed pattern swing within 0..10."""
        self.set_current_pattern_swing_ui(self.current_pattern_swing_ui() + int(delta))

    def current_pattern_humanize(self):
        """Return current pattern-level humanize amount (0 or configured amount)."""
        return int(self.humanize_amount) if self.pattern_humanize[self.view_pattern] else 0

    def current_pattern_humanize_enabled(self):
        """Return current pattern humanize toggle state."""
        return bool(self.pattern_humanize[self.view_pattern])

    def set_current_pattern_humanize_enabled(self, enabled):
        """Set current pattern humanize toggle state."""
        new_value = bool(enabled)
        if self.pattern_humanize[self.view_pattern] != new_value:
            self.pattern_humanize[self.view_pattern] = new_value
            self.dirty = True

    def toggle_current_pattern_humanize(self):
        """Toggle current pattern humanize state."""
        self.set_current_pattern_humanize_enabled(not self.current_pattern_humanize_enabled())

    def set_current_pattern_humanize(self, value):
        """Backward-compatible setter: >0 means enabled, 0 means disabled."""
        try:
            enabled = int(value) > 0
        except (TypeError, ValueError):
            enabled = False
        self.set_current_pattern_humanize_enabled(enabled)

    def change_current_pattern_humanize(self, delta):
        """Toggle current pattern-level humanize on any non-zero delta."""
        try:
            if int(delta) != 0:
                self.toggle_current_pattern_humanize()
        except (TypeError, ValueError):
            return

    def set_current_pattern_swing_from_text(self, text):
        src = text.strip()
        if not src:
            return False, texts.backend.sequencer.swing.canceled
        try:
            value = int(src)
        except ValueError:
            return False, texts.backend.sequencer.swing.not_number
        if value < 0 or value > 10:
            return False, texts.backend.sequencer.swing.out_of_range
        self.set_current_pattern_swing_ui(value)
        return True, texts.fmt(texts.backend.sequencer.swing.set, value=value)

    def change_bpm(self, delta):
        self.bpm = max(1, self.bpm + delta)
        self.dirty = True

    def set_bpm(self, value):
        self.bpm = max(1, min(999, int(value)))
        self.dirty = True

    def set_last_velocity(self, velocity):
        self.last_velocity = max(1, min(9, velocity))
        self.dirty = True

    def set_step_velocity(self, track, step, velocity):
        """Set step velocity (or accent on/off), with idle preview on note create."""
        if track < 0 or track >= TRACKS or step < 0:
            return
        if self.view_pattern < 0 or self.view_pattern >= len(self.grid):
            return
        pattern_grid = self.grid[self.view_pattern]
        if track >= len(pattern_grid):
            return
        row = pattern_grid[track]
        if step >= len(row):
            return

        prev = row[step]
        if track == ACCENT_TRACK:
            row[step] = 1 if velocity > 0 else 0
        else:
            row[step] = max(0, min(9, velocity))
            new_val = row[step]
            if prev == 0 and new_val > 0:
                self._preview_note_if_idle(track, new_val)
        self.dirty = True

    def set_step_ratchet(self, track, step, ratchet):
        if track == ACCENT_TRACK:
            return
        self.ratchet_grid[self.view_pattern][track][step] = max(1, min(4, ratchet))
        self.dirty = True

    def set_step_detune(self, track, step, detune):
        """Set per-step detune value (0..9, 5 neutral)."""
        if track == ACCENT_TRACK:
            return
        self.detune_grid[self.view_pattern][track][step] = max(0, min(9, int(detune)))
        self.dirty = True

    def set_step_pan(self, track, step, pan):
        """Set per-step pan value (0..9, 5 center)."""
        if track == ACCENT_TRACK:
            return
        if track < 0 or track >= TRACKS - 1 or step < 0 or step >= self.max_step_count:
            return
        self.pan_grid[self.view_pattern][track][step] = max(0, min(9, int(pan)))
        self.dirty = True

    def step_detune_rate(self, track, step):
        """Return playback rate multiplier for per-step detune value."""
        if track == ACCENT_TRACK:
            return 1.0
        if track < 0 or track >= TRACKS - 1 or step < 0 or step >= self.max_step_count:
            return 1.0
        ui = int(self.detune_grid[self.pattern][track][step])
        semis = float(ui - 5)
        return float(2.0 ** (semis / 12.0))

    def quick_set_ratchet(self, track, step, ratchet):
        if track == ACCENT_TRACK:
            return
        prev = self.grid[self.view_pattern][track][step]
        self.ratchet_grid[self.view_pattern][track][step] = max(1, min(4, ratchet))
        if self.grid[self.view_pattern][track][step] == 0:
            self.grid[self.view_pattern][track][step] = self.last_velocity
        if prev == 0 and self.grid[self.view_pattern][track][step] > 0:
            self._preview_note_if_idle(track, self.grid[self.view_pattern][track][step])
        self.dirty = True

    def cycle_step_ratchet(self, track, step):
        if track == ACCENT_TRACK:
            return
        current = self.ratchet_grid[self.view_pattern][track][step]
        self.ratchet_grid[self.view_pattern][track][step] = 1 + (current % 4)
        self.dirty = True

    def toggle_step(self, track, step):
        """Toggle step between empty and last-used velocity."""
        current = self.grid[self.view_pattern][track][step]
        if current == 0:
            if track == ACCENT_TRACK:
                self.grid[self.view_pattern][track][step] = 1
            else:
                self.grid[self.view_pattern][track][step] = self.last_velocity
                self._preview_note_if_idle(track, self.grid[self.view_pattern][track][step])
        else:
            self.grid[self.view_pattern][track][step] = 0
        self.dirty = True

    def clear_current_pattern(self):
        """Clear notes/ratchets for viewed pattern."""
        self.grid[self.view_pattern] = [
            [0 for _ in range(self.max_step_count)] for _ in range(TRACKS)
        ]
        self.ratchet_grid[self.view_pattern] = [
            [1 for _ in range(self.max_step_count)] for _ in range(TRACKS)
        ]
        self.ratchet_grid[self.view_pattern][ACCENT_TRACK] = [1 for _ in range(self.max_step_count)]
        self.detune_grid[self.view_pattern] = [
            [5 for _ in range(self.max_step_count)] for _ in range(TRACKS)
        ]
        self.detune_grid[self.view_pattern][ACCENT_TRACK] = [5 for _ in range(self.max_step_count)]
        self.pan_grid[self.view_pattern] = [
            [5 for _ in range(self.max_step_count)] for _ in range(TRACKS)
        ]
        self.pan_grid[self.view_pattern][ACCENT_TRACK] = [5 for _ in range(self.max_step_count)]
        self.dirty = True

    def add_pattern(self, copy_from_view=False):
        """Append a new pattern. Optionally duplicate currently viewed pattern."""
        if copy_from_view and 0 <= self.view_pattern < self.pattern_count():
            self.grid.append([row[:] for row in self.grid[self.view_pattern]])
            self.ratchet_grid.append([row[:] for row in self.ratchet_grid[self.view_pattern]])
            self.detune_grid.append([row[:] for row in self.detune_grid[self.view_pattern]])
            self.pan_grid.append([row[:] for row in self.pan_grid[self.view_pattern]])
            self.pattern_length.append(int(self.pattern_length[self.view_pattern]))
            self.pattern_swing.append(int(self.pattern_swing[self.view_pattern]))
            self.pattern_humanize.append(bool(self.pattern_humanize[self.view_pattern]))
            self.audio_track_slot_pan.append(self.audio_track_slot_pan[self.view_pattern][:])
            self.audio_track_slot_volume.append(self.audio_track_slot_volume[self.view_pattern][:])
            self.audio_track_slot_shift.append(self.audio_track_slot_shift[self.view_pattern][:])
            self.audio_track_slot_sample_paths.append(self.audio_track_slot_sample_paths[self.view_pattern][:])
            self.audio_track_slot_sample_names.append(self.audio_track_slot_sample_names[self.view_pattern][:])
            self.audio_track_slot_samples.append(self.audio_track_slot_samples[self.view_pattern][:])
            self.audio_track_slot_channels.append(self.audio_track_slot_channels[self.view_pattern][:])
        else:
            self.grid.append(self._new_pattern_grid())
            self.ratchet_grid.append(self._new_pattern_ratchet())
            self.detune_grid.append(self._new_pattern_detune())
            self.pan_grid.append(self._new_pattern_pan())
            self.pattern_length.append(self.default_step_count)
            self.pattern_swing.append(50)
            self.pattern_humanize.append(False)
            self.pattern_names.append(self.DEFAULT_PATTERN_NAME)
            self.audio_track_slot_pan.append([5 for _ in range(TRACKS - 1)])
            self.audio_track_slot_volume.append([9 for _ in range(TRACKS - 1)])
            self.audio_track_slot_shift.append([12 for _ in range(TRACKS - 1)])
            self.audio_track_slot_sample_paths.append([None for _ in range(TRACKS - 1)])
            self.audio_track_slot_sample_names.append(["-" for _ in range(TRACKS - 1)])
            self.audio_track_slot_samples.append([None for _ in range(TRACKS - 1)])
            self.audio_track_slot_channels.append([1 for _ in range(TRACKS - 1)])
        self.view_pattern = self.pattern_count() - 1
        if not self.chain_enabled and not self.playing:
            self.pattern = self.view_pattern
        self.dirty = True
        return True, texts.fmt(texts.backend.sequencer.pattern.added, num=self.view_pattern + 1)

    def add_pattern_after_current(self, copy_from_view=False):
        """Insert a new pattern after current view. Optionally duplicate current pattern."""
        insert_at = max(0, min(self.pattern_count(), int(self.view_pattern) + 1))
        if copy_from_view and 0 <= self.view_pattern < self.pattern_count():
            grid = [row[:] for row in self.grid[self.view_pattern]]
            ratchet = [row[:] for row in self.ratchet_grid[self.view_pattern]]
            detune = [row[:] for row in self.detune_grid[self.view_pattern]]
            pan = [row[:] for row in self.pan_grid[self.view_pattern]]
            length = int(self.pattern_length[self.view_pattern])
            swing = int(self.pattern_swing[self.view_pattern])
            humanize = bool(self.pattern_humanize[self.view_pattern])
            name = self.DEFAULT_PATTERN_NAME
            slot_pan = self.audio_track_slot_pan[self.view_pattern][:]
            slot_vol = self.audio_track_slot_volume[self.view_pattern][:]
            slot_shift = self.audio_track_slot_shift[self.view_pattern][:]
            slot_paths = self.audio_track_slot_sample_paths[self.view_pattern][:]
            slot_names = self.audio_track_slot_sample_names[self.view_pattern][:]
            slot_samples = self.audio_track_slot_samples[self.view_pattern][:]
            slot_channels = self.audio_track_slot_channels[self.view_pattern][:]
        else:
            grid = self._new_pattern_grid()
            ratchet = self._new_pattern_ratchet()
            detune = self._new_pattern_detune()
            pan = self._new_pattern_pan()
            length = self.default_step_count
            swing = 50
            humanize = False
            name = self.DEFAULT_PATTERN_NAME
            slot_pan = [5 for _ in range(TRACKS - 1)]
            slot_vol = [9 for _ in range(TRACKS - 1)]
            slot_shift = [12 for _ in range(TRACKS - 1)]
            slot_paths = [None for _ in range(TRACKS - 1)]
            slot_names = ["-" for _ in range(TRACKS - 1)]
            slot_samples = [None for _ in range(TRACKS - 1)]
            slot_channels = [1 for _ in range(TRACKS - 1)]

        self.grid.insert(insert_at, grid)
        self.ratchet_grid.insert(insert_at, ratchet)
        self.detune_grid.insert(insert_at, detune)
        self.pan_grid.insert(insert_at, pan)
        self.pattern_length.insert(insert_at, length)
        self.pattern_swing.insert(insert_at, swing)
        self.pattern_humanize.insert(insert_at, humanize)
        self.pattern_names.insert(insert_at, name)
        self.audio_track_slot_pan.insert(insert_at, slot_pan)
        self.audio_track_slot_volume.insert(insert_at, slot_vol)
        self.audio_track_slot_shift.insert(insert_at, slot_shift)
        self.audio_track_slot_sample_paths.insert(insert_at, slot_paths)
        self.audio_track_slot_sample_names.insert(insert_at, slot_names)
        self.audio_track_slot_samples.insert(insert_at, slot_samples)
        self.audio_track_slot_channels.insert(insert_at, slot_channels)

        def remap_after_insert(v):
            return v + 1 if v >= insert_at else v

        self.pattern = remap_after_insert(self.pattern)
        self.view_pattern = insert_at
        if self.next_pattern is not None:
            self.next_pattern = remap_after_insert(self.next_pattern)
        self.chain = [p + 1 if p >= insert_at else p for p in self.chain]
        self._sync_chain_pos_to_pattern()

        if not self.chain_enabled and not self.playing:
            self.pattern = self.view_pattern

        self.dirty = True
        return True, texts.fmt(texts.backend.sequencer.pattern.added, num=self.view_pattern + 1)

    def delete_pattern(self, pattern_index):
        """Delete a pattern by index, keeping at least one pattern."""
        if self.pattern_count() <= 1:
            return False, texts.backend.sequencer.pattern.at_least_one_required
        idx = max(0, min(self.pattern_count() - 1, int(pattern_index)))
        del self.grid[idx]
        del self.ratchet_grid[idx]
        del self.detune_grid[idx]
        del self.pan_grid[idx]
        del self.pattern_length[idx]
        del self.pattern_swing[idx]
        del self.pattern_humanize[idx]
        del self.pattern_names[idx]
        del self.audio_track_slot_pan[idx]
        del self.audio_track_slot_volume[idx]
        del self.audio_track_slot_shift[idx]
        del self.audio_track_slot_sample_paths[idx]
        del self.audio_track_slot_sample_names[idx]
        del self.audio_track_slot_samples[idx]
        del self.audio_track_slot_channels[idx]

        def remap_pattern_index(v):
            if v == idx:
                return max(0, min(self.pattern_count() - 1, idx - 1))
            if v > idx:
                return v - 1
            return v

        self.pattern = remap_pattern_index(self.pattern)
        self.view_pattern = remap_pattern_index(self.view_pattern)
        if self.next_pattern is not None:
            self.next_pattern = remap_pattern_index(self.next_pattern)

        new_chain = []
        for p in self.chain:
            if p == idx:
                continue
            new_chain.append(p - 1 if p > idx else p)
        self.chain = new_chain if new_chain else [0]
        self.chain_pos = min(self.chain_pos, len(self.chain) - 1)
        self._sync_chain_pos_to_pattern()
        self.dirty = True
        return True, texts.fmt(texts.backend.sequencer.pattern.deleted, num=idx + 1)

    def delete_view_pattern(self):
        """Delete currently viewed pattern, keeping at least one pattern."""
        return self.delete_pattern(self.view_pattern)

    def copy_current_pattern(self):
        """Copy viewed pattern into internal clipboard."""
        slot_samples = []
        for sample in self.audio_track_slot_samples[self.view_pattern]:
            if sample is None:
                slot_samples.append(None)
            else:
                slot_samples.append(np.copy(sample))
        self.pattern_clipboard = {
            "grid": [row[:] for row in self.grid[self.view_pattern]],
            "ratchet_grid": [row[:] for row in self.ratchet_grid[self.view_pattern]],
            "detune_grid": [row[:] for row in self.detune_grid[self.view_pattern]],
            "pan_grid": [row[:] for row in self.pan_grid[self.view_pattern]],
            "length": self.pattern_length[self.view_pattern],
            "swing": self.pattern_swing[self.view_pattern],
            "humanize": self.pattern_humanize[self.view_pattern],
            "audio_slot_pan": self.audio_track_slot_pan[self.view_pattern][:],
            "audio_slot_volume": self.audio_track_slot_volume[self.view_pattern][:],
            "audio_slot_shift": self.audio_track_slot_shift[self.view_pattern][:],
            "audio_slot_sample_paths": self.audio_track_slot_sample_paths[self.view_pattern][:],
            "audio_slot_sample_names": self.audio_track_slot_sample_names[self.view_pattern][:],
            "audio_slot_samples": slot_samples,
            "audio_slot_channels": self.audio_track_slot_channels[self.view_pattern][:],
        }
        return True, texts.fmt(texts.backend.sequencer.pattern.copied, num=self.view_pattern + 1)

    def paste_to_current_pattern(self):
        """Paste clipboard into viewed pattern and resync playback in manual mode."""
        if not self.pattern_clipboard:
            return False, texts.backend.sequencer.pattern.clipboard_empty

        self.grid[self.view_pattern] = [row[:] for row in self.pattern_clipboard["grid"]]
        self.ratchet_grid[self.view_pattern] = [row[:] for row in self.pattern_clipboard["ratchet_grid"]]
        if "detune_grid" in self.pattern_clipboard:
            self.detune_grid[self.view_pattern] = [row[:] for row in self.pattern_clipboard["detune_grid"]]
        if "pan_grid" in self.pattern_clipboard:
            self.pan_grid[self.view_pattern] = [row[:] for row in self.pattern_clipboard["pan_grid"]]
        self.pattern_length[self.view_pattern] = max(1, min(self.max_step_count, int(self.pattern_clipboard["length"])))
        self.pattern_swing[self.view_pattern] = max(50, min(75, int(self.pattern_clipboard.get("swing", 50))))
        clip_humanize = self.pattern_clipboard.get("humanize", False)
        if isinstance(clip_humanize, bool):
            self.pattern_humanize[self.view_pattern] = clip_humanize
        else:
            try:
                self.pattern_humanize[self.view_pattern] = int(clip_humanize) > 0
            except (TypeError, ValueError):
                self.pattern_humanize[self.view_pattern] = False
        if "audio_slot_pan" in self.pattern_clipboard:
            self.audio_track_slot_pan[self.view_pattern] = self.pattern_clipboard["audio_slot_pan"][:]
        if "audio_slot_volume" in self.pattern_clipboard:
            self.audio_track_slot_volume[self.view_pattern] = self.pattern_clipboard["audio_slot_volume"][:]
        if "audio_slot_shift" in self.pattern_clipboard:
            self.audio_track_slot_shift[self.view_pattern] = self.pattern_clipboard["audio_slot_shift"][:]
        if "audio_slot_sample_paths" in self.pattern_clipboard:
            self.audio_track_slot_sample_paths[self.view_pattern] = self.pattern_clipboard["audio_slot_sample_paths"][:]
        if "audio_slot_sample_names" in self.pattern_clipboard:
            self.audio_track_slot_sample_names[self.view_pattern] = self.pattern_clipboard["audio_slot_sample_names"][:]
        if "audio_slot_samples" in self.pattern_clipboard:
            restored = []
            for sample in self.pattern_clipboard["audio_slot_samples"]:
                restored.append(None if sample is None else np.copy(sample))
            self.audio_track_slot_samples[self.view_pattern] = restored
        if "audio_slot_channels" in self.pattern_clipboard:
            self.audio_track_slot_channels[self.view_pattern] = self.pattern_clipboard["audio_slot_channels"][:]
        self.ratchet_grid[self.view_pattern][ACCENT_TRACK] = [1 for _ in range(self.max_step_count)]

        if self.step >= self.pattern_length[self.view_pattern]:
            self.step = 0

        # In manual mode, make pasted pattern the active playback pattern immediately.
        # This prevents hearing stale queued/scheduled data from another pattern.
        if not self.chain_enabled:
            self.pattern = self.view_pattern
            self.next_pattern = None
            self.step = 0
            self.pending_events.clear()
            self._sync_chain_pos_to_pattern()

        self.dirty = True
        return True, texts.fmt(texts.backend.sequencer.pattern.pasted, num=self.view_pattern + 1)

    def _parse_pattern_rows_block(self, rows):
        """Parse one 8-row text block into sequencer + ratchet grids.

        Format rules:
        - Exactly 8 rows (sequencer tracks 1..8, accent is implicit off)
        - Row width must be 1..max_step_count and equal for all rows
        - Allowed chars: 0,1,2,3,4
          - 0: empty step
          - 1: velocity 9, ratchet 1
          - 2/3/4: velocity 9, ratchet value
        """
        if not isinstance(rows, list) or len(rows) != (TRACKS - 1):
            return False, texts.fmt(texts.backend.sequencer.pattern.each_pattern_rows, rows=TRACKS - 1), None

        row_width = len(str(rows[0]).strip()) if rows else 0
        if row_width < 1 or row_width > self.max_step_count:
            return (
                False,
                texts.fmt(texts.backend.sequencer.pattern.row_width_exceeded, row_width=row_width, max_step_count=self.max_step_count),
                None,
            )

        grid = self._new_pattern_grid()
        ratchet = self._new_pattern_ratchet()
        detune = self._new_pattern_detune()
        pan = self._new_pattern_pan()
        for track in range(TRACKS - 1):
            line = str(rows[track]).strip()
            if len(line) != row_width:
                return False, texts.fmt(texts.backend.sequencer.pattern.row_exact_steps, track_num=track + 1, row_width=row_width), None
            for step, ch in enumerate(line):
                if ch not in "01234":
                    return False, texts.fmt(texts.backend.sequencer.pattern.invalid_char, char=ch, track_num=track + 1, step_num=step + 1), None
                if ch == "0":
                    grid[track][step] = 0
                    ratchet[track][step] = 1
                elif ch == "1":
                    grid[track][step] = 9
                    ratchet[track][step] = 1
                else:
                    grid[track][step] = 9
                    ratchet[track][step] = int(ch)
                detune[track][step] = 5
                pan[track][step] = 5
        grid[ACCENT_TRACK] = [0 for _ in range(self.max_step_count)]
        ratchet[ACCENT_TRACK] = [1 for _ in range(self.max_step_count)]
        detune[ACCENT_TRACK] = [5 for _ in range(self.max_step_count)]
        pan[ACCENT_TRACK] = [5 for _ in range(self.max_step_count)]
        return True, "", (grid, ratchet, detune, pan, row_width)

    def parse_patterns_from_text(self, text):
        """Parse clipboard-style text into one or more pattern payloads."""
        src = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
        lines = src.split("\n")
        blocks = []
        current = []
        for raw in lines:
            line = raw.strip()
            if not line:
                if current:
                    blocks.append(current)
                    current = []
                continue
            current.append(line)
        if current:
            blocks.append(current)

        if not blocks:
            return False, texts.backend.sequencer.pattern.clipboard_empty_or_invalid, []

        parsed = []
        for idx, block in enumerate(blocks):
            ok, message, payload = self._parse_pattern_rows_block(block)
            if not ok:
                return False, texts.fmt(texts.backend.sequencer.pattern.pattern_parse_error, pattern_num=idx + 1, message=message), []
            parsed.append(payload)
        return True, "", parsed

    def import_patterns_from_text(self, text):
        """Import clipboard text and replace full sequencer pattern step data.

        One or more blocks (separated by blank lines):
        - Replaces all pattern step data in sequencer memory.
        - Imported row width becomes each imported pattern length.
        - Rebuilds song chain sequentially from imported patterns.
        """
        ok, message, parsed = self.parse_patterns_from_text(text)
        if not ok:
            return False, message

        with self.transport_lock:
            self.playing = False
            self.engine.stop_all()
            self.pending_events.clear()
            self.pending_midi_off.clear()
            self.step = 0
            self.next_pattern = None

            count = len(parsed)
            self.grid = []
            self.ratchet_grid = []
            self.detune_grid = []
            self.pan_grid = []
            self.pattern_length = []
            self.pattern_swing = []
            self.pattern_humanize = []
            self.pattern_names = []
            for grid, ratchet, detune, pan, row_width in parsed:
                self.grid.append([row[:] for row in grid])
                self.ratchet_grid.append([row[:] for row in ratchet])
                self.detune_grid.append([row[:] for row in detune])
                self.pan_grid.append([row[:] for row in pan])
                self.pattern_length.append(max(1, min(self.max_step_count, int(row_width))))
                self.pattern_swing.append(50)
                self.pattern_humanize.append(False)
                self.pattern_names.append(self.DEFAULT_PATTERN_NAME)

            self.audio_track_slot_pan = [[5 for _ in range(TRACKS - 1)] for _ in range(count)]
            self.audio_track_slot_volume = [[9 for _ in range(TRACKS - 1)] for _ in range(count)]
            self.audio_track_slot_shift = [[12 for _ in range(TRACKS - 1)] for _ in range(count)]
            self.audio_track_slot_sample_paths = [[None for _ in range(TRACKS - 1)] for _ in range(count)]
            self.audio_track_slot_sample_names = [["-" for _ in range(TRACKS - 1)] for _ in range(count)]
            self.audio_track_slot_samples = [[None for _ in range(TRACKS - 1)] for _ in range(count)]
            self.audio_track_slot_channels = [[1 for _ in range(TRACKS - 1)] for _ in range(count)]

            self.pattern = 0
            self.view_pattern = 0
            self.chain = [i for i in range(count)]
            self.chain_pos = 0
            self.chain_enabled = count > 1
            self._sync_chain_pos_to_pattern()
            self.dirty = True
            if self.chain_enabled:
                return True, texts.fmt(texts.backend.sequencer.pattern.imported_many, count=count)
            return True, texts.backend.sequencer.pattern.imported_one

    def export_patterns_to_text(self):
        """Export all patterns as clipboard-friendly step rows.

        Output format matches `parse_patterns_from_text` expectations:
        - 8 rows per pattern (tracks 1..8, accent omitted)
        - Each row is pattern-length chars of 0/1/2/3/4
        - Empty line between patterns
        """
        blocks = []
        for p in range(self.pattern_count()):
            rows = []
            row_width = max(1, min(self.max_step_count, int(self.pattern_length[p])))
            for t in range(TRACKS - 1):
                chars = []
                for s in range(row_width):
                    vel = int(self.grid[p][t][s])
                    if vel <= 0:
                        chars.append("0")
                        continue
                    ratchet = int(self.ratchet_grid[p][t][s])
                    if ratchet < 2:
                        chars.append("1")
                    elif ratchet > 4:
                        chars.append("4")
                    else:
                        chars.append(str(ratchet))
                rows.append("".join(chars))
            blocks.append("\n".join(rows))
        return "\n\n".join(blocks)

    def import_pattern_steps_from_project(self, filename):
        """Import only step-level pattern data from another project JSON file.

        This updates sequencer step data (velocity/ratchet/detune/pan + length)
        while leaving loaded samples and non-step project settings untouched.
        """
        target = str(filename or "").strip()
        if not target:
            return False, texts.backend.sequencer.project.import_canceled

        path = target if os.path.isabs(target) else os.path.join(os.getcwd(), target)
        if not os.path.isfile(path):
            return False, texts.fmt(texts.backend.sequencer.project.project_not_found, name=os.path.basename(path))

        try:
            with open(path, "r") as f:
                data = json.load(f)
        except Exception as exc:
            return False, texts.fmt(texts.backend.sequencer.project.import_failed, error=exc)

        count = self.pattern_count()
        imported = 0

        loaded_grid = data.get("grid", [])
        loaded_ratchet = data.get("ratchet_grid", [])
        loaded_detune = data.get("detune_grid", [])
        loaded_step_pan = data.get("pan_grid", [])
        loaded_lengths = data.get("pattern_length", [])

        normalized_grid = [self._new_pattern_grid() for _ in range(count)]
        normalized_ratchet = [self._new_pattern_ratchet() for _ in range(count)]
        normalized_detune = [self._new_pattern_detune() for _ in range(count)]
        normalized_step_pan = [self._new_pattern_pan() for _ in range(count)]
        normalized_lengths = [self.default_step_count for _ in range(count)]

        for p in range(count):
            has_any_data = False
            if isinstance(loaded_grid, list) and p < len(loaded_grid) and isinstance(loaded_grid[p], list):
                has_any_data = True
                for t in range(min(TRACKS, len(loaded_grid[p]))):
                    if not isinstance(loaded_grid[p][t], list):
                        continue
                    for s in range(min(self.max_step_count, len(loaded_grid[p][t]))):
                        try:
                            value = int(loaded_grid[p][t][s])
                        except (TypeError, ValueError):
                            value = 0
                        if t == ACCENT_TRACK:
                            normalized_grid[p][t][s] = 1 if value > 0 else 0
                        else:
                            normalized_grid[p][t][s] = max(0, min(9, value))

            if isinstance(loaded_ratchet, list) and p < len(loaded_ratchet) and isinstance(loaded_ratchet[p], list):
                has_any_data = True
                for t in range(min(TRACKS, len(loaded_ratchet[p]))):
                    if not isinstance(loaded_ratchet[p][t], list):
                        continue
                    for s in range(min(self.max_step_count, len(loaded_ratchet[p][t]))):
                        try:
                            ratchet = int(loaded_ratchet[p][t][s])
                        except (TypeError, ValueError):
                            ratchet = 1
                        normalized_ratchet[p][t][s] = max(1, min(4, ratchet))
                normalized_ratchet[p][ACCENT_TRACK] = [1 for _ in range(self.max_step_count)]

            if isinstance(loaded_detune, list) and p < len(loaded_detune) and isinstance(loaded_detune[p], list):
                has_any_data = True
                for t in range(min(TRACKS, len(loaded_detune[p]))):
                    if not isinstance(loaded_detune[p][t], list):
                        continue
                    for s in range(min(self.max_step_count, len(loaded_detune[p][t]))):
                        try:
                            detune = int(loaded_detune[p][t][s])
                        except (TypeError, ValueError):
                            detune = 5
                        normalized_detune[p][t][s] = max(0, min(9, detune))
                normalized_detune[p][ACCENT_TRACK] = [5 for _ in range(self.max_step_count)]

            if isinstance(loaded_step_pan, list) and p < len(loaded_step_pan) and isinstance(loaded_step_pan[p], list):
                has_any_data = True
                for t in range(min(TRACKS, len(loaded_step_pan[p]))):
                    if not isinstance(loaded_step_pan[p][t], list):
                        continue
                    for s in range(min(self.max_step_count, len(loaded_step_pan[p][t]))):
                        try:
                            pan = int(loaded_step_pan[p][t][s])
                        except (TypeError, ValueError):
                            pan = 5
                        normalized_step_pan[p][t][s] = max(0, min(9, pan))
                normalized_step_pan[p][ACCENT_TRACK] = [5 for _ in range(self.max_step_count)]

            if isinstance(loaded_lengths, list) and p < len(loaded_lengths):
                has_any_data = True
                try:
                    normalized_lengths[p] = max(1, min(self.max_step_count, int(loaded_lengths[p])))
                except (TypeError, ValueError):
                    normalized_lengths[p] = self.default_step_count

            if has_any_data:
                imported += 1

        with self.transport_lock:
            self.playing = False
            self.engine.stop_all()
            self.pending_events.clear()
            self.pending_midi_off.clear()
            self.step = 0
            self.next_pattern = None
            self.grid = normalized_grid
            self.ratchet_grid = normalized_ratchet
            self.detune_grid = normalized_detune
            self.pan_grid = normalized_step_pan
            self.pattern_length = normalized_lengths
            self.dirty = True

        return True, texts.fmt(texts.backend.sequencer.project.imported_step_data, name=os.path.basename(path), imported=imported, count=count)

    def select_pattern(self, pattern_index):
        """Select/queue pattern depending on chain/playback mode."""
        with self.transport_lock:
            if self.pattern_count() <= 0:
                return
            pattern_index = max(0, min(self.pattern_count() - 1, int(pattern_index)))
            prev_pattern = self.pattern
            prev_view = self.view_pattern
            prev_next = self.next_pattern
            if self.chain_enabled:
                self.view_pattern = pattern_index
            elif self.playing:
                self.next_pattern = pattern_index
            else:
                self.pattern = pattern_index
                self.view_pattern = pattern_index
                self._sync_chain_pos_to_pattern()
            if self.pattern != prev_pattern or self.view_pattern != prev_view or self.next_pattern != prev_next:
                self.dirty = True

    def toggle_mute_row(self, track):
        self.muted_rows[track] = not self.muted_rows[track]

    def set_track_pan(self, track, pan):
        if track == ACCENT_TRACK:
            return
        self.seq_track_pan[track] = max(1, min(9, pan))
        self.dirty = True

    def set_track_volume(self, track, volume):
        """Set sequencer track volume (0..9)."""
        if track == ACCENT_TRACK:
            return
        self.seq_track_volume[track] = max(0, min(9, int(volume)))
        self.dirty = True

    def set_audio_track_pan(self, pattern_index, track, pan):
        """Set pan (1..9) for one track-view lane."""
        if track < 0 or track >= TRACKS - 1:
            return
        if self.audio_track_mode[track] == 1:
            self.audio_track_free_pan[track] = max(1, min(9, int(pan)))
        else:
            if pattern_index < 0 or pattern_index >= self.pattern_count():
                return
            self.audio_track_slot_pan[pattern_index][track] = max(1, min(9, int(pan)))
        self.dirty = True

    def set_audio_track_volume(self, pattern_index, track, volume):
        """Set volume (0..9) for one track-view lane."""
        if track < 0 or track >= TRACKS - 1:
            return
        if self.audio_track_mode[track] == 1:
            self.audio_track_free_volume[track] = max(0, min(9, int(volume)))
        else:
            if pattern_index < 0 or pattern_index >= self.pattern_count():
                return
            self.audio_track_slot_volume[pattern_index][track] = max(0, min(9, int(volume)))
        self.dirty = True

    def get_audio_track_mode(self, track):
        """Return track mode label for tracks view (`Pattern` or `Song`)."""
        if track < 0 or track >= TRACKS - 1:
            return texts.backend.sequencer.audio_track.mode_label_pattern
        return texts.backend.sequencer.audio_track.mode_label_song if self.audio_track_mode[track] == 1 else texts.backend.sequencer.audio_track.mode_label_pattern

    def toggle_audio_track_mode(self, pattern_index, track):
        """Toggle one tracks-view lane between Pattern and Song modes."""
        if track < 0 or track >= TRACKS - 1:
            return False, texts.backend.sequencer.sample.invalid_track
        if pattern_index < 0 or pattern_index >= self.pattern_count():
            pattern_index = max(0, min(self.pattern_count() - 1, int(pattern_index)))
        current = self.audio_track_mode[track]
        next_mode = 0 if current == 1 else 1

        # Ownership transfer rule:
        # - pattern -> song: take current viewed pattern payload as song payload
        # - song -> pattern: take current song payload and write it to viewed pattern
        # This makes the toggle target the explicit owner context.
        if next_mode == 1:
            # Move ownership from current pattern slot into song payload.
            self.audio_track_free_samples[track] = self.audio_track_slot_samples[pattern_index][track]
            self.audio_track_free_sample_paths[track] = self.audio_track_slot_sample_paths[pattern_index][track]
            self.audio_track_free_sample_names[track] = self.audio_track_slot_sample_names[pattern_index][track]
            self.audio_track_free_pan[track] = self.audio_track_slot_pan[pattern_index][track]
            self.audio_track_free_volume[track] = self.audio_track_slot_volume[pattern_index][track]
            self.audio_track_free_shift[track] = self.audio_track_slot_shift[pattern_index][track]
            self.audio_track_free_channels[track] = self.audio_track_slot_channels[pattern_index][track]
            # Clear source pattern slot so this is a true move, not copy.
            self.audio_track_slot_samples[pattern_index][track] = None
            self.audio_track_slot_sample_paths[pattern_index][track] = None
            self.audio_track_slot_sample_names[pattern_index][track] = "-"
            self.audio_track_slot_pan[pattern_index][track] = 5
            self.audio_track_slot_volume[pattern_index][track] = 9
            self.audio_track_slot_shift[pattern_index][track] = 12
            self.audio_track_slot_channels[pattern_index][track] = 1
        else:
            # Move ownership from song payload into current pattern slot.
            self.audio_track_slot_samples[pattern_index][track] = self.audio_track_free_samples[track]
            self.audio_track_slot_sample_paths[pattern_index][track] = self.audio_track_free_sample_paths[track]
            self.audio_track_slot_sample_names[pattern_index][track] = self.audio_track_free_sample_names[track]
            self.audio_track_slot_pan[pattern_index][track] = self.audio_track_free_pan[track]
            self.audio_track_slot_volume[pattern_index][track] = self.audio_track_free_volume[track]
            self.audio_track_slot_shift[pattern_index][track] = self.audio_track_free_shift[track]
            self.audio_track_slot_channels[pattern_index][track] = self.audio_track_free_channels[track]
            # Clear song payload after moving back to pattern ownership.
            self.audio_track_free_samples[track] = None
            self.audio_track_free_sample_paths[track] = None
            self.audio_track_free_sample_names[track] = "-"
            self.audio_track_free_pan[track] = 5
            self.audio_track_free_volume[track] = 9
            self.audio_track_free_shift[track] = 12
            self.audio_track_free_channels[track] = 1

        self.audio_track_mode[track] = next_mode
        self.dirty = True
        if next_mode == 1:
            return True, texts.fmt(texts.backend.sequencer.audio_track.mode_song, track_num=track + 1, pattern_num=pattern_index + 1)
        return True, texts.fmt(texts.backend.sequencer.audio_track.mode_pattern, track_num=track + 1, pattern_num=pattern_index + 1)

    def get_audio_track_name(self, pattern_index, track):
        """Return displayed sample name for a tracks-view lane."""
        if track < 0 or track >= TRACKS - 1:
            return "-"
        if self.audio_track_mode[track] == 1:
            return self.audio_track_free_sample_names[track]
        if pattern_index < 0 or pattern_index >= self.pattern_count():
            return "-"
        return self.audio_track_slot_sample_names[pattern_index][track]

    def set_audio_track_name(self, pattern_index, track, name):
        """Set displayed sample name for a tracks-view lane in its active mode."""
        if track < 0 or track >= TRACKS - 1:
            return
        text = str(name or "").strip()
        if not text:
            text = "-"
        text = text[:64]
        if self.audio_track_mode[track] == 1:
            self.audio_track_free_sample_names[track] = text
        else:
            if pattern_index < 0 or pattern_index >= self.pattern_count():
                return
            self.audio_track_slot_sample_names[pattern_index][track] = text
        self.dirty = True

    def get_audio_track_path(self, pattern_index, track):
        """Return currently active sample path for a tracks-view lane."""
        if track < 0 or track >= TRACKS - 1:
            return None
        if self.audio_track_mode[track] == 1:
            return self.audio_track_free_sample_paths[track]
        if pattern_index < 0 or pattern_index >= self.pattern_count():
            return None
        return self.audio_track_slot_sample_paths[pattern_index][track]

    def get_audio_track_pan(self, pattern_index, track):
        """Return current pan for a tracks-view lane in active mode."""
        if track < 0 or track >= TRACKS - 1:
            return 5
        if self.audio_track_mode[track] == 1:
            return self.audio_track_free_pan[track]
        if pattern_index < 0 or pattern_index >= self.pattern_count():
            return 5
        return self.audio_track_slot_pan[pattern_index][track]

    def get_audio_track_volume(self, pattern_index, track):
        """Return current volume for a tracks-view lane in active mode."""
        if track < 0 or track >= TRACKS - 1:
            return 9
        if self.audio_track_mode[track] == 1:
            return self.audio_track_free_volume[track]
        if pattern_index < 0 or pattern_index >= self.pattern_count():
            return 9
        return self.audio_track_slot_volume[pattern_index][track]

    @staticmethod
    def audio_shift_ui_to_ms(shift_ui):
        """Convert audio start shift UI value (0..50) to milliseconds (-60..+190)."""
        ui = max(0, min(50, int(shift_ui)))
        return (ui - 12) * 5

    def get_audio_track_shift(self, pattern_index, track):
        """Return current audio-track shift UI value (0..50, 12 = no shift)."""
        if track < 0 or track >= TRACKS - 1:
            return 12
        if self.audio_track_mode[track] == 1:
            return self.audio_track_free_shift[track]
        if pattern_index < 0 or pattern_index >= self.pattern_count():
            return 12
        return self.audio_track_slot_shift[pattern_index][track]

    def set_audio_track_shift(self, pattern_index, track, shift_ui):
        """Set audio-track start shift UI value (0..50, 12 = no shift)."""
        if track < 0 or track >= TRACKS - 1:
            return
        value = max(0, min(50, int(shift_ui)))
        if self.audio_track_mode[track] == 1:
            self.audio_track_free_shift[track] = value
        else:
            if pattern_index < 0 or pattern_index >= self.pattern_count():
                return
            self.audio_track_slot_shift[pattern_index][track] = value
        self.dirty = True

    def get_audio_track_channels(self, pattern_index, track):
        """Return channel count (1 or 2) for active audio track lane."""
        if track < 0 or track >= TRACKS - 1:
            return 1
        if self.audio_track_mode[track] == 1:
            return 2 if self.audio_track_free_channels[track] >= 2 else 1
        if pattern_index < 0 or pattern_index >= self.pattern_count():
            return 1
        return 2 if self.audio_track_slot_channels[pattern_index][track] >= 2 else 1

    def rename_audio_track_sample(self, pattern_index, track, new_name):
        """Rename tracks-view sample label and recording file when applicable."""
        if track < 0 or track >= TRACKS - 1:
            return False, texts.backend.sequencer.sample.invalid_track
        name = str(new_name).strip()
        if not name:
            return False, texts.backend.sequencer.sample.rename_canceled
        if not name.lower().endswith(".wav"):
            name = f"{name}.wav"

        if self.audio_track_mode[track] == 1:
            old_path = self.audio_track_free_sample_paths[track]
            old_name = self.audio_track_free_sample_names[track]
            if old_path and os.path.isfile(old_path) and os.path.isdir(os.path.dirname(old_path)):
                new_path = os.path.join(os.path.dirname(old_path), name)
                if new_path != old_path:
                    if os.path.exists(new_path):
                        return False, texts.backend.sequencer.sample.name_exists
                    try:
                        os.rename(old_path, new_path)
                        self.audio_track_free_sample_paths[track] = new_path
                    except Exception as exc:
                        return False, texts.fmt(texts.backend.sequencer.sample.rename_failed, error=exc)
            self.audio_track_free_sample_names[track] = name
            self.dirty = True
            return True, texts.fmt(texts.backend.sequencer.sample.renamed, old_name=old_name, new_name=name)

        if pattern_index < 0 or pattern_index >= self.pattern_count():
            return False, texts.backend.sequencer.audio_track.invalid_pattern
        old_path = self.audio_track_slot_sample_paths[pattern_index][track]
        old_name = self.audio_track_slot_sample_names[pattern_index][track]
        if old_path and os.path.isfile(old_path) and os.path.isdir(os.path.dirname(old_path)):
            new_path = os.path.join(os.path.dirname(old_path), name)
            if new_path != old_path:
                if os.path.exists(new_path):
                    return False, texts.backend.sequencer.sample.name_exists
                try:
                    os.rename(old_path, new_path)
                    self.audio_track_slot_sample_paths[pattern_index][track] = new_path
                except Exception as exc:
                    return False, texts.fmt(texts.backend.sequencer.sample.rename_failed, error=exc)
        self.audio_track_slot_sample_names[pattern_index][track] = name
        self.dirty = True
        return True, texts.fmt(texts.backend.sequencer.sample.renamed, old_name=old_name, new_name=name)

    def set_track_humanize(self, track, value):
        if track == ACCENT_TRACK:
            return
        self.seq_track_humanize[track] = max(0, min(100, int(value)))
        self.dirty = True

    def set_track_probability(self, track, value):
        if track == ACCENT_TRACK:
            return
        self.seq_track_probability[track] = max(0, min(9, int(value)))
        self.dirty = True

    def set_track_group(self, track, value):
        if track == ACCENT_TRACK:
            return
        self.seq_track_group[track] = max(0, min(9, int(value)))
        self.dirty = True

    def set_track_pitch(self, track, semitones):
        if track == ACCENT_TRACK:
            return
        self.seq_track_pitch[track] = max(-12, min(12, int(semitones)))
        self.dirty = True

    def set_track_pitch_ui(self, track, value_0_24):
        """Set track pitch from UI scale 0..24 where 12 means no pitch shift."""
        if track == ACCENT_TRACK:
            return
        self.set_track_pitch(track, int(value_0_24) - 12)

    def seq_shift_ui_to_ms(self, shift_ui):
        """Convert sequencer track shift UI value (0..9) to milliseconds around neutral 5."""
        ui = max(0, min(9, int(shift_ui)))
        return (ui - 5) * int(self.track_shift_step_ms)

    def set_track_shift(self, track, shift_ui):
        """Set sequencer track timing shift UI value (0..9, 5 = neutral)."""
        if track == ACCENT_TRACK:
            return
        self.seq_track_shift[track] = max(0, min(9, int(shift_ui)))
        self.dirty = True

    def preview_row(self, track):
        """Preview current track sample (or MIDI note when MIDI mode is on)."""
        if track < 0 or track >= TRACKS - 1:
            return False, texts.backend.sequencer.sample.invalid_track
        self._mark_track_trigger(track, source="seq")
        if self.midi_out_enabled:
            self._trigger_midi(track, self.last_velocity / 9.0, 0.08)
            return True, f"Preview MIDI track {track + 1}"
        else:
            group_id = self.seq_track_group[track]
            if group_id > 0:
                self.engine.choke_group(group_id, self.seq_track_group)
            vol = self.seq_track_volume[track] / 9.0
            self.engine.trigger(track, (self.last_velocity / 9.0) * vol, self.seq_track_pan[track], rate=self.pitch_rate(track))
            name = self.engine.sample_names[track] if 0 <= track < len(self.engine.sample_names) else f"Track {track + 1}"
            return True, f"Preview: {name}"

    def _preview_note_if_idle(self, track, velocity):
        if self.playing or track >= TRACKS - 1 or velocity <= 0:
            return
        self._mark_track_trigger(track, source="seq")
        if self.midi_out_enabled:
            self._trigger_midi(track, velocity / 9.0, 0.06)
        else:
            group_id = self.seq_track_group[track]
            if group_id > 0:
                self.engine.choke_group(group_id, self.seq_track_group)
            vol = self.seq_track_volume[track] / 9.0
            self.engine.trigger(track, (velocity / 9.0) * vol, self.seq_track_pan[track], rate=self.pitch_rate(track))
