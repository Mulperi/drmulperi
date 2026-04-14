import os
import warnings

import numpy as np
import sounddevice as sd
from scipy.io import wavfile

from .config import TRACKS

try:
    import mido
except Exception:
    mido = None

class Voice:
    """Single active sample playback slot used by the mixer callback."""
    def __init__(self):
        self.active = False
        self.data = None
        self.track = -1
        self.pos = 0.0
        self.rate = 1.0
        self.vel = 1.0
        self.pan_l = 1.0
        self.pan_r = 1.0


class MidiOut:
    """Thin MIDI output wrapper over `mido` with graceful failure handling."""
    def __init__(self):
        self.port = None
        self.port_name = None

    def enable(self):
        """Open the first available system MIDI output port."""
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
    """Real-time sample engine: buffering trigger events and rendering stereo audio."""
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
        """Load first 8 alphabetic WAV files from current kit path."""
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

    def preview_wav_file(self, path, velocity=1.0, pan=5):
        """Preview an arbitrary wav file without loading it into a track slot."""
        if not os.path.isfile(path) or not path.lower().endswith(".wav"):
            return False, "Select a .wav file to preview"
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", wavfile.WavFileWarning)
                sr, data = wavfile.read(path)
        except Exception as exc:
            return False, f"Preview failed: {exc}"

        if data.dtype == np.int16:
            data = data.astype(np.float32) / 32768.0
        elif data.dtype == np.int32:
            data = data.astype(np.float32) / 2147483648.0
        else:
            data = data.astype(np.float32)

        if len(data.shape) == 2:
            mono = data.mean(axis=1)
        else:
            mono = data

        velocity = max(0.0, min(1.0, float(velocity)))
        pan_pos = (max(1, min(9, int(pan))) - 1) / 8.0
        left_gain = float(np.cos(pan_pos * (np.pi / 2)))
        right_gain = float(np.sin(pan_pos * (np.pi / 2)))
        stereo = np.zeros((len(mono), 2), dtype=np.float32)
        stereo[:, 0] = mono * velocity * left_gain
        stereo[:, 1] = mono * velocity * right_gain

        try:
            sd.play(stereo, sr, blocking=False)
        except Exception as exc:
            return False, f"Preview failed: {exc}"
        return True, f"Preview: {os.path.basename(path)}"

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
            v.track = -1

    def choke_group(self, group_id, track_groups):
        """Stop active voices belonging to a choke/mute group."""
        if group_id <= 0:
            return
        for v in self.voices:
            if not v.active:
                continue
            tr = v.track
            if 0 <= tr < len(track_groups) and track_groups[tr] == group_id:
                v.active = False
                v.track = -1

    def trigger(self, track, velocity, pan, rate=1.0):
        """Queue one sample trigger event for the audio callback thread."""
        pan_pos = (pan - 1) / 8.0
        left_gain = float(np.cos(pan_pos * (np.pi / 2)))
        right_gain = float(np.sin(pan_pos * (np.pi / 2)))

        idx = self.event_write % len(self.event_buffer)
        self.event_buffer[idx] = (track, velocity, left_gain, right_gain, float(rate))
        self.event_write += 1

    def audio_callback(self, outdata, frames, time_info, status):
        """PortAudio callback: consume trigger queue, mix voices, write to `outdata`."""
        mix = self.mix
        mix[:, :] = 0.0

        while self.event_read != self.event_write:
            idx = self.event_read % len(self.event_buffer)
            event = self.event_buffer[idx]

            if event:
                track, vel, pan_l, pan_r, rate = event
                sample = self.samples[track]

                if sample is not None:
                    for v in self.voices:
                        if not v.active:
                            v.active = True
                            v.data = sample
                            v.track = track
                            v.pos = 0.0
                            v.rate = max(0.01, float(rate))
                            v.vel = vel
                            v.pan_l = pan_l
                            v.pan_r = pan_r
                            break

            self.event_read += 1

        for v in self.voices:
            if not v.active:
                continue

            src = v.data
            src_len = len(src)
            if src_len < 2:
                v.active = False
                v.track = -1
                continue

            positions = v.pos + (np.arange(frames, dtype=np.float32) * v.rate)
            valid = positions < (src_len - 1)
            n = int(np.count_nonzero(valid))
            if n > 0:
                p = positions[:n]
                idx0 = p.astype(np.int32)
                frac = p - idx0
                idx1 = idx0 + 1
                chunk = ((1.0 - frac) * src[idx0]) + (frac * src[idx1])
                scaled = chunk * v.vel
                mix[:n, 0] += scaled * v.pan_l
                mix[:n, 1] += scaled * v.pan_r

            v.pos += frames * v.rate
            if v.pos >= (src_len - 1):
                v.active = False
                v.track = -1

        outdata[:] = mix * 0.25
