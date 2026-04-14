import heapq
import json
import os
import random
import shutil
import threading
import time

import numpy as np
from scipy.io import wavfile

from audio_engine import AudioEngine, MidiOut
from config import (
    ACCENT_BOOST,
    ACCENT_TRACK,
    CHAIN_MAX_STEPS,
    MIDI_NOTES,
    PATTERNS,
    STEPS,
    TRACKS,
)

class Sequencer:
    """Pattern sequencer state, persistence, scheduling, and high-level actions."""
    def __init__(self, kit_path, pattern_path):
        self.kit_path = kit_path
        self.pattern_path = pattern_path
        self.pattern_name = os.path.basename(pattern_path)
        self.engine = AudioEngine(kit_path=self.kit_path)

        self.grid = [
            [[0 for _ in range(STEPS)] for _ in range(TRACKS)]
            for _ in range(PATTERNS)
        ]
        self.ratchet_grid = [
            [[1 for _ in range(STEPS)] for _ in range(TRACKS)]
            for _ in range(PATTERNS)
        ]

        self.pattern = 0
        self.view_pattern = 0
        self.next_pattern = None
        self.pending_events = []
        self.pending_midi_off = []
        self.chain_enabled = False
        self.chain = [0]
        self.chain_pos = 0

        self.step = 0

        self.playing = False
        self.bpm = 120
        self.steps_per_beat = 4

        self.last_velocity = 5
        self.track_pan = [5 for _ in range(TRACKS)]
        self.track_humanize = [0 for _ in range(TRACKS)]
        self.track_probability = [100 for _ in range(TRACKS)]
        self.track_group = [0 for _ in range(TRACKS)]
        self.pattern_length = [STEPS for _ in range(PATTERNS)]
        self.pattern_swing = [50 for _ in range(PATTERNS)]
        self.muted_rows = [False for _ in range(TRACKS)]
        self.pattern_clipboard = None
        self.midi = MidiOut()
        self.midi_out_enabled = False
        self.pitch_semitones = 0

        self.enter_held = False
        self.draw_mode = None

        # ---------- SAVE SYSTEM ----------
        self.dirty = False
        self.last_save_time = time.time()

        self.load()

        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    # ---------- SAVE ----------
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

    def _serialize(self):
        """Return JSON-serializable project state."""
        return {
            "bpm": self.bpm,
            "last_velocity": self.last_velocity,
            "pattern": self.pattern,
            "view_pattern": self.view_pattern,
            "grid": self.grid,
            "track_pan": self.track_pan,
            "track_humanize": self.track_humanize,
            "track_probability": self.track_probability,
            "track_group": self.track_group,
            "pattern_length": self.pattern_length,
            "pattern_swing": [self.swing_internal_to_ui(v) for v in self.pattern_swing],
            "ratchet_grid": self.ratchet_grid,
            "chain_enabled": self.chain_enabled,
            "chain": self.chain,
            "midi_out_enabled": self.midi_out_enabled,
            "pitch_semitones": self.pitch_semitones,
        }

    def _apply_loaded_data(self, data):
        """Apply and sanitize loaded project data into runtime state."""
        self.bpm = data.get("bpm", 120)
        self.last_velocity = data.get("last_velocity", 5)
        try:
            self.pattern = max(0, min(PATTERNS - 1, int(data.get("pattern", self.pattern))))
        except (TypeError, ValueError):
            self.pattern = 0
        try:
            self.view_pattern = max(0, min(PATTERNS - 1, int(data.get("view_pattern", self.pattern))))
        except (TypeError, ValueError):
            self.view_pattern = self.pattern
        self.grid = data.get("grid", self.grid)
        for p in range(PATTERNS):
            if p < len(self.grid) and ACCENT_TRACK < len(self.grid[p]):
                for s in range(min(STEPS, len(self.grid[p][ACCENT_TRACK]))):
                    self.grid[p][ACCENT_TRACK][s] = 1 if self.grid[p][ACCENT_TRACK][s] > 0 else 0
        loaded_ratchet = data.get("ratchet_grid", self.ratchet_grid)

        normalized_ratchet = [
            [[1 for _ in range(STEPS)] for _ in range(TRACKS)]
            for _ in range(PATTERNS)
        ]
        if isinstance(loaded_ratchet, list):
            for p in range(min(PATTERNS, len(loaded_ratchet))):
                if not isinstance(loaded_ratchet[p], list):
                    continue
                for t in range(min(TRACKS, len(loaded_ratchet[p]))):
                    if not isinstance(loaded_ratchet[p][t], list):
                        continue
                    for s in range(min(STEPS, len(loaded_ratchet[p][t]))):
                        try:
                            ratchet = int(loaded_ratchet[p][t][s])
                        except (ValueError, TypeError):
                            ratchet = 1
                        normalized_ratchet[p][t][s] = max(1, min(4, ratchet))
                normalized_ratchet[p][ACCENT_TRACK] = [1 for _ in range(STEPS)]
        self.ratchet_grid = normalized_ratchet

        loaded_pan = data.get("track_pan", self.track_pan)
        normalized_pan = [5 for _ in range(TRACKS)]
        if isinstance(loaded_pan, list):
            for i in range(min(TRACKS, len(loaded_pan))):
                try:
                    normalized_pan[i] = max(1, min(9, int(loaded_pan[i])))
                except (ValueError, TypeError):
                    normalized_pan[i] = 5
        normalized_pan[ACCENT_TRACK] = 5
        self.track_pan = normalized_pan

        loaded_humanize = data.get("track_humanize", self.track_humanize)
        normalized_humanize = [0 for _ in range(TRACKS)]
        if isinstance(loaded_humanize, list):
            for i in range(min(TRACKS, len(loaded_humanize))):
                try:
                    normalized_humanize[i] = max(0, min(100, int(loaded_humanize[i])))
                except (ValueError, TypeError):
                    normalized_humanize[i] = 0
        normalized_humanize[ACCENT_TRACK] = 0
        self.track_humanize = normalized_humanize

        loaded_prob = data.get("track_probability", self.track_probability)
        normalized_prob = [100 for _ in range(TRACKS)]
        if isinstance(loaded_prob, list):
            for i in range(min(TRACKS, len(loaded_prob))):
                try:
                    normalized_prob[i] = max(0, min(100, int(loaded_prob[i])))
                except (ValueError, TypeError):
                    normalized_prob[i] = 100
        normalized_prob[ACCENT_TRACK] = 100
        self.track_probability = normalized_prob

        loaded_group = data.get("track_group", self.track_group)
        normalized_group = [0 for _ in range(TRACKS)]
        if isinstance(loaded_group, list):
            for i in range(min(TRACKS, len(loaded_group))):
                try:
                    normalized_group[i] = max(0, min(9, int(loaded_group[i])))
                except (ValueError, TypeError):
                    normalized_group[i] = 0
        normalized_group[ACCENT_TRACK] = 0
        self.track_group = normalized_group

        loaded_lengths = data.get("pattern_length", self.pattern_length)
        normalized_lengths = [STEPS for _ in range(PATTERNS)]
        if isinstance(loaded_lengths, list):
            for i in range(min(PATTERNS, len(loaded_lengths))):
                try:
                    normalized_lengths[i] = max(1, min(STEPS, int(loaded_lengths[i])))
                except (ValueError, TypeError):
                    normalized_lengths[i] = STEPS
        self.pattern_length = normalized_lengths

        loaded_swing = data.get("pattern_swing", self.pattern_swing)
        normalized_swing = [50 for _ in range(PATTERNS)]
        if isinstance(loaded_swing, list):
            for i in range(min(PATTERNS, len(loaded_swing))):
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
            # - zero-based [0..PATTERNS-1] (current saves)
            # - one-based  [1..PATTERNS]   (legacy/manual edits)
            if raw:
                has_zero = any(v == 0 for v in raw)
                for value in raw:
                    idx = value if has_zero else (value - 1)
                    if 0 <= idx < PATTERNS:
                        normalized_chain.append(idx)
        if not normalized_chain:
            normalized_chain = [0]
        self.chain = normalized_chain
        raw_chain_enabled = data.get("chain_enabled", False)
        if isinstance(raw_chain_enabled, str):
            self.chain_enabled = raw_chain_enabled.strip().lower() in ["1", "true", "yes", "on"]
        else:
            self.chain_enabled = bool(raw_chain_enabled)

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
        data = self._serialize()

        with open(self.pattern_path, "w") as f:
            json.dump(data, f)

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
            return False, "Load canceled"

        if not target.lower().endswith(".json"):
            target = f"{target}.json"

        path = target if os.path.isabs(target) else os.path.join(os.getcwd(), target)
        if not os.path.exists(path):
            return False, f"Pattern not found: {os.path.basename(path)}"

        try:
            with open(path, "r") as f:
                data = json.load(f)
        except Exception as exc:
            return False, f"Load failed: {exc}"

        self._apply_loaded_data(data)
        self.pattern_path = path
        self.pattern_name = os.path.basename(path)
        self.playing = False
        self.step = 0
        self.next_pattern = None
        self.pending_events.clear()
        self.pending_midi_off.clear()
        self.dirty = False
        self._sync_chain_pos_to_pattern()
        return True, f"Loaded {self.pattern_name}"

    def save_project_file(self, filename):
        """Save pattern bank JSON to a user-provided filename."""
        target = filename.strip()
        if not target:
            return False, "Save canceled"

        if not target.lower().endswith(".json"):
            target = f"{target}.json"

        path = target if os.path.isabs(target) else os.path.join(os.getcwd(), target)
        try:
            with open(path, "w") as f:
                json.dump(self._serialize(), f)
        except Exception as exc:
            return False, f"Save failed: {exc}"

        return True, f"Saved {os.path.basename(path)}"

    def load_kit_folder(self, foldername):
        """Load a sample kit folder (first 8 alphabetical WAV files)."""
        target = foldername.strip()
        if not target:
            return False, "Load canceled"

        path = target if os.path.isabs(target) else os.path.join(os.getcwd(), target)
        if not os.path.isdir(path):
            return False, f"Kit folder not found: {os.path.basename(path)}"

        self.kit_path = path
        loaded_count = self.engine.reload_kit(path)
        return True, f"Loaded kit {os.path.basename(path)} ({loaded_count}/8 samples)"

    def load_single_sample_to_track(self, track, path):
        ok, message = self.engine.load_single_sample(track, path)
        if ok:
            self.dirty = True
        return ok, message

    def preview_sample_file(self, path, track=None):
        """Preview a sample file from browser without assigning it."""
        pan = 5
        if track is not None and 0 <= track < TRACKS - 1:
            pan = self.track_pan[track]
        return self.engine.preview_wav_file(path, velocity=self.last_velocity / 9.0, pan=pan)

    def save_pack(self, foldername):
        """Save a portable pack folder with `pattern_bank.json` plus current samples."""
        target = foldername.strip()
        if not target:
            return False, "Save pack canceled"

        pack_dir = target if os.path.isabs(target) else os.path.join(os.getcwd(), target)
        try:
            os.makedirs(pack_dir, exist_ok=True)
        except Exception as exc:
            return False, f"Pack folder create failed: {exc}"

        copied = 0
        for t in range(TRACKS - 1):
            src = self.engine.sample_paths[t] if t < len(self.engine.sample_paths) else None
            if not src or not os.path.isfile(src):
                continue
            dst = os.path.join(pack_dir, f"{t+1:02d}_{self.engine.sample_names[t]}")
            try:
                shutil.copy2(src, dst)
                copied += 1
            except Exception:
                continue

        pattern_path = os.path.join(pack_dir, "pattern_bank.json")
        try:
            with open(pattern_path, "w") as f:
                json.dump(self._serialize(), f)
        except Exception as exc:
            return False, f"Pattern save failed: {exc}"

        return True, f"Pack saved: {os.path.basename(pack_dir)} ({copied}/8 samples + pattern_bank.json)"

    def export_current_pattern_audio(self, filename):
        """Offline-render the viewed pattern as one-loop stereo WAV."""
        target = filename.strip()
        if not target:
            return False, "Audio export canceled"

        if not target.lower().endswith(".wav"):
            target = f"{target}.wav"

        path = target if os.path.isabs(target) else os.path.join(os.getcwd(), target)
        pattern = self.view_pattern
        current_length = self.pattern_length[pattern]
        sr = self.engine.sr
        base_step_time = (60.0 / self.bpm) / self.steps_per_beat
        pitch_rate = self.pitch_rate()

        def pitch_sample(sample):
            if sample is None:
                return None
            if abs(pitch_rate - 1.0) < 1e-6:
                return sample
            src_len = len(sample)
            if src_len < 2:
                return sample
            out_len = max(1, int(((src_len - 1) / pitch_rate) + 1))
            pos = np.arange(out_len, dtype=np.float32) * pitch_rate
            idx0 = np.minimum(pos.astype(np.int32), src_len - 2)
            frac = pos - idx0
            idx1 = idx0 + 1
            return ((1.0 - frac) * sample[idx0]) + (frac * sample[idx1])

        pitched_samples = [pitch_sample(self.engine.samples[t]) for t in range(TRACKS - 1)]

        step_durations = [
            self._step_duration_for(pattern, s, base_step_time)
            for s in range(current_length)
        ]
        step_starts = []
        t_cursor = 0.0
        for d in step_durations:
            step_starts.append(t_cursor)
            t_cursor += d

        # Export exactly one loop length (no extra tail after the loop end).
        total_seconds = t_cursor
        total_samples = max(1, int(total_seconds * sr))
        mix = np.zeros((total_samples, 2), dtype=np.float32)

        for s in range(current_length):
            accent_on = (
                not self.muted_rows[ACCENT_TRACK]
                and self.grid[pattern][ACCENT_TRACK][s] > 0
            )
            step_time = step_durations[s]
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

                pan_pos = (self.track_pan[t] - 1) / 8.0
                pan_l = float(np.cos(pan_pos * (np.pi / 2)))
                pan_r = float(np.sin(pan_pos * (np.pi / 2)))

                ratchet = max(1, min(4, self.ratchet_grid[pattern][t][s]))
                interval = step_time / ratchet
                for i in range(ratchet):
                    hit_t = step_starts[s] + (i * interval)
                    start = int(hit_t * sr)
                    if start >= total_samples:
                        continue
                    n = min(len(sample), total_samples - start)
                    if n <= 0:
                        continue
                    chunk = sample[:n] * v
                    mix[start:start + n, 0] += chunk * pan_l
                    mix[start:start + n, 1] += chunk * pan_r

        # Louder export: normalize peak to near full scale.
        peak = float(np.max(np.abs(mix))) if mix.size > 0 else 0.0
        if peak > 1e-9:
            out = np.clip(mix * (0.95 / peak), -1.0, 1.0)
        else:
            out = mix
        out_i16 = (out * 32767.0).astype(np.int16)
        try:
            wavfile.write(path, sr, out_i16)
        except Exception as exc:
            return False, f"Audio export failed: {exc}"
        return True, f"Exported audio: {os.path.basename(path)}"

    # ---------- AUDIO LOOP ----------
    def run(self):
        """Sequencer scheduler loop for timed triggering and autosave debounce."""
        next_time = time.perf_counter()

        while True:
            base_step_time = (60.0 / self.bpm) / self.steps_per_beat
            now = time.perf_counter()

            while self.pending_events and self.pending_events[0][0] <= now:
                _, track, vel = heapq.heappop(self.pending_events)
                if self.midi_out_enabled:
                    self._trigger_midi(track, vel, 0.05)
                else:
                    group_id = self.track_group[track] if 0 <= track < len(self.track_group) else 0
                    if group_id > 0:
                        self.engine.choke_group(group_id, self.track_group)
                    self.engine.trigger(track, vel, self.track_pan[track], rate=self.pitch_rate())

            while self.pending_midi_off and self.pending_midi_off[0][0] <= now:
                _, channel, note = heapq.heappop(self.pending_midi_off)
                self.midi.send_note_off(channel, note)

            if self.playing:
                if now >= next_time:
                    step_time = self._step_duration_for(self.pattern, self.step, base_step_time)
                    current_length = self.pattern_length[self.pattern]

                    accent_on = (
                        not self.muted_rows[ACCENT_TRACK]
                        and self.grid[self.pattern][ACCENT_TRACK][self.step] > 0
                    )

                    for t in range(TRACKS - 1):
                        if self.muted_rows[t]:
                            continue

                        vel = self.grid[self.pattern][t][self.step]

                        if vel > 0:
                            prob = self.track_probability[t]
                            if prob < 100 and (random.random() * 100.0) >= prob:
                                continue

                            v = vel / 9.0

                            if accent_on:
                                v = min(1.0, v + ACCENT_BOOST)

                            humanize = self.track_humanize[t] / 100.0
                            if humanize > 0.0:
                                vel_jitter = 1.0 + (random.uniform(-0.3, 0.3) * humanize)
                                v = max(0.0, min(1.0, v * vel_jitter))

                            ratchet = self.ratchet_grid[self.pattern][t][self.step]
                            ratchet = max(1, min(4, ratchet))
                            interval = step_time / ratchet

                            for i in range(ratchet):
                                fire_time = next_time + (i * interval)
                                if humanize > 0.0:
                                    jitter_max = min(step_time * 0.2, interval * 0.45) * humanize
                                    fire_time += random.uniform(-jitter_max, jitter_max)
                                heapq.heappush(self.pending_events, (fire_time, t, v))

                    self.step += 1

                    if self.step >= current_length:
                        self.step = 0
                        if self.chain_enabled and self.chain:
                            self.chain_pos = (self.chain_pos + 1) % len(self.chain)
                            self.pattern = self.chain[self.chain_pos]
                            self.next_pattern = None
                        elif self.next_pattern is not None:
                            self.pattern = self.next_pattern
                            self.view_pattern = self.pattern
                            self.next_pattern = None

                    next_time += step_time
            else:
                self.step = 0
                self.pending_events.clear()
                if self.pending_midi_off:
                    self.midi.all_notes_off()
                    self.pending_midi_off.clear()
                next_time = time.perf_counter()

            # ---------- AUTO SAVE (debounce) ----------
            if self.dirty and (time.time() - self.last_save_time > 1.5):
                self.save()
                self.dirty = False
                self.last_save_time = time.time()

            time.sleep(0.001)

    def toggle_playback(self):
        """Start/stop playback and clear queued/pending events on stop."""
        if not self.playing and not self.chain_enabled:
            self.pattern = self.view_pattern
            self.next_pattern = None
        self.playing = not self.playing
        if not self.playing:
            self.step = 0
            self.next_pattern = None
            self.pending_events.clear()
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
        self.chain_enabled = not self.chain_enabled
        if self.chain_enabled:
            if not self.chain:
                self.chain = [0]
            self.chain_pos = 0
            self.pattern = self.chain[0]
            self.next_pattern = None
            self.step = 0
            self.pending_events.clear()
            self.pending_midi_off.clear()
            self.dirty = True
            return True, "Chain ON"
        self.pattern = self.view_pattern
        self.next_pattern = None
        self.step = 0
        self.pending_events.clear()
        self.pending_midi_off.clear()
        self._sync_chain_pos_to_pattern()
        self.dirty = True
        return True, "Chain OFF"

    def _set_midi_out_enabled(self, enabled):
        if enabled == self.midi_out_enabled and not (enabled and self.midi.port is None):
            return True, ("MIDI OUT ON" if enabled else "MIDI OUT OFF")
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

    def pitch_rate(self):
        """Return playback rate multiplier for global semitone transpose."""
        return float(2.0 ** (self.pitch_semitones / 12.0))

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

    def set_chain_from_text(self, text):
        """Parse text chain input (e.g. `1 2 3 2`) and store it."""
        src = text.strip()
        if not src:
            return False, "Chain canceled"

        values = []
        for ch in src:
            if ch in [" ", ",", "-", ">"]:
                continue
            if not ch.isdigit():
                return False, "Invalid chain (use 1-4 with spaces/commas)"
            n = int(ch)
            if n < 1 or n > PATTERNS:
                return False, "Invalid chain (pattern range 1-4)"
            values.append(n - 1)

        if not values:
            return False, "Invalid chain (empty)"

        if len(values) > CHAIN_MAX_STEPS:
            values = values[:CHAIN_MAX_STEPS]
            clipped = True
        else:
            clipped = False

        self.chain = values
        self.chain_enabled = True
        self._sync_chain_pos_to_pattern()
        self.dirty = True
        if clipped:
            return True, f"Chain set (max {CHAIN_MAX_STEPS} steps)"
        return True, "Chain set"

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
        """Increase or decrease viewed pattern length within 1..16."""
        current = self.pattern_length[self.view_pattern]
        new_length = max(1, min(STEPS, current + delta))
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

    def set_current_pattern_swing_from_text(self, text):
        src = text.strip()
        if not src:
            return False, "Swing canceled"
        try:
            value = int(src)
        except ValueError:
            return False, "Swing must be a number (0-10)"
        if value < 0 or value > 10:
            return False, "Swing out of range (0-10)"
        self.set_current_pattern_swing_ui(value)
        return True, f"Swing set to {value}"

    def change_bpm(self, delta):
        self.bpm = max(1, self.bpm + delta)
        self.dirty = True

    def set_last_velocity(self, velocity):
        self.last_velocity = max(1, min(9, velocity))
        self.dirty = True

    def set_step_velocity(self, track, step, velocity):
        """Set step velocity (or accent on/off), with idle preview on note create."""
        prev = self.grid[self.view_pattern][track][step]
        if track == ACCENT_TRACK:
            self.grid[self.view_pattern][track][step] = 1 if velocity > 0 else 0
        else:
            self.grid[self.view_pattern][track][step] = max(0, min(9, velocity))
            new_val = self.grid[self.view_pattern][track][step]
            if prev == 0 and new_val > 0:
                self._preview_note_if_idle(track, new_val)
        self.dirty = True

    def set_step_ratchet(self, track, step, ratchet):
        if track == ACCENT_TRACK:
            return
        self.ratchet_grid[self.view_pattern][track][step] = max(1, min(4, ratchet))
        self.dirty = True

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
            [0 for _ in range(STEPS)] for _ in range(TRACKS)
        ]
        self.ratchet_grid[self.view_pattern] = [
            [1 for _ in range(STEPS)] for _ in range(TRACKS)
        ]
        self.ratchet_grid[self.view_pattern][ACCENT_TRACK] = [1 for _ in range(STEPS)]
        self.dirty = True

    def copy_current_pattern(self):
        """Copy viewed pattern into internal clipboard."""
        self.pattern_clipboard = {
            "grid": [row[:] for row in self.grid[self.view_pattern]],
            "ratchet_grid": [row[:] for row in self.ratchet_grid[self.view_pattern]],
            "length": self.pattern_length[self.view_pattern],
        }
        return True, f"Copied pattern {self.view_pattern + 1}"

    def paste_to_current_pattern(self):
        """Paste clipboard into viewed pattern and resync playback in manual mode."""
        if not self.pattern_clipboard:
            return False, "Clipboard empty"

        self.grid[self.view_pattern] = [row[:] for row in self.pattern_clipboard["grid"]]
        self.ratchet_grid[self.view_pattern] = [row[:] for row in self.pattern_clipboard["ratchet_grid"]]
        self.pattern_length[self.view_pattern] = max(1, min(STEPS, int(self.pattern_clipboard["length"])))
        self.ratchet_grid[self.view_pattern][ACCENT_TRACK] = [1 for _ in range(STEPS)]

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
        return True, f"Pasted pattern {self.view_pattern + 1}"

    def select_pattern(self, pattern_index):
        """Select/queue pattern depending on chain/playback mode."""
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
        self.track_pan[track] = max(1, min(9, pan))
        self.dirty = True

    def set_track_humanize(self, track, value):
        if track == ACCENT_TRACK:
            return
        self.track_humanize[track] = max(0, min(100, int(value)))
        self.dirty = True

    def set_track_probability(self, track, value):
        if track == ACCENT_TRACK:
            return
        self.track_probability[track] = max(0, min(100, int(value)))
        self.dirty = True

    def set_track_group(self, track, value):
        if track == ACCENT_TRACK:
            return
        self.track_group[track] = max(0, min(9, int(value)))
        self.dirty = True

    def preview_row(self, track):
        """Preview current track sample (or MIDI note when MIDI mode is on)."""
        if track >= TRACKS - 1:
            return
        if self.midi_out_enabled:
            self._trigger_midi(track, self.last_velocity / 9.0, 0.08)
        else:
            group_id = self.track_group[track]
            if group_id > 0:
                self.engine.choke_group(group_id, self.track_group)
            self.engine.trigger(track, self.last_velocity / 9.0, self.track_pan[track], rate=self.pitch_rate())

    def _preview_note_if_idle(self, track, velocity):
        if self.playing or track >= TRACKS - 1 or velocity <= 0:
            return
        if self.midi_out_enabled:
            self._trigger_midi(track, velocity / 9.0, 0.06)
        else:
            group_id = self.track_group[track]
            if group_id > 0:
                self.engine.choke_group(group_id, self.track_group)
            self.engine.trigger(track, velocity / 9.0, self.track_pan[track], rate=self.pitch_rate())

