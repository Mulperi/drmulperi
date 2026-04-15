"""Recording workflow helpers for the terminal controller.

This module keeps input-device, monitor, and capture logic outside the UI layer.
"""

import os
import time

import numpy as np
import sounddevice as sd
from scipy.io import wavfile

from .config import TRACKS


def _start_take_capture(controller):
    """Start one take capture in the engine duplex callback."""
    sr = int(controller.seq.engine.sr)
    frames = max(1, int(round(controller.record_capture_duration_seconds * sr)))
    idx = controller.record_capture_input_indices if controller.record_capture_input_indices else [0]
    if controller.record_use_external_capture:
        dev_id = controller.record_device_ids[controller.record_device_index] if controller.record_device_ids else None
        mapping = [(max(0, int(v)) + 1) for v in idx]
        if controller.record_capture_channels >= 2 and len(mapping) < 2:
            mapping = [mapping[0], mapping[0]]
        controller._record_stream = sd.rec(
            frames=frames,
            samplerate=sr,
            channels=controller.record_capture_channels,
            dtype="float32",
            device=dev_id,
            mapping=mapping,
            blocking=False,
        )
    else:
        controller.seq.engine.configure_capture(
            channels=controller.record_capture_channels,
            input_indices=idx,
            frames=frames,
        )
        if not controller.seq.engine.start_capture():
            raise RuntimeError("Capture start failed")
    controller.record_capture_started_at = time.perf_counter()


def refresh_record_devices(controller):
    """Load available input devices for record overlay selection."""
    names = []
    ids = []
    sample_rates = []
    channels = []
    try:
        devices = sd.query_devices()
    except Exception:
        devices = []
    for idx, dev in enumerate(devices):
        try:
            max_in = int(dev.get("max_input_channels", 0))
            if max_in > 0:
                names.append(str(dev.get("name", "Input")))
                ids.append(idx)
                sample_rates.append(int(round(float(dev.get("default_samplerate", controller.seq.engine.sr)))))
                channels.append(max_in)
        except Exception:
            continue
    controller.record_device_names = names
    controller.record_device_ids = ids
    controller.record_device_sample_rates = sample_rates
    controller.record_device_channels = channels
    if controller.record_device_index >= len(ids):
        controller.record_device_index = max(0, len(ids) - 1)
    controller._refresh_record_input_sources()


def refresh_record_input_sources(controller):
    """Rebuild selectable input channel sources for selected device/channels mode."""
    sources = []
    if controller.record_device_ids and 0 <= controller.record_device_index < len(controller.record_device_channels):
        max_in = max(1, int(controller.record_device_channels[controller.record_device_index]))
        if int(controller.record_channels) >= 2:
            for i in range(max(0, max_in - 1)):
                sources.append({"label": f"In {i+1}/{i+2}", "indices": [i, i + 1]})
        else:
            for i in range(max_in):
                sources.append({"label": f"In {i+1}", "indices": [i]})
    if not sources:
        sources = [{"label": "Default", "indices": [0]}]
    controller.record_input_sources = sources
    if controller.record_input_source_index >= len(sources):
        controller.record_input_source_index = 0


def current_record_input_indices(controller):
    """Return currently selected input channel indices (0-based)."""
    if not controller.record_input_sources:
        controller._refresh_record_input_sources()
    if not controller.record_input_sources:
        return [0]
    idx = max(0, min(len(controller.record_input_sources) - 1, int(controller.record_input_source_index)))
    indices = controller.record_input_sources[idx].get("indices", [0])
    if not isinstance(indices, list) or not indices:
        return [0]
    return [max(0, int(v)) for v in indices]


def extract_record_input(controller, indata):
    """Extract selected input source channels from raw device input frames."""
    arr = np.asarray(indata, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr.reshape(-1, 1)
    if arr.size <= 0:
        return np.zeros((0,), dtype=np.float32)
    idx = controller._current_record_input_indices()
    ncols = arr.shape[1]
    if int(controller.record_channels) >= 2:
        left_i = idx[0] if len(idx) > 0 else 0
        right_i = idx[1] if len(idx) > 1 else left_i
        left_i = max(0, min(ncols - 1, left_i))
        right_i = max(0, min(ncols - 1, right_i))
        left = arr[:, left_i]
        right = arr[:, right_i]
        return np.column_stack((left, right)).astype(np.float32)
    mono_i = idx[0] if len(idx) > 0 else 0
    mono_i = max(0, min(ncols - 1, mono_i))
    return np.asarray(arr[:, mono_i], dtype=np.float32)


def record_level_callback(controller, indata, frames, time_info, status):
    """Input stream callback: compute current dBFS level for UI meter."""
    try:
        selected = controller._extract_record_input(indata)
        mono = selected.mean(axis=1) if np.asarray(selected).ndim == 2 else np.asarray(selected, dtype=np.float32)
        rms = float(np.sqrt(np.mean(np.square(mono)))) if mono.size > 0 else 0.0
        if rms <= 1e-9:
            db = -60.0
        else:
            db = max(-60.0, min(0.0, 20.0 * np.log10(rms)))
        controller.record_level_db = db
    except Exception:
        controller.record_level_db = -60.0


def record_capture_callback(controller, indata, frames, time_info, status):
    """Unused with duplex-engine capture mode."""
    return


def stop_record_monitor(controller):
    """Stop and dispose current input monitor stream."""
    controller._record_stream = None
    controller.record_monitor_running = False
    controller.seq.engine.set_input_monitoring(False)


def start_record_monitor(controller):
    """Start input monitor stream for currently selected device."""
    controller._stop_record_monitor()
    if controller.seq.playing and not controller.record_capture_active:
        controller.record_level_db = -60.0
        controller.record_monitor_running = False
        return
    if not controller.seq.engine.input_available:
        controller.record_level_db = -60.0
        return
    controller.record_monitor_running = True
    controller.record_capture_sr = int(controller.seq.engine.sr)
    controller.seq.engine.set_input_monitoring(True)
    controller.record_level_db = controller.seq.engine.get_input_level_db()


def start_record_capture_stream(controller):
    """Prepare capture settings for engine duplex capture mode."""
    controller._stop_record_monitor()
    engine = controller.seq.engine
    # Try enabling duplex only when recording starts (keeps normal playback stable).
    if engine.duplex_mode in {"on", "auto"} and not engine.using_duplex:
        try:
            engine.enable_duplex_for_recording()
        except Exception:
            pass

    if engine.using_duplex and engine.input_available:
        controller.record_use_external_capture = False
        controller.record_capture_sr = int(engine.sr)
    else:
        if engine.duplex_mode == "on":
            controller.status_message = "Duplex mode requested but unavailable. Restart with a duplex-capable device."
            return False
        if not controller.record_device_ids:
            controller.status_message = "No input device"
            return False
        if controller.seq.playing:
            controller.status_message = "Recording while playing requires duplex input device."
            return False
        controller.record_use_external_capture = True
        controller.record_capture_sr = int(engine.sr)
        controller.status_message = "Recording fallback mode (non-duplex device)"
    controller.record_monitor_running = False
    return True


def open_record_overlay(controller, target_track=None, from_audio_view=False):
    """Open record device overlay and start live input level monitoring."""
    controller._refresh_record_devices()
    controller.record_overlay_active = True
    controller.record_overlay_index = 0
    controller.record_action_index = 1
    controller.record_precount_pattern = max(0, min(controller.seq.pattern_count() - 1, int(controller.seq.view_pattern)))
    controller.record_capture_context_track = target_track if isinstance(target_track, int) else None
    controller.record_capture_context_audio = bool(from_audio_view)
    controller.record_level_db = -60.0
    controller._start_record_monitor()
    if controller.seq.playing:
        controller.status_message = "Record menu open (meter paused while playing)"


def close_record_overlay(controller):
    """Close record overlay and stop input monitor."""
    controller.record_overlay_active = False
    controller._stop_record_monitor()


def cancel_record_capture(controller, reason="Recording canceled"):
    """Abort any active two-pass recording session."""
    if controller.record_capture_active:
        controller.record_capture_active = False
        controller.record_capture_stage = "idle"
        controller.record_capture_loop_count = 0
        controller.record_capture_chunks = []
        controller.record_capture_buffer = None
        controller.record_capture_write = 0
        controller.record_capture_capacity = 0
        controller.record_capture_duration_seconds = 0.0
        controller.record_capture_started_at = 0.0
        controller.record_capture_controls_transport = True
        controller.record_capture_end_time = 0.0
        controller.record_capture_started_playback = False
        controller.seq.engine.stop_capture()
        if controller.record_use_external_capture:
            # Do not call `sd.stop()` here; it can stop the engine output stream too.
            controller._record_stream = None
            controller.seq.engine.restart_output_stream()
            controller.record_use_external_capture = False
        else:
            controller.seq.engine.disable_duplex_after_recording()
        controller._stop_record_monitor()
        with controller.seq.transport_lock:
            controller.seq.pending_events.clear()
            if controller.seq.pending_midi_off:
                controller.seq.midi.all_notes_off()
                controller.seq.pending_midi_off.clear()
            controller.seq.transport_resync = True
        controller.status_message = reason


def finish_record_capture(controller):
    """Finalize capture, write WAV, then open import overlay for routing."""
    controller.record_capture_active = False
    controller.record_capture_stage = "idle"
    controller.record_capture_loop_count = 0
    if controller.record_use_external_capture:
        try:
            sd.wait()
        except Exception:
            pass
        recorded = np.asarray(controller._record_stream, dtype=np.float32) if controller._record_stream is not None else None
        controller._record_stream = None
        controller.seq.engine.restart_output_stream()
    else:
        controller.seq.engine.stop_capture()
        recorded = controller.seq.engine.consume_capture()
        controller.seq.engine.disable_duplex_after_recording()
    if recorded is not None:
        recorded = np.asarray(recorded, dtype=np.float32)
    controller.record_capture_chunks = []
    controller.record_capture_buffer = None
    controller.record_capture_write = 0
    controller.record_capture_capacity = 0
    controller.record_capture_duration_seconds = 0.0
    controller.record_capture_started_at = 0.0
    controller.record_capture_controls_transport = True
    controller.record_capture_end_time = 0.0
    controller.record_use_external_capture = False
    controller.record_capture_started_playback = False
    controller._stop_record_monitor()
    with controller.seq.transport_lock:
        controller.seq.pending_events.clear()
        if controller.seq.pending_midi_off:
            controller.seq.midi.all_notes_off()
            controller.seq.pending_midi_off.clear()
        controller.seq.transport_resync = True
    if recorded is None:
        controller.status_message = "Record failed: no audio captured"
        return
    if recorded.size <= 1:
        controller.status_message = "Record failed: no audio captured"
        return
    src_sr = int(controller.seq.engine.sr)
    dst_sr = int(controller.seq.engine.sr)
    channels = 2 if (recorded.ndim == 2 and recorded.shape[1] >= 2) else 1
    if channels == 2:
        if src_sr != dst_sr:
            left = controller.seq._resample_mono_linear(recorded[:, 0], src_sr, dst_sr)
            right = controller.seq._resample_mono_linear(recorded[:, 1], src_sr, dst_sr)
            n = min(len(left), len(right))
            recorded = np.column_stack((left[:n], right[:n])).astype(np.float32)
        mono = recorded.mean(axis=1).astype(np.float32)
    else:
        mono = recorded.reshape(-1).astype(np.float32)
        if src_sr != dst_sr:
            mono = controller.seq._resample_mono_linear(mono, src_sr, dst_sr)
    rec_dir = os.path.join(os.getcwd(), "recordings")
    os.makedirs(rec_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(controller.seq.pattern_name))[0] or "pattern"
    rec_idx = 1
    while True:
        name = f"{base}_rec{rec_idx}.wav"
        out_path = os.path.join(rec_dir, name)
        if not os.path.exists(out_path):
            break
        rec_idx += 1
    out_src = recorded if channels == 2 else mono
    out = np.clip(out_src * 32767.0, -32768, 32767).astype(np.int16)
    wavfile.write(out_path, dst_sr, out)
    sr_hint = f" (SR {src_sr}->{dst_sr})" if src_sr != dst_sr else ""
    controller.status_message = f"Recorded {name}{sr_hint}"
    controller._close_record_overlay()
    controller._open_import_overlay(out_path, can_delete_source=True)
    if controller.record_capture_context_track is not None:
        track = max(0, min(TRACKS - 2, int(controller.record_capture_context_track)))
        controller.import_target_drum_track = track
        controller.import_target_audio_track = track
        if controller.record_capture_context_audio:
            controller.import_overlay_index = 2


def arm_record_capture(controller):
    """Start recording with selected precount and scope."""
    track = controller.record_capture_context_track
    if track is None and controller.active_tab == 1 and controller.cursor_y < (TRACKS - 1):
        track = controller._track_for_row(controller.cursor_y)
    if track is None:
        track = max(0, min(TRACKS - 2, int(controller.cursor_y)))

    precount_pattern = max(0, min(controller.seq.pattern_count() - 1, int(controller.record_precount_pattern)))
    take_pattern = controller.seq.view_pattern
    scope = "song" if (0 <= track < (TRACKS - 1) and controller.seq.audio_track_mode[track] == 1) else "pattern"
    precount_loops = 1 if controller.record_precount_enabled else 0
    take_loops = max(1, len(controller.seq.chain)) if scope == "song" else 1
    if take_loops <= 0:
        controller.status_message = "Nothing to record"
        return

    was_playing = bool(controller.seq.playing)
    controller._cancel_record_capture("")
    controller.record_capture_channels = 2 if int(controller.record_channels) >= 2 else 1
    controller.record_capture_input_indices = controller._current_record_input_indices()
    take_seconds = controller.seq.chain_duration_seconds() if scope == "song" else controller.seq.pattern_duration_seconds(take_pattern)
    controller.record_capture_buffer = None
    controller.record_capture_capacity = 0
    controller.record_capture_write = 0
    controller.record_capture_duration_seconds = max(0.05, float(take_seconds))
    controller.record_capture_started_at = 0.0
    controller.record_capture_controls_transport = False
    controller.record_capture_end_time = 0.0
    controller.record_capture_started_playback = False

    if not controller._start_record_capture_stream():
        return
    live_duplex = bool(controller.seq.engine.using_duplex and not controller.record_use_external_capture)
    controller.record_capture_controls_transport = live_duplex
    controller.record_capture_active = True
    controller.record_capture_stage = "preroll" if (precount_loops > 0 and controller.record_capture_controls_transport) else "recording"
    controller.record_capture_pattern = take_pattern
    controller.record_capture_scope = scope
    controller.record_capture_precount_loops = int(precount_loops)
    controller.record_capture_take_loops = int(take_loops)
    controller.record_capture_loop_count = 0
    controller.record_capture_precount_seconds = 0.0
    controller.record_capture_take_seconds = 0.0
    controller.record_capture_phase_start = time.perf_counter()
    controller.record_capture_context_track = track
    controller.record_capture_track = track
    controller.record_capture_last_step = 0
    controller.record_capture_chunks = []
    controller.record_level_db = -60.0

    # Non-duplex: isolate recording from playback for stability.
    if not live_duplex:
        with controller.seq.transport_lock:
            if controller.seq.playing:
                controller.seq.toggle_playback()
            controller.seq.step = 0
            controller.seq.next_pattern = None
            controller.seq.pending_events.clear()
            controller.seq.pending_midi_off.clear()
            controller.seq.transport_resync = True
            controller.record_capture_last_step = controller.seq.step

        try:
            _start_take_capture(controller)
        except Exception as exc:
            controller._cancel_record_capture(f"Record failed: {exc}")
            return
        controller.record_capture_end_time = time.perf_counter() + controller.record_capture_duration_seconds
        if was_playing:
            controller.status_message = "Recording (playback paused for stability)"
        else:
            controller.status_message = "Recording..."
        return

    # Duplex live path: keep playback running and align capture to loop boundaries.
    with controller.seq.transport_lock:
        if not controller.seq.playing:
            if controller.record_capture_stage == "preroll":
                controller.seq.chain_enabled = False
                controller.seq.select_pattern(precount_pattern)
            else:
                if scope == "song":
                    controller.seq.chain_enabled = True
                    if not controller.seq.chain:
                        controller.seq.chain = [0]
                    controller.seq.chain_pos = 0
                    controller.seq.pattern = controller.seq.chain[0]
                    controller.seq.view_pattern = controller.seq.pattern
                else:
                    controller.seq.chain_enabled = False
                    controller.seq.select_pattern(controller.record_capture_pattern)
            controller.seq.step = 0
            controller.seq.next_pattern = None
            controller.seq.pending_events.clear()
            controller.seq.pending_midi_off.clear()
            controller.seq.transport_resync = True
            controller.seq.toggle_playback()
            controller.record_capture_started_playback = True
        controller.record_capture_last_step = controller.seq.step

    if controller.record_capture_stage == "recording":
        try:
            _start_take_capture(controller)
        except Exception as exc:
            controller._cancel_record_capture(f"Record failed: {exc}")
            return
        controller.status_message = "Recording..."
    else:
        scope_text = "song" if scope == "song" else "pattern"
        controller.status_message = f"Record armed: precount pattern {precount_pattern + 1}, then {scope_text} capture"


def tick_record_capture(controller):
    """Advance recording state machine at loop boundaries."""
    controller.record_level_db = controller.seq.engine.get_input_level_db()
    if not controller.record_capture_active:
        return
    if not controller.record_capture_controls_transport:
        if controller.record_capture_end_time > 0.0 and time.perf_counter() >= controller.record_capture_end_time:
            controller._finish_record_capture()
        return

    if not controller.seq.playing:
        controller._cancel_record_capture("Recording canceled (playback stopped)")
        return
    current_step = int(controller.seq.step)
    wrapped = controller.record_capture_last_step > current_step
    controller.record_capture_last_step = current_step
    if not wrapped:
        return

    controller.record_capture_loop_count += 1

    if controller.record_capture_stage == "preroll":
        if controller.record_capture_loop_count < controller.record_capture_precount_loops:
            return
        controller.record_capture_stage = "recording"
        controller.record_capture_loop_count = 0
        with controller.seq.transport_lock:
            if controller.record_capture_scope == "song":
                controller.seq.chain_enabled = True
                if not controller.seq.chain:
                    controller.seq.chain = [0]
                controller.seq.chain_pos = 0
                controller.seq.pattern = controller.seq.chain[0]
                controller.seq.view_pattern = controller.seq.pattern
            else:
                controller.seq.chain_enabled = False
                controller.seq.select_pattern(controller.record_capture_pattern)
            controller.seq.step = 0
            controller.seq.next_pattern = None
            controller.seq.pending_events.clear()
            controller.seq.pending_midi_off.clear()
            controller.seq.transport_resync = True
            controller.record_capture_last_step = controller.seq.step
        try:
            _start_take_capture(controller)
        except Exception as exc:
            controller._cancel_record_capture(f"Record failed: {exc}")
            return
        controller.status_message = "Recording..."
        return

    if controller.record_capture_loop_count >= controller.record_capture_take_loops:
        with controller.seq.transport_lock:
            if controller.record_capture_started_playback and controller.seq.playing:
                controller.seq.toggle_playback()
        controller._finish_record_capture()
