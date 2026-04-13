import numpy as np
import sounddevice as sd
import time
import threading
import os
import curses
import json
import argparse
import heapq
import configparser
import warnings
import shutil
from scipy.io import wavfile
try:
    import mido
except Exception:
    mido = None

TRACKS = 9
STEPS = 16
CHAIN_MAX_STEPS = 16
PAN_COL = STEPS
LOAD_COL = STEPS + 1
GRID_COLS = STEPS + 2
PATTERNS = 4
DEFAULT_KIT_PATH = "kit1"
DEFAULT_PATTERN_NAME = "patterns"
KEYMAP_PATH = "keymap.ini"

ACCENT_TRACK = 8
ACCENT_BOOST = 0.35

DEFAULT_KEYMAP = {
    "help_menu": "H,F1",
    "page_menu": "F2",
    "mode_toggle": "T",
    "clear_pattern": "N",
    "pattern_copy": "B",
    "pattern_paste": "V",
    "mute_row": "M",
    "tempo_inc": "U",
    "tempo_dec": "J",
    "chain_toggle": "G",
    "chain_edit": "C",
    "pattern_length_dec": "[",
    "pattern_length_inc": "]",
    "pattern_export": "X",
    "pattern_load": "L",
    "kit_load": "K",
    "pattern_1": "Q",
    "pattern_2": "W",
    "pattern_3": "E",
    "pattern_4": "R",
}

PAGE_MENU_ITEMS = [
    "1. Copy Page",
    "2. Paste Page",
    "3. Erase Page",
    "4. Save Pattern As",
    "5. Load Pattern",
    "6. Load Sample Kit",
    "7. Toggle Chain Mode",
    "8. Set Swing",
    "9. Save Pack",
    "10. Toggle MIDI OUT",
]

MIDI_NOTES = [36, 37, 38, 39, 40, 41, 42, 43]


def _normalize_key_token(token):
    token = token.strip()
    if not token:
        return None

    upper = token.upper()
    if upper.startswith("CODE:"):
        try:
            code = int(token.split(":", 1)[1].strip())
            return f"CODE:{code}"
        except ValueError:
            return None

    if upper.startswith("CHAR:"):
        value = token.split(":", 1)[1]
        if len(value) == 0:
            return None
        return f"CHAR:{value}"

    if len(token) == 1:
        return f"CHAR:{token}"

    return upper


def _event_tokens(key):
    tokens = set()

    if isinstance(key, str):
        if key:
            tokens.add(f"CHAR:{key}")
            if len(key) == 1 and key.isalpha():
                tokens.add(f"CHAR:{key.lower()}")
                tokens.add(f"CHAR:{key.upper()}")

            if key == " ":
                tokens.add("SPACE")
            elif key in ["\n", "\r"]:
                tokens.add("ENTER")
            elif key == "\t":
                tokens.add("TAB")
    else:
        key_code = key
        tokens.add(f"CODE:{key_code}")

        if key_code == 27:
            tokens.add("ESC")
        elif key_code in [10, 13, curses.KEY_ENTER]:
            tokens.add("ENTER")
        elif key_code == curses.KEY_UP:
            tokens.add("UP")
        elif key_code == curses.KEY_DOWN:
            tokens.add("DOWN")
        elif key_code == curses.KEY_LEFT:
            tokens.add("LEFT")
        elif key_code == curses.KEY_RIGHT:
            tokens.add("RIGHT")
        elif key_code == 32:
            tokens.add("SPACE")

        key_f0 = getattr(curses, "KEY_F0", None)
        if key_f0 is not None and isinstance(key_code, int):
            f_index = key_code - key_f0
            if 1 <= f_index <= 12:
                tokens.add(f"F{f_index}")
        else:
            for i in range(1, 13):
                key_fi = getattr(curses, f"KEY_F{i}", None)
                if key_fi is not None and key_code == key_fi:
                    tokens.add(f"F{i}")
                    break

    return tokens


class Keymap:
    def __init__(self, path=KEYMAP_PATH):
        self.path = path
        self.bindings = {}
        self.load()

    def _parse_binding(self, raw_value, fallback):
        raw_parts = [part.strip() for part in raw_value.split(",")]
        tokens = []
        for part in raw_parts:
            normalized = _normalize_key_token(part)
            if normalized is not None:
                tokens.append(normalized)

        if tokens:
            return tokens

        fallback_token = _normalize_key_token(fallback)
        return [fallback_token] if fallback_token is not None else []

    def load(self):
        parser = configparser.ConfigParser()

        if not os.path.exists(self.path):
            parser["keys"] = DEFAULT_KEYMAP
            with open(self.path, "w") as f:
                parser.write(f)

        parser.read(self.path)
        section = parser["keys"] if "keys" in parser else {}

        for action, fallback in DEFAULT_KEYMAP.items():
            raw_value = section.get(action, fallback)
            self.bindings[action] = self._parse_binding(raw_value, fallback)

    def matches(self, action, event_tokens):
        action_tokens = self.bindings.get(action, [])
        return any(token in event_tokens for token in action_tokens)

    def label(self, action):
        action_tokens = self.bindings.get(action, [])
        if not action_tokens:
            return "?"

        token = action_tokens[0]
        if token.startswith("CHAR:"):
            return token.split(":", 1)[1]
        if token.startswith("CODE:"):
            return token
        return token

    def file_lines(self):
        if not os.path.exists(self.path):
            return ["[keys]"]
        lines = []
        try:
            with open(self.path, "r") as f:
                for line in f:
                    lines.append(line.rstrip("\n"))
        except Exception:
            return ["[keys]"]
        return lines if lines else ["[keys]"]

# ---------- VOICE ----------
class Voice:
    def __init__(self):
        self.active = False
        self.data = None
        self.pos = 0
        self.vel = 1.0
        self.pan_l = 1.0
        self.pan_r = 1.0


class MidiOut:
    def __init__(self):
        self.port = None
        self.port_name = None

    def enable(self):
        if mido is None:
            return False, "MIDI unavailable (install mido + python-rtmidi)"
        try:
            names = mido.get_output_names()
        except Exception as exc:
            return False, f"MIDI enumerate failed: {exc}"
        if not names:
            return False, "No MIDI output ports found"
        try:
            self.port = mido.open_output(names[0])
            self.port_name = names[0]
        except Exception as exc:
            self.port = None
            self.port_name = None
            return False, f"MIDI open failed: {exc}"
        return True, f"MIDI OUT ON ({self.port_name})"

    def disable(self):
        if self.port is not None:
            try:
                self.port.close()
            except Exception:
                pass
        self.port = None
        self.port_name = None
        return True, "MIDI OUT OFF"

    def send_note_on(self, channel, note, velocity):
        if self.port is None or mido is None:
            return
        try:
            self.port.send(mido.Message("note_on", channel=channel, note=note, velocity=velocity))
        except Exception:
            pass

    def send_note_off(self, channel, note):
        if self.port is None or mido is None:
            return
        try:
            self.port.send(mido.Message("note_off", channel=channel, note=note, velocity=0))
        except Exception:
            pass

    def all_notes_off(self):
        if self.port is None or mido is None:
            return
        for ch in range(8):
            try:
                self.port.send(mido.Message("control_change", channel=ch, control=123, value=0))
            except Exception:
                pass

# ---------- AUDIO ENGINE ----------
class AudioEngine:
    def __init__(self, kit_path, samplerate=44100, blocksize=512):
        self.sr = samplerate
        self.blocksize = blocksize
        self.kit_path = kit_path

        self.mix = np.zeros((blocksize, 2), dtype=np.float32)
        self.voices = [Voice() for _ in range(32)]

        self.event_buffer = [None] * 1024
        self.event_write = 0
        self.event_read = 0

        self.samples, self.sample_names, self.sample_paths = self.load_samples()

        self.stream = sd.OutputStream(
            samplerate=self.sr,
            blocksize=self.blocksize,
            channels=2,
            callback=self.audio_callback,
            latency='high'
        )
        self.stream.start()

    def load_samples(self):
        sample_files = []
        if os.path.isdir(self.kit_path):
            sample_files = [
                os.path.join(self.kit_path, name)
                for name in sorted(os.listdir(self.kit_path), key=str.lower)
                if os.path.isfile(os.path.join(self.kit_path, name))
                and name.lower().endswith(".wav")
            ]

        samples = []
        sample_names = []
        sample_paths = []

        for i in range(TRACKS - 1):
            if i >= len(sample_files):
                samples.append(None)
                sample_names.append("-")
                sample_paths.append(None)
                continue

            path = sample_files[i]
            data = self._read_wav_mono(path)

            samples.append(data)
            sample_names.append(os.path.basename(path))
            sample_paths.append(path)

        samples.append(None)
        sample_names.append("Accent")
        sample_paths.append(None)
        return samples, sample_names, sample_paths

    def reload_kit(self, kit_path):
        self.kit_path = kit_path
        self.samples, self.sample_names, self.sample_paths = self.load_samples()
        self.stop_all()
        loaded_count = sum(1 for s in self.samples[:TRACKS - 1] if s is not None)
        return loaded_count

    def _read_wav_mono(self, path):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", wavfile.WavFileWarning)
            _, data = wavfile.read(path)

        if data.dtype == np.int16:
            data = data.astype(np.float32) / 32768.0
        elif data.dtype == np.int32:
            data = data.astype(np.float32) / 2147483648.0
        else:
            data = data.astype(np.float32)

        if len(data.shape) == 2:
            data = data.mean(axis=1)
        return data

    def load_single_sample(self, track, path):
        if track < 0 or track >= TRACKS - 1:
            return False, "Invalid track"
        if not os.path.isfile(path) or not path.lower().endswith(".wav"):
            return False, "Select a .wav file"
        try:
            data = self._read_wav_mono(path)
        except Exception as exc:
            return False, f"Sample load failed: {exc}"

        self.samples[track] = data
        self.sample_names[track] = os.path.basename(path)
        self.sample_paths[track] = path
        self.stop_all()
        return True, f"Loaded {self.sample_names[track]} on track {track + 1}"

    def stop_all(self):
        for v in self.voices:
            v.active = False

    def trigger(self, track, velocity, pan):
        pan_pos = (pan - 1) / 8.0
        left_gain = float(np.cos(pan_pos * (np.pi / 2)))
        right_gain = float(np.sin(pan_pos * (np.pi / 2)))

        idx = self.event_write % len(self.event_buffer)
        self.event_buffer[idx] = (track, velocity, left_gain, right_gain)
        self.event_write += 1

    def audio_callback(self, outdata, frames, time_info, status):
        mix = self.mix
        mix[:, :] = 0.0

        while self.event_read != self.event_write:
            idx = self.event_read % len(self.event_buffer)
            event = self.event_buffer[idx]

            if event:
                track, vel, pan_l, pan_r = event
                sample = self.samples[track]

                if sample is not None:
                    for v in self.voices:
                        if not v.active:
                            v.active = True
                            v.data = sample
                            v.pos = 0
                            v.vel = vel
                            v.pan_l = pan_l
                            v.pan_r = pan_r
                            break

            self.event_read += 1

        for v in self.voices:
            if not v.active:
                continue

            end = v.pos + frames
            chunk = v.data[v.pos:end]

            n = len(chunk)
            scaled = chunk * v.vel
            mix[:n, 0] += scaled * v.pan_l
            mix[:n, 1] += scaled * v.pan_r

            v.pos += frames

            if v.pos >= len(v.data):
                v.active = False

        outdata[:] = mix * 0.25

# ---------- SEQUENCER ----------
class Sequencer:
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
        self.pattern_length = [STEPS for _ in range(PATTERNS)]
        self.pattern_swing = [50 for _ in range(PATTERNS)]
        self.muted_rows = [False for _ in range(TRACKS)]
        self.page_clipboard = None
        self.midi = MidiOut()
        self.midi_out_enabled = False

        self.enter_held = False
        self.draw_mode = None

        # ---------- SAVE SYSTEM ----------
        self.dirty = False
        self.last_save_time = time.time()

        self.load()

        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    # ---------- SAVE ----------
    def _serialize(self):
        return {
            "bpm": self.bpm,
            "last_velocity": self.last_velocity,
            "grid": self.grid,
            "track_pan": self.track_pan,
            "pattern_length": self.pattern_length,
            "pattern_swing": self.pattern_swing,
            "ratchet_grid": self.ratchet_grid,
            "chain_enabled": self.chain_enabled,
            "chain": self.chain,
            "midi_out_enabled": self.midi_out_enabled,
        }

    def _apply_loaded_data(self, data):
        self.bpm = data.get("bpm", 120)
        self.last_velocity = data.get("last_velocity", 5)
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
                    normalized_swing[i] = max(50, min(75, int(loaded_swing[i])))
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
        self._sync_chain_pos_to_pattern()

    def save(self):
        data = self._serialize()

        with open(self.pattern_path, "w") as f:
            json.dump(data, f)

    def load(self):
        if not os.path.exists(self.pattern_path):
            self.save()
            return

        with open(self.pattern_path, "r") as f:
            data = json.load(f)

        self._apply_loaded_data(data)

    def load_project_file(self, filename):
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
        self.view_pattern = self.pattern
        self.playing = False
        self.step = 0
        self.next_pattern = None
        self.pending_events.clear()
        self.pending_midi_off.clear()
        self.dirty = False
        self._sync_chain_pos_to_pattern()
        return True, f"Loaded {self.pattern_name}"

    def save_project_file(self, filename):
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

    def save_pack(self, foldername):
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

        pattern_path = os.path.join(pack_dir, "pattern.json")
        try:
            with open(pattern_path, "w") as f:
                json.dump(self._serialize(), f)
        except Exception as exc:
            return False, f"Pattern save failed: {exc}"

        return True, f"Pack saved: {os.path.basename(pack_dir)} ({copied}/8 samples + pattern.json)"

    # ---------- AUDIO LOOP ----------
    def run(self):
        next_time = time.perf_counter()

        while True:
            base_step_time = (60.0 / self.bpm) / self.steps_per_beat
            now = time.perf_counter()

            while self.pending_events and self.pending_events[0][0] <= now:
                _, track, vel = heapq.heappop(self.pending_events)
                if self.midi_out_enabled:
                    self._trigger_midi(track, vel, 0.05)
                else:
                    self.engine.trigger(track, vel, self.track_pan[track])

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
                            v = vel / 9.0

                            if accent_on:
                                v = min(1.0, v + ACCENT_BOOST)

                            ratchet = self.ratchet_grid[self.pattern][t][self.step]
                            ratchet = max(1, min(4, ratchet))
                            interval = step_time / ratchet

                            for i in range(ratchet):
                                fire_time = next_time + (i * interval)
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
        return self._set_midi_out_enabled(not self.midi_out_enabled)

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

    def set_current_pattern_swing(self, value):
        swing = max(50, min(75, int(value)))
        if self.pattern_swing[self.view_pattern] != swing:
            self.pattern_swing[self.view_pattern] = swing
            self.dirty = True

    def set_current_pattern_swing_from_text(self, text):
        src = text.strip()
        if not src:
            return False, "Swing canceled"
        try:
            value = int(src)
        except ValueError:
            return False, "Swing must be a number (50-75)"
        if value < 50 or value > 75:
            return False, "Swing out of range (50-75)"
        self.set_current_pattern_swing(value)
        return True, f"Swing set to {value}"

    def change_bpm(self, delta):
        self.bpm = max(1, self.bpm + delta)
        self.dirty = True

    def set_last_velocity(self, velocity):
        self.last_velocity = max(1, min(9, velocity))
        self.dirty = True

    def set_step_velocity(self, track, step, velocity):
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
        self.grid[self.view_pattern] = [
            [0 for _ in range(STEPS)] for _ in range(TRACKS)
        ]
        self.ratchet_grid[self.view_pattern] = [
            [1 for _ in range(STEPS)] for _ in range(TRACKS)
        ]
        self.ratchet_grid[self.view_pattern][ACCENT_TRACK] = [1 for _ in range(STEPS)]
        self.dirty = True

    def copy_current_page(self):
        self.page_clipboard = {
            "grid": [row[:] for row in self.grid[self.view_pattern]],
            "ratchet_grid": [row[:] for row in self.ratchet_grid[self.view_pattern]],
            "length": self.pattern_length[self.view_pattern],
        }
        return True, f"Copied page {self.view_pattern + 1}"

    def paste_to_current_page(self):
        if not self.page_clipboard:
            return False, "Clipboard empty"

        self.grid[self.view_pattern] = [row[:] for row in self.page_clipboard["grid"]]
        self.ratchet_grid[self.view_pattern] = [row[:] for row in self.page_clipboard["ratchet_grid"]]
        self.pattern_length[self.view_pattern] = max(1, min(STEPS, int(self.page_clipboard["length"])))
        self.ratchet_grid[self.view_pattern][ACCENT_TRACK] = [1 for _ in range(STEPS)]

        if self.step >= self.pattern_length[self.view_pattern]:
            self.step = 0

        # In manual mode, make pasted page the active playback page immediately.
        # This prevents hearing stale queued/scheduled data from another page.
        if not self.chain_enabled:
            self.pattern = self.view_pattern
            self.next_pattern = None
            self.step = 0
            self.pending_events.clear()
            self._sync_chain_pos_to_pattern()

        self.dirty = True
        return True, f"Pasted to page {self.view_pattern + 1}"

    def select_pattern(self, pattern_index):
        if self.chain_enabled:
            self.view_pattern = pattern_index
        elif self.playing:
            self.next_pattern = pattern_index
        else:
            self.pattern = pattern_index
            self.view_pattern = pattern_index
            self._sync_chain_pos_to_pattern()

    def toggle_mute_row(self, track):
        self.muted_rows[track] = not self.muted_rows[track]

    def set_track_pan(self, track, pan):
        if track == ACCENT_TRACK:
            return
        self.track_pan[track] = max(1, min(9, pan))
        self.dirty = True

    def preview_row(self, track):
        if track >= TRACKS - 1:
            return
        if self.midi_out_enabled:
            self._trigger_midi(track, self.last_velocity / 9.0, 0.08)
        else:
            self.engine.trigger(track, self.last_velocity / 9.0, self.track_pan[track])

    def _preview_note_if_idle(self, track, velocity):
        if self.playing or track >= TRACKS - 1 or velocity <= 0:
            return
        if self.midi_out_enabled:
            self._trigger_midi(track, velocity / 9.0, 0.06)
        else:
            self.engine.trigger(track, velocity / 9.0, self.track_pan[track])

# ---------- UI ----------
def draw(
    stdscr,
    seq,
    cursor_x,
    cursor_y,
    edit_mode,
    clear_confirm,
    pattern_load_prompt,
    status_message,
    page_menu_active,
    page_menu_index,
    page_menu_key_label,
    help_active,
    help_lines,
    help_key_label,
    file_browser_active,
    file_browser_mode,
    file_browser_path,
    file_browser_items,
    file_browser_index,
    mode_key_label,
    clear_key_label,
    length_dec_label,
    length_inc_label,
    theme
):
    stdscr.clear()
    h, w = stdscr.getmaxyx()

    def safe_add(y, x, text, attr=0):
        if y < 0 or y >= h or x < 0 or x >= w:
            return
        max_len = w - x
        if max_len <= 0:
            return
        if y == h - 1 and x + len(text) >= w:
            text = text[:max(0, w - x - 1)]
        else:
            text = text[:max_len]
        if not text:
            return
        try:
            if attr:
                stdscr.addstr(y, x, text, attr)
            else:
                stdscr.addstr(y, x, text)
        except curses.error:
            pass

    def draw_hline(y, x0, x1, ch="-", attr=0):
        if y < 0 or y >= h or x0 > x1:
            return
        x0 = max(0, x0)
        x1 = min(w - 1, x1)
        safe_add(y, x0, ch * (x1 - x0 + 1), attr)

    def draw_box(x0, y0, x1, y1, attr=0):
        if x0 >= x1 or y0 >= y1:
            return
        if x0 < 0 or y0 < 0 or x1 >= w or y1 >= h:
            return
        draw_hline(y0, x0 + 1, x1 - 1, "─", attr)
        draw_hline(y1, x0 + 1, x1 - 1, "─", attr)
        safe_add(y0, x0, "╭", attr)
        safe_add(y0, x1, "╮", attr)
        safe_add(y1, x0, "╰", attr)
        safe_add(y1, x1, "╯", attr)
        for y in range(y0 + 1, y1):
            safe_add(y, x0, "│", attr)
            safe_add(y, x1, "│", attr)

    if h < 16 or w < 80:
        safe_add(0, 0, "Terminal too small for outlined layout")
        stdscr.refresh()
        return

    outer_left = 0
    outer_top = 0
    outer_right = w - 1
    outer_bottom = h - 1
    draw_box(outer_left, outer_top, outer_right, outer_bottom, theme["frame"])

    header_left = 2
    header_right = w - 3
    header_top = 1
    header_bottom = 6
    draw_box(header_left, header_top, header_right, header_bottom, theme["frame"])

    grid_left = 2
    grid_right = w - 3
    grid_top = 7
    grid_bottom = h - 2
    draw_box(grid_left, grid_top, grid_right, grid_bottom, theme["frame"])

    content_x = header_left + 2
    status = "PLAY" if seq.playing else "STOP"
    beat = (seq.step // 4) + 1
    mode = "RATCHET" if edit_mode == "ratchet" else "VELOCITY"

    safe_add(2, content_x, "DR. MULPERI", theme["title"])
    kit_name = os.path.basename(os.path.normpath(seq.kit_path))
    safe_add(
        3,
        content_x,
        f"PATTERN FILE: {seq.pattern_name}  KIT: {kit_name}"[:header_right - content_x],
        theme["text"]
    )
    midi_text = "MIDI OUT"
    midi_attr = theme["midi_on"] if seq.midi_out_enabled else theme["midi_off"]
    midi_x = header_right - len(midi_text) - 1
    safe_add(3, midi_x, midi_text, midi_attr)
    safe_add(
        4,
        content_x,
        (
            f"BPM:{seq.bpm}  {status}  {beat}/4  "
            f"LEN:{seq.pattern_length[seq.view_pattern]} ({length_dec_label}/{length_inc_label})  "
            f"SW:{seq.pattern_swing[seq.view_pattern]}  "
            f"MODE:{mode} ({mode_key_label} to switch)  "
            f"MENU:{page_menu_key_label}"
        )[:header_right - content_x],
        theme["text"]
    )

    pattern_line = "PATTERN: "
    queue_flash_on = int(time.time() * 2) % 2 == 0
    for i in range(PATTERNS):
        if seq.view_pattern == i:
            pattern_line += f"[{i+1}] "
        elif (not seq.chain_enabled) and seq.playing and seq.next_pattern == i:
            pattern_line += f"({i+1}) " if queue_flash_on else f" {i+1}  "
        else:
            pattern_line += f" {i+1}  "

    pattern_attr = theme["pattern_manual"] if not seq.chain_enabled else theme["pattern_chain_off"]
    safe_add(5, content_x, pattern_line[:header_right - content_x], pattern_attr)

    chain_text = f"CHAIN:{seq.chain_display()}"
    chain_attr = theme["chain_on"] if seq.chain_enabled else theme["chain_off"]
    chain_x = content_x + len(pattern_line) + 2
    safe_add(5, chain_x, chain_text[:header_right - chain_x], chain_attr)

    grid_content_x = grid_left + 2
    playhead_y = grid_top + 1
    current_length = seq.pattern_length[seq.view_pattern]
    show_playhead = seq.playing and (seq.view_pattern == seq.pattern)
    x = grid_content_x
    safe_add(playhead_y, x, "  ", theme["text"])
    x += 2
    for s in range(GRID_COLS):
        sep = "  "
        sep_attr = theme["divider"]
        if s == current_length and s < STEPS:
            sep = "| "
            sep_attr = theme["hint"]
        elif s == PAN_COL or s == LOAD_COL:
            sep = "| "

        safe_add(playhead_y, x, sep, sep_attr)
        x += len(sep)
        if s == LOAD_COL:
            body = "      "
        else:
            body = "  v  " if show_playhead and s == seq.step else "     "
        body_attr = theme["playhead"] if show_playhead and s == seq.step else theme["muted"]
        safe_add(playhead_y, x, body, body_attr)
        x += len(body)

    row_start = grid_top + 2
    for t in range(TRACKS):
        y = row_start + t
        if y >= grid_bottom:
            continue

        row_attr = theme["accent"] if t == ACCENT_TRACK else theme["text"]
        if seq.muted_rows[t]:
            row_attr = theme["muted"]

        x = grid_content_x
        row_label = "A " if t == ACCENT_TRACK else f"{t+1} "
        safe_add(y, x, row_label, row_attr)
        x += len(row_label)

        def velocity_attr(value):
            if value <= 0:
                return theme["muted"]
            if value < 4:
                return theme["velocity_low"]
            return theme["velocity_high"]

        for s in range(GRID_COLS):
            if s == PAN_COL:
                if t == ACCENT_TRACK:
                    char = ""
                else:
                    pan_val = seq.track_pan[t]
                    char = f"P{pan_val}"
                cell_attr = row_attr
            elif s == LOAD_COL:
                char = "LOAD" if t != ACCENT_TRACK else ""
                cell_attr = row_attr
            else:
                val = seq.grid[seq.view_pattern][t][s]
                ratchet = seq.ratchet_grid[seq.view_pattern][t][s]
                if val == 0:
                    char = "."
                elif ratchet > 1:
                    char = f"{val}x{ratchet}"
                else:
                    char = str(val)
                if t == ACCENT_TRACK:
                    cell_attr = theme["accent"] | (curses.A_BOLD if val > 0 else 0)
                else:
                    cell_attr = velocity_attr(val)

                if s >= seq.pattern_length[seq.view_pattern]:
                    cell_attr = theme["muted"]

            sep = "| " if s == PAN_COL or s == LOAD_COL or (s < STEPS and s % 4 == 0) else "  "
            safe_add(y, x, sep, theme["divider"])
            x += len(sep)
            cell_w = 4 if s == LOAD_COL else 3
            body = f"[{char:>{cell_w}}]" if cursor_x == s and cursor_y == t else f" {char:>{cell_w}} "
            if cursor_x == s and cursor_y == t:
                cell_attr = cell_attr | curses.A_REVERSE
            safe_add(y, x, body, cell_attr)
            x += len(body)

        mute_mark = "M" if seq.muted_rows[t] else " "
        safe_add(y, x, f" {mute_mark}", row_attr)

    prompt_line = ""
    if cursor_y < TRACKS - 1:
        sample_line = f"SAMPLE: {seq.engine.sample_names[cursor_y]}  (P preview, Enter on L to load)"
    else:
        sample_line = "SAMPLE: Accent track (no sample file)"

    if clear_confirm:
        prompt_line = f"Clear current pattern? Press {clear_key_label} again to confirm."
    elif pattern_load_prompt:
        prompt_line = pattern_load_prompt
    elif status_message:
        prompt_line = f"{status_message} | {sample_line}"
    else:
        prompt_line = sample_line

    if prompt_line:
        prompt_y = row_start + TRACKS
        if prompt_y < grid_bottom:
            safe_add(prompt_y, grid_content_x, prompt_line[:grid_right - grid_content_x], theme["hint"])
        else:
            safe_add(5, content_x, prompt_line[:header_right - content_x], theme["hint"])

    if help_active:
        visible_lines = [line for line in help_lines if line.strip() != ""]
        if not visible_lines:
            visible_lines = ["[keys]"]

        header = f"HELP ({help_key_label}/Esc to close)"
        content = [header, ""] + visible_lines
        max_line_len = max(len(line) for line in content)
        box_width = min(w - 6, max(40, max_line_len + 4))
        box_height = min(h - 6, len(content) + 3)
        box_left = max(1, (w - box_width) // 2)
        box_top = max(1, (h - box_height) // 2)
        box_right = box_left + box_width - 1
        box_bottom = box_top + box_height - 1

        draw_box(box_left, box_top, box_right, box_bottom, theme["frame"])
        line_y = box_top + 1
        for i, line in enumerate(content):
            if line_y + i >= box_bottom:
                break
            safe_add(line_y + i, box_left + 2, line[: box_width - 4], theme["text"])

    if page_menu_active:
        items = PAGE_MENU_ITEMS
        title = f"PAGE MENU ({page_menu_key_label}/Esc close)"
        max_item_len = max(len(title), *(len(item) for item in items))
        box_width = min(w - 8, max(40, max_item_len + 6))
        box_height = min(h - 4, len(items) + 4)
        box_left = max(1, (w - box_width) // 2)
        box_top = max(1, (h - box_height) // 2)
        box_right = box_left + box_width - 1
        box_bottom = box_top + box_height - 1

        draw_box(box_left, box_top, box_right, box_bottom, theme["frame"])
        for y in range(box_top + 1, box_bottom):
            safe_add(y, box_left + 1, " " * (box_width - 2), theme["text"])
        safe_add(box_top + 1, box_left + 2, title[: box_width - 4], theme["text"])
        for i, item in enumerate(items):
            item_attr = theme["text"]
            if i == page_menu_index:
                item_attr = item_attr | curses.A_REVERSE
            safe_add(box_top + 3 + i, box_left + 2, item[: box_width - 4], item_attr)

    if file_browser_active:
        if file_browser_mode == "pattern":
            mode_name = "PATTERN"
        elif file_browser_mode == "sample":
            mode_name = "SAMPLE"
        else:
            mode_name = "KIT"
        title = f"{mode_name} BROWSER (Enter open/select, <-/-> or Backspace up, Esc close)"
        visible_items = file_browser_items if file_browser_items else [{"name": "(empty)", "is_dir": False, "is_parent": False}]
        list_height = min(14, max(6, h - 12))
        max_name = max(len(it["name"]) for it in visible_items)
        box_width = min(w - 6, max(52, max_name + 12))
        box_height = min(h - 4, list_height + 4)
        box_left = max(1, (w - box_width) // 2)
        box_top = max(1, (h - box_height) // 2)
        box_right = box_left + box_width - 1
        box_bottom = box_top + box_height - 1

        draw_box(box_left, box_top, box_right, box_bottom, theme["frame"])
        for y in range(box_top + 1, box_bottom):
            safe_add(y, box_left + 1, " " * (box_width - 2), theme["text"])

        safe_add(box_top + 1, box_left + 2, title[: box_width - 4], theme["text"])
        path_line = f"Path: {file_browser_path}"
        safe_add(box_top + 2, box_left + 2, path_line[: box_width - 4], theme["muted"])

        max_rows = box_height - 4
        start = 0
        if file_browser_index >= max_rows:
            start = file_browser_index - max_rows + 1
        end = min(len(visible_items), start + max_rows)

        for i in range(start, end):
            row = box_top + 3 + (i - start)
            label = visible_items[i]["name"]
            item_attr = theme["text"]
            if i == file_browser_index and file_browser_items:
                item_attr = item_attr | curses.A_REVERSE
            safe_add(row, box_left + 2, label[: box_width - 4], item_attr)

    stdscr.refresh()

# ---------- CONTROLLER ----------
class Controller:
    def __init__(self, sequencer, keymap):
        self.seq = sequencer
        self.keymap = keymap
        self.cursor_x = 0
        self.cursor_y = 0
        self.edit_mode = "velocity"
        self.clear_confirm = False
        self.pattern_save_active = False
        self.pattern_save_input = ""
        self.pattern_load_active = False
        self.pattern_load_input = ""
        self.kit_load_active = False
        self.kit_load_input = ""
        self.pack_save_active = False
        self.pack_save_input = ""
        self.chain_edit_active = False
        self.chain_edit_input = ""
        self.swing_edit_active = False
        self.swing_edit_input = ""
        self.page_menu_active = False
        self.page_menu_index = 0
        self.help_active = False
        self.file_browser_active = False
        self.file_browser_mode = None
        self.file_browser_target_track = None
        self.file_browser_path = os.getcwd()
        self.file_browser_items = []
        self.file_browser_index = 0
        self.status_message = ""
        self.pattern_actions = [f"pattern_{i+1}" for i in range(PATTERNS)]

    def move_cursor(self, dx, dy):
        self.cursor_x = (self.cursor_x + dx) % GRID_COLS
        self.cursor_y = (self.cursor_y + dy) % TRACKS

    def _close_pattern_dialog(self):
        self.pattern_load_active = False
        self.pattern_load_input = ""

    def _close_pattern_save_dialog(self):
        self.pattern_save_active = False
        self.pattern_save_input = ""

    def _close_kit_dialog(self):
        self.kit_load_active = False
        self.kit_load_input = ""

    def _close_pack_dialog(self):
        self.pack_save_active = False
        self.pack_save_input = ""

    def _close_chain_dialog(self):
        self.chain_edit_active = False
        self.chain_edit_input = ""

    def _close_page_menu(self):
        self.page_menu_active = False

    def _close_file_browser(self):
        self.file_browser_active = False
        self.file_browser_mode = None
        self.file_browser_target_track = None
        self.file_browser_items = []
        self.file_browser_index = 0

    def _refresh_file_browser(self):
        items = []
        current = os.path.abspath(self.file_browser_path)
        self.file_browser_path = current
        parent = os.path.dirname(current)
        if parent and parent != current:
            items.append({"name": "../", "path": parent, "is_dir": True, "is_parent": True})

        if self.file_browser_mode == "kit":
            items.append({"name": "[LOAD THIS FOLDER]", "path": current, "is_dir": False, "is_parent": False, "is_action": True})

        try:
            entries = list(os.scandir(current))
        except Exception as exc:
            self.status_message = f"Browse failed: {exc}"
            entries = []

        dirs = []
        files = []
        for e in entries:
            if e.name.startswith("."):
                continue
            if e.is_dir(follow_symlinks=False):
                dirs.append(e)
            elif e.is_file(follow_symlinks=False):
                if self.file_browser_mode == "pattern" and e.name.lower().endswith(".json"):
                    files.append(e)
                elif self.file_browser_mode == "sample" and e.name.lower().endswith(".wav"):
                    files.append(e)

        dirs.sort(key=lambda e: e.name.casefold())
        files.sort(key=lambda e: e.name.casefold())

        for e in dirs:
            items.append({"name": f"{e.name}/", "path": e.path, "is_dir": True, "is_parent": False})
        for e in files:
            items.append({"name": e.name, "path": e.path, "is_dir": False, "is_parent": False})

        self.file_browser_items = items
        if self.file_browser_index >= len(items):
            self.file_browser_index = max(0, len(items) - 1)

    def _open_file_browser(self, mode, target_track=None):
        self.file_browser_mode = mode
        self.file_browser_target_track = target_track
        start_path = os.getcwd()
        if mode == "kit":
            start_path = self.seq.kit_path if os.path.isdir(self.seq.kit_path) else start_path
        elif mode == "sample" and target_track is not None:
            sample_path = self.seq.engine.sample_paths[target_track]
            if sample_path and os.path.exists(sample_path):
                start_path = os.path.dirname(sample_path)
            elif os.path.isdir(self.seq.kit_path):
                start_path = self.seq.kit_path
        self.file_browser_path = os.path.abspath(start_path)
        self.file_browser_active = True
        self.file_browser_index = 0
        self.pattern_load_active = False
        self.pattern_load_input = ""
        self.kit_load_active = False
        self.kit_load_input = ""
        self.pack_save_active = False
        self.pack_save_input = ""
        self._refresh_file_browser()

    def _file_browser_enter_dir(self):
        if not self.file_browser_items:
            return
        item = self.file_browser_items[self.file_browser_index]
        if not item["is_dir"]:
            return
        self.file_browser_path = item["path"]
        self.file_browser_index = 0
        self._refresh_file_browser()

    def _run_file_browser_select(self):
        if not self.file_browser_items:
            return
        item = self.file_browser_items[self.file_browser_index]

        if item["is_parent"]:
            self.file_browser_path = item["path"]
            self.file_browser_index = 0
            self._refresh_file_browser()
            return

        if item.get("is_action"):
            if self.file_browser_mode == "kit":
                ok, message = self.seq.load_kit_folder(item["path"])
                self.status_message = message
                self._close_file_browser()
            return

        if item["is_dir"]:
            self.file_browser_path = item["path"]
            self.file_browser_index = 0
            self._refresh_file_browser()
            return

        if self.file_browser_mode == "pattern":
            ok, message = self.seq.load_project_file(item["path"])
            self.status_message = message
            self._close_file_browser()
            return

        if self.file_browser_mode == "kit":
            return

        if self.file_browser_mode == "sample":
            track = self.file_browser_target_track
            if track is None:
                self.status_message = "No target track selected"
                self._close_file_browser()
                return
            ok, message = self.seq.load_single_sample_to_track(track, item["path"])
            self.status_message = message
            self._close_file_browser()
            return

    def _close_swing_dialog(self):
        self.swing_edit_active = False
        self.swing_edit_input = ""

    def _run_page_menu_action(self):
        if self.page_menu_index == 0:
            ok, message = self.seq.copy_current_page()
        elif self.page_menu_index == 1:
            ok, message = self.seq.paste_to_current_page()
        elif self.page_menu_index == 2:
            self.seq.clear_current_pattern()
            ok, message = True, f"Cleared page {self.seq.view_pattern + 1}"
        elif self.page_menu_index == 3:
            self.pattern_save_active = True
            self.pattern_save_input = ""
            self.pattern_load_active = False
            self.pattern_load_input = ""
            self.kit_load_active = False
            self.kit_load_input = ""
            self.chain_edit_active = False
            self.chain_edit_input = ""
            ok, message = True, ""
        elif self.page_menu_index == 4:
            self._open_file_browser("pattern")
            self.pattern_save_active = False
            self.pattern_save_input = ""
            self.kit_load_active = False
            self.kit_load_input = ""
            self.chain_edit_active = False
            self.chain_edit_input = ""
            ok, message = True, ""
        elif self.page_menu_index == 5:
            self._open_file_browser("kit")
            self.pattern_save_active = False
            self.pattern_save_input = ""
            self.pattern_load_active = False
            self.pattern_load_input = ""
            self.chain_edit_active = False
            self.chain_edit_input = ""
            ok, message = True, ""
            self.swing_edit_active = False
            self.swing_edit_input = ""
        elif self.page_menu_index == 6:
            ok, message = self.seq.toggle_chain()
        elif self.page_menu_index == 7:
            self.swing_edit_active = True
            self.swing_edit_input = str(self.seq.pattern_swing[self.seq.view_pattern])
            self.pattern_save_active = False
            self.pattern_save_input = ""
            self.pattern_load_active = False
            self.pattern_load_input = ""
            self.kit_load_active = False
            self.kit_load_input = ""
            self.chain_edit_active = False
            self.chain_edit_input = ""
            ok, message = True, ""
        elif self.page_menu_index == 8:
            self.pack_save_active = True
            self.pack_save_input = ""
            self.pattern_save_active = False
            self.pattern_save_input = ""
            self.pattern_load_active = False
            self.pattern_load_input = ""
            self.kit_load_active = False
            self.kit_load_input = ""
            self.chain_edit_active = False
            self.chain_edit_input = ""
            self.swing_edit_active = False
            self.swing_edit_input = ""
            ok, message = True, ""
        else:
            ok, message = self.seq.toggle_midi_out()
        self.status_message = message

    def handle_key(self, key):
        event_tokens = _event_tokens(key)
        key_code = key if isinstance(key, int) else ord(key)
        if self.status_message and key_code != -1:
            self.status_message = ""

        if self.help_active:
            if key_code == 27 or self.keymap.matches("help_menu", event_tokens):
                self.help_active = False
            return True

        if self.file_browser_active:
            if key_code == 27:
                self._close_file_browser()
                return True
            if key_code in {curses.KEY_BACKSPACE, 127, 8}:
                parent = os.path.dirname(self.file_browser_path)
                if parent and parent != self.file_browser_path:
                    self.file_browser_path = parent
                    self.file_browser_index = 0
                    self._refresh_file_browser()
                return True
            if key_code == curses.KEY_UP:
                if self.file_browser_items:
                    self.file_browser_index = (self.file_browser_index - 1) % len(self.file_browser_items)
                return True
            if key_code == curses.KEY_DOWN:
                if self.file_browser_items:
                    self.file_browser_index = (self.file_browser_index + 1) % len(self.file_browser_items)
                return True
            if key_code in [10, 13, curses.KEY_ENTER]:
                self._run_file_browser_select()
                return True
            if key_code == curses.KEY_RIGHT:
                self._file_browser_enter_dir()
                return True
            if key_code == curses.KEY_LEFT:
                parent = os.path.dirname(self.file_browser_path)
                if parent and parent != self.file_browser_path:
                    self.file_browser_path = parent
                    self.file_browser_index = 0
                    self._refresh_file_browser()
                return True
            return True

        if self.page_menu_active:
            if key_code == 27 or self.keymap.matches("page_menu", event_tokens):
                self._close_page_menu()
                return True
            if key_code == curses.KEY_UP:
                self.page_menu_index = (self.page_menu_index - 1) % len(PAGE_MENU_ITEMS)
                return True
            if key_code == curses.KEY_DOWN:
                self.page_menu_index = (self.page_menu_index + 1) % len(PAGE_MENU_ITEMS)
                return True
            if key_code in [10, 13, curses.KEY_ENTER]:
                self._run_page_menu_action()
                self._close_page_menu()
                return True
            if ord("1") <= key_code <= ord("9"):
                idx = key_code - ord("1")
                if idx < len(PAGE_MENU_ITEMS):
                    self.page_menu_index = idx
                    self._run_page_menu_action()
                    self._close_page_menu()
                    return True
            return True

        if key_code == curses.KEY_RIGHT:
            self.move_cursor(1, 0)
            return True
        if key_code == curses.KEY_LEFT:
            self.move_cursor(-1, 0)
            return True
        if key_code == curses.KEY_UP:
            self.move_cursor(0, -1)
            return True
        if key_code == curses.KEY_DOWN:
            self.move_cursor(0, 1)
            return True
        if "TAB" in event_tokens or key_code == 9:
            cycle = [0, 4, 8, 12, PAN_COL, LOAD_COL]
            next_idx = 0
            for i, col in enumerate(cycle):
                if col > self.cursor_x:
                    next_idx = i
                    break
            else:
                next_idx = 0
            self.cursor_x = cycle[next_idx]
            return True
        if key_code == 27:  # ESC
            if self.chain_edit_active:
                self._close_chain_dialog()
                return True
            if self.pattern_save_active:
                self._close_pattern_save_dialog()
                return True
            if self.kit_load_active:
                self._close_kit_dialog()
                return True
            if self.pack_save_active:
                self._close_pack_dialog()
                return True
            if self.pattern_load_active:
                self._close_pattern_dialog()
                return True
            if self.swing_edit_active:
                self._close_swing_dialog()
                return True
            if self.clear_confirm:
                self.clear_confirm = False
                return True
            if self.edit_mode == "ratchet":
                self.edit_mode = "velocity"
                return True
            return False

        if self.pattern_load_active:
            if key_code in [10, 13, curses.KEY_ENTER]:
                ok, message = self.seq.load_project_file(self.pattern_load_input)
                self.status_message = message
                self._close_pattern_dialog()
                return True

            backspace_keys = {curses.KEY_BACKSPACE, 127, 8}
            if key_code in backspace_keys or key in ["\b", "\x7f"]:
                self.pattern_load_input = self.pattern_load_input[:-1]
                return True

            if isinstance(key, str) and key.isprintable() and key not in ["\n", "\r", "\t"]:
                if len(self.pattern_load_input) < 120:
                    self.pattern_load_input += key
                return True

            return True

        if self.chain_edit_active:
            if key_code in [10, 13, curses.KEY_ENTER]:
                ok, message = self.seq.set_chain_from_text(self.chain_edit_input)
                self.status_message = message
                self._close_chain_dialog()
                return True

            backspace_keys = {curses.KEY_BACKSPACE, 127, 8}
            if key_code in backspace_keys or key in ["\b", "\x7f"]:
                self.chain_edit_input = self.chain_edit_input[:-1]
                return True

            if isinstance(key, str) and key.isprintable() and key not in ["\n", "\r", "\t"]:
                if len(self.chain_edit_input) < 120:
                    self.chain_edit_input += key
                return True

            return True

        if self.swing_edit_active:
            if key_code in [10, 13, curses.KEY_ENTER]:
                ok, message = self.seq.set_current_pattern_swing_from_text(self.swing_edit_input)
                self.status_message = message
                self._close_swing_dialog()
                return True

            backspace_keys = {curses.KEY_BACKSPACE, 127, 8}
            if key_code in backspace_keys or key in ["\b", "\x7f"]:
                self.swing_edit_input = self.swing_edit_input[:-1]
                return True

            if isinstance(key, str) and key.isdigit():
                if len(self.swing_edit_input) < 3:
                    self.swing_edit_input += key
                return True

            return True

        if self.pattern_save_active:
            if key_code in [10, 13, curses.KEY_ENTER]:
                ok, message = self.seq.save_project_file(self.pattern_save_input)
                self.status_message = message
                self._close_pattern_save_dialog()
                return True

            backspace_keys = {curses.KEY_BACKSPACE, 127, 8}
            if key_code in backspace_keys or key in ["\b", "\x7f"]:
                self.pattern_save_input = self.pattern_save_input[:-1]
                return True

            if isinstance(key, str) and key.isprintable() and key not in ["\n", "\r", "\t"]:
                if len(self.pattern_save_input) < 120:
                    self.pattern_save_input += key
                return True

            return True

        if self.kit_load_active:
            if key_code in [10, 13, curses.KEY_ENTER]:
                ok, message = self.seq.load_kit_folder(self.kit_load_input)
                self.status_message = message
                self._close_kit_dialog()
                return True

            backspace_keys = {curses.KEY_BACKSPACE, 127, 8}
            if key_code in backspace_keys or key in ["\b", "\x7f"]:
                self.kit_load_input = self.kit_load_input[:-1]
                return True

            if isinstance(key, str) and key.isprintable() and key not in ["\n", "\r", "\t"]:
                if len(self.kit_load_input) < 120:
                    self.kit_load_input += key
                return True

            return True

        if self.pack_save_active:
            if key_code in [10, 13, curses.KEY_ENTER]:
                ok, message = self.seq.save_pack(self.pack_save_input)
                self.status_message = message
                self._close_pack_dialog()
                return True

            backspace_keys = {curses.KEY_BACKSPACE, 127, 8}
            if key_code in backspace_keys or key in ["\b", "\x7f"]:
                self.pack_save_input = self.pack_save_input[:-1]
                return True

            if isinstance(key, str) and key.isprintable() and key not in ["\n", "\r", "\t"]:
                if len(self.pack_save_input) < 120:
                    self.pack_save_input += key
                return True

            return True

        if self.keymap.matches("clear_pattern", event_tokens):
            if self.clear_confirm:
                self.seq.clear_current_pattern()
                self.clear_confirm = False
            else:
                self.clear_confirm = True
            return True

        if self.clear_confirm and key_code != -1:
            self.clear_confirm = False

        if key_code == ord(' '):
            self.seq.toggle_playback()
            self.status_message = ""
        elif self.keymap.matches("page_menu", event_tokens):
            self.page_menu_active = True
            self.page_menu_index = 0
            self.pattern_save_active = False
            self.pattern_save_input = ""
            self.pattern_load_active = False
            self.pattern_load_input = ""
            self.kit_load_active = False
            self.kit_load_input = ""
            self.pack_save_active = False
            self.pack_save_input = ""
            self.chain_edit_active = False
            self.chain_edit_input = ""
            self.swing_edit_active = False
            self.swing_edit_input = ""
        elif self.keymap.matches("help_menu", event_tokens):
            self.help_active = True
        elif self.keymap.matches("pattern_copy", event_tokens):
            ok, message = self.seq.copy_current_page()
            self.status_message = message
        elif self.keymap.matches("pattern_paste", event_tokens):
            ok, message = self.seq.paste_to_current_page()
            self.status_message = message
        elif self.keymap.matches("pattern_export", event_tokens):
            self.pattern_save_active = True
            self.pattern_save_input = ""
            self.pattern_load_active = False
            self.pattern_load_input = ""
            self.kit_load_active = False
            self.kit_load_input = ""
            self.pack_save_active = False
            self.pack_save_input = ""
            self.chain_edit_active = False
            self.chain_edit_input = ""
            self.swing_edit_active = False
            self.swing_edit_input = ""
            self.status_message = ""
        elif self.keymap.matches("pattern_load", event_tokens):
            self._open_file_browser("pattern")
            self.pattern_save_active = False
            self.pattern_save_input = ""
            self.kit_load_active = False
            self.kit_load_input = ""
            self.pack_save_active = False
            self.pack_save_input = ""
            self.chain_edit_active = False
            self.chain_edit_input = ""
            self.swing_edit_active = False
            self.swing_edit_input = ""
            self.status_message = ""
        elif self.keymap.matches("kit_load", event_tokens):
            self._open_file_browser("kit")
            self.pattern_save_active = False
            self.pattern_save_input = ""
            self.pattern_load_active = False
            self.pattern_load_input = ""
            self.pack_save_active = False
            self.pack_save_input = ""
            self.chain_edit_active = False
            self.chain_edit_input = ""
            self.swing_edit_active = False
            self.swing_edit_input = ""
            self.status_message = ""
        elif self.keymap.matches("chain_edit", event_tokens):
            self.chain_edit_active = True
            self.chain_edit_input = ""
            self.pattern_save_active = False
            self.pattern_save_input = ""
            self.pattern_load_active = False
            self.pattern_load_input = ""
            self.kit_load_active = False
            self.kit_load_input = ""
            self.pack_save_active = False
            self.pack_save_input = ""
            self.swing_edit_active = False
            self.swing_edit_input = ""
            self.status_message = ""
        elif self.keymap.matches("chain_toggle", event_tokens):
            ok, message = self.seq.toggle_chain()
            self.status_message = message
        elif self.keymap.matches("mode_toggle", event_tokens):
            if self.cursor_x < STEPS:
                if self.edit_mode == "velocity":
                    self.edit_mode = "ratchet"
                else:
                    self.edit_mode = "velocity"
        elif self.keymap.matches("pattern_length_dec", event_tokens):
            self.seq.change_current_pattern_length(-1)
        elif self.keymap.matches("pattern_length_inc", event_tokens):
            self.seq.change_current_pattern_length(1)
        elif self.keymap.matches("tempo_inc", event_tokens):
            self.seq.change_bpm(1)
        elif self.keymap.matches("tempo_dec", event_tokens):
            self.seq.change_bpm(-1)
        elif key_code in [
            ord('!'), ord('@'), ord('#'), ord('$'),
            ord('"'), 164,  # common Shift+2 / Shift+4 on some EU layouts
            curses.KEY_F1, curses.KEY_F2, curses.KEY_F3, curses.KEY_F4
        ]:
            if self.cursor_x < STEPS and self.cursor_y != ACCENT_TRACK:
                quick_ratchet = {
                    ord('!'): 1,
                    ord('@'): 2,
                    ord('#'): 3,
                    ord('$'): 4,
                    ord('"'): 2,
                    164: 4,
                    curses.KEY_F1: 1,
                    curses.KEY_F2: 2,
                    curses.KEY_F3: 3,
                    curses.KEY_F4: 4
                }[key_code]
                self.seq.quick_set_ratchet(self.cursor_y, self.cursor_x, quick_ratchet)
        elif key_code in range(ord('0'), ord('9') + 1):
            velocity = key_code - ord('0')
            if self.cursor_x == PAN_COL:
                if velocity > 0:
                    self.seq.set_track_pan(self.cursor_y, velocity)
            elif self.cursor_x == LOAD_COL:
                pass
            elif self.edit_mode == "ratchet":
                if self.cursor_y == ACCENT_TRACK:
                    self.seq.set_step_velocity(self.cursor_y, self.cursor_x, velocity)
                elif 1 <= velocity <= 4:
                    self.seq.set_step_ratchet(self.cursor_y, self.cursor_x, velocity)
            else:
                self.seq.set_step_velocity(self.cursor_y, self.cursor_x, velocity)
                if velocity > 0:
                    self.seq.set_last_velocity(velocity)
        elif key_code in [10, 13, curses.KEY_ENTER]:
            if self.cursor_x == PAN_COL:
                self.seq.set_track_pan(self.cursor_y, 5)
            elif self.cursor_x == LOAD_COL:
                if self.cursor_y != ACCENT_TRACK:
                    self._open_file_browser("sample", target_track=self.cursor_y)
            else:
                self.seq.toggle_step(self.cursor_y, self.cursor_x)
        elif key_code in [ord('p'), ord('P')]:
            self.seq.preview_row(self.cursor_y)
        elif self.keymap.matches("mute_row", event_tokens):
            self.seq.toggle_mute_row(self.cursor_y)
        else:
            for pattern_index, action in enumerate(self.pattern_actions):
                if self.keymap.matches(action, event_tokens):
                    self.seq.select_pattern(pattern_index)
                    break

        return True

# ---------- INPUT ----------
def ui_loop(stdscr, seq):
    curses.set_escdelay(25)
    curses.curs_set(0)
    stdscr.nodelay(True)

    theme = {
        "frame": 0,
        "title": curses.A_BOLD,
        "text": 0,
        "hint": curses.A_BOLD,
        "divider": 0,
        "playhead": curses.A_BOLD,
        "muted": curses.A_DIM,
        "accent": curses.A_BOLD,
        "chain_on": curses.A_BOLD,
        "chain_off": curses.A_DIM,
        "pattern_manual": curses.A_BOLD,
        "pattern_chain_off": curses.A_DIM,
        "velocity_low": 0,
        "velocity_high": curses.A_BOLD,
        "midi_on": curses.A_BOLD,
        "midi_off": curses.A_DIM,
    }
    if curses.has_colors():
        curses.start_color()
        try:
            curses.use_default_colors()
        except curses.error:
            pass
        curses.init_pair(1, curses.COLOR_CYAN, -1)    # frames
        curses.init_pair(2, curses.COLOR_WHITE, -1)   # text
        curses.init_pair(3, curses.COLOR_GREEN, -1)   # playhead
        curses.init_pair(4, curses.COLOR_YELLOW, -1)  # accent/high velocity
        curses.init_pair(5, curses.COLOR_BLUE, -1)    # dividers

        theme["frame"] = curses.color_pair(1)
        theme["title"] = curses.color_pair(1) | curses.A_BOLD
        theme["text"] = curses.color_pair(2)
        theme["hint"] = curses.color_pair(4) | curses.A_BOLD
        theme["divider"] = curses.color_pair(5)
        theme["playhead"] = curses.color_pair(3) | curses.A_BOLD
        theme["muted"] = curses.color_pair(2) | curses.A_DIM
        theme["accent"] = curses.color_pair(4) | curses.A_BOLD
        theme["chain_on"] = curses.color_pair(3) | curses.A_BOLD
        theme["chain_off"] = curses.color_pair(2) | curses.A_DIM
        theme["pattern_manual"] = curses.color_pair(3) | curses.A_BOLD
        theme["pattern_chain_off"] = curses.color_pair(2) | curses.A_DIM
        theme["velocity_low"] = curses.color_pair(2) | curses.A_DIM
        theme["velocity_high"] = curses.color_pair(2) | curses.A_BOLD
        theme["midi_on"] = curses.color_pair(3) | curses.A_BOLD
        theme["midi_off"] = curses.color_pair(2) | curses.A_DIM

    keymap = Keymap()
    controller = Controller(seq, keymap)
    help_lines = keymap.file_lines()
    help_key_label = keymap.label("help_menu")
    page_menu_label = keymap.label("page_menu")
    mode_key_label = keymap.label("mode_toggle")
    clear_key_label = keymap.label("clear_pattern")
    length_dec_label = keymap.label("pattern_length_dec")
    length_inc_label = keymap.label("pattern_length_inc")
    chain_edit_label = keymap.label("chain_edit")
    pattern_export_label = keymap.label("pattern_export")

    should_draw = True
    last_step = -1
    last_pattern = -1
    last_next_pattern = None
    last_playing = None
    last_ui_state = None

    while True:
        try:
            key = stdscr.get_wch()
        except curses.error:
            key = -1

        if key != -1:
            if not controller.handle_key(key):
                if seq.dirty:
                    seq.save()
                    seq.dirty = False
                return
            should_draw = True

        ui_state = (
            controller.cursor_x,
            controller.cursor_y,
            controller.edit_mode,
            controller.clear_confirm,
            controller.pattern_save_active,
            controller.pattern_load_active,
            controller.kit_load_active,
            controller.pack_save_active,
            controller.chain_edit_active,
            controller.swing_edit_active,
            controller.page_menu_active,
            controller.page_menu_index,
            controller.help_active,
            controller.file_browser_active,
            controller.file_browser_mode,
            controller.file_browser_path,
            tuple(item["name"] for item in controller.file_browser_items),
            controller.file_browser_index,
            controller.pattern_save_input,
            controller.pattern_load_input,
            controller.kit_load_input,
            controller.pack_save_input,
            controller.chain_edit_input,
            controller.swing_edit_input,
            controller.status_message,
            seq.bpm,
            seq.pattern_length[seq.view_pattern],
            seq.pattern_swing[seq.view_pattern],
            seq.midi_out_enabled,
            seq.pattern,
            seq.view_pattern,
            seq.next_pattern,
            seq.chain_enabled,
            tuple(seq.chain),
            seq.chain_pos,
        )
        if ui_state != last_ui_state:
            should_draw = True

        if (
            seq.step != last_step
            or seq.pattern != last_pattern
            or seq.next_pattern != last_next_pattern
            or seq.playing != last_playing
        ):
            should_draw = True

        if should_draw:
            draw(
                stdscr,
                seq,
                controller.cursor_x,
                controller.cursor_y,
                controller.edit_mode,
                controller.clear_confirm,
                (
                    f"Save pattern filename (Esc cancels): {controller.pattern_save_input}"
                    if controller.pattern_save_active
                    else (
                        f"Give chain sequence ({chain_edit_label}, Esc cancels): {controller.chain_edit_input}"
                        if controller.chain_edit_active
                        else (
                            f"Give pattern filename (Esc cancels): {controller.pattern_load_input}"
                            if controller.pattern_load_active
                            else (
                                f"Give sample folder name (Esc cancels): {controller.kit_load_input}"
                                if controller.kit_load_active
                                else (
                                    f"Save pack folder name (Esc cancels): {controller.pack_save_input}"
                                    if controller.pack_save_active
                                    else (
                                        f"Swing 50-75 (Esc cancels): {controller.swing_edit_input}"
                                        if controller.swing_edit_active
                                        else ""
                                    )
                                )
                            )
                        )
                    )
                ),
                controller.status_message if not controller.pattern_save_active and not controller.chain_edit_active and not controller.pattern_load_active and not controller.kit_load_active and not controller.pack_save_active and not controller.swing_edit_active else "",
                controller.page_menu_active,
                controller.page_menu_index,
                page_menu_label,
                controller.help_active,
                help_lines,
                help_key_label,
                controller.file_browser_active,
                controller.file_browser_mode,
                controller.file_browser_path,
                controller.file_browser_items,
                controller.file_browser_index,
                mode_key_label,
                clear_key_label,
                length_dec_label,
                length_inc_label,
                theme
            )

            last_step = seq.step
            last_pattern = seq.pattern
            last_next_pattern = seq.next_pattern
            last_playing = seq.playing
            last_ui_state = ui_state
            should_draw = False

        time.sleep(0.002)

# ---------- MAIN ----------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--kit",
        default=DEFAULT_KIT_PATH,
        help="Sample kit directory (default: kit1)"
    )
    parser.add_argument(
        "--pattern",
        default=DEFAULT_PATTERN_NAME,
        help="Pattern JSON file name/path without or with .json (default: patterns)"
    )
    args = parser.parse_args()

    pattern_path = args.pattern
    if not pattern_path.lower().endswith(".json"):
        pattern_path = f"{pattern_path}.json"

    seq = Sequencer(kit_path=args.kit, pattern_path=pattern_path)
    curses.wrapper(ui_loop, seq)

if __name__ == "__main__":
    main()
