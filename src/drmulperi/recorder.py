"""Recording workflow helpers for the terminal controller.

This module keeps input-device, monitor, and capture logic outside the UI layer.
"""

import os
import time

import numpy as np
import sounddevice as sd
from scipy.io import wavfile

from .config import TRACKS
from . import ui_texts as texts


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
    """Load available input devices for record dialog selection."""
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
        selected = extract_record_input(controller, indata)

        def level_from_signal(sig):
            arr = np.asarray(sig, dtype=np.float32)
            if arr.ndim == 1:
                rms_val = float(np.sqrt(np.mean(np.square(arr)))) if arr.size > 0 else 0.0
                peak_val = float(np.max(np.abs(arr))) if arr.size > 0 else 0.0
                return rms_val, peak_val
            if arr.ndim == 2 and arr.shape[1] > 0:
                # Use loudest channel to avoid phase cancellation when channels differ.
                ch_rms = np.sqrt(np.mean(np.square(arr), axis=0)) if arr.shape[0] > 0 else np.zeros((arr.shape[1],), dtype=np.float32)
                ch_peak = np.max(np.abs(arr), axis=0) if arr.shape[0] > 0 else np.zeros((arr.shape[1],), dtype=np.float32)
                rms_val = float(np.max(ch_rms)) if ch_rms.size > 0 else 0.0
                peak_val = float(np.max(ch_peak)) if ch_peak.size > 0 else 0.0
                return rms_val, peak_val
            return 0.0, 0.0

        rms, peak = level_from_signal(selected)

        # Fallback: if selected mapping is effectively silent, meter any active input channel.
        if peak <= 1e-9:
            raw = np.asarray(indata, dtype=np.float32)
            rms_any, peak_any = level_from_signal(raw)
            if peak_any > peak:
                rms, peak = rms_any, peak_any

        if rms <= 1e-9:
            db_rms = -60.0
        else:
            db_rms = max(-60.0, min(0.0, 20.0 * np.log10(rms)))
        if peak <= 1e-9:
            db_peak = -60.0
        else:
            db_peak = max(-60.0, min(0.0, 20.0 * np.log10(peak)))

        # Make meter visually reactive: peak-forward with gentle decay.
        prev = float(getattr(controller, "record_level_db", -60.0))
        instant = max(db_rms, db_peak)
        db = max(instant, prev - 3.0)
        controller.record_level_db = db
        controller.record_level_peak_db = db_peak
        controller.record_level_tick = int(getattr(controller, "record_level_tick", 0)) + 1
    except Exception:
        controller.record_level_db = -60.0


def record_capture_callback(controller, indata, frames, time_info, status):
    """Unused with duplex-engine capture mode."""
    return


def stop_record_monitor(controller):
    """Stop and dispose current input monitor stream."""
    stream = getattr(controller, "_record_monitor_stream", None)
    if stream is not None:
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass
    controller._record_monitor_stream = None
    controller.record_monitor_running = False
    controller.record_monitor_info = ""
    controller.seq.engine.set_input_monitoring(False)
    if not controller.record_capture_active:
        try:
            controller.seq.engine.disable_duplex_after_recording()
        except Exception:
            pass
    controller.record_level_peak_db = -60.0


def start_record_monitor(controller):
    """Start input monitor stream for currently selected device."""
    # Monitoring behavior and settings:
    # - Enabled only when [ui] rec_input_metering=on in settings.ini.
    # - Runs only while record dialog is open and transport is stopped.
    # - Uses engine duplex input metering first (matches recording path),
    #   then falls back to a standalone input stream if duplex is unavailable.
    if not getattr(controller, "record_input_metering_enabled", False):
        controller._stop_record_monitor()
        controller.record_level_db = -60.0
        controller.record_level_peak_db = -60.0
        controller.record_level_tick = 0
        controller.record_monitor_info = ""
        return
    if controller.record_capture_active or controller.seq.playing:
        controller._stop_record_monitor()
        controller.record_level_db = -60.0
        controller.record_level_peak_db = -60.0
        controller.record_level_tick = 0
        controller.record_monitor_info = ""
        return
    controller._stop_record_monitor()

    # Prefer the engine duplex meter path so monitoring matches the recording path.
    engine = controller.seq.engine
    try:
        if engine.duplex_mode in {"on", "auto"} and not (engine.using_duplex and engine.input_available):
            engine.enable_duplex_for_recording()
    except Exception:
        pass
    if engine.using_duplex and engine.input_available:
        controller.record_monitor_running = True
        controller.record_level_db = -60.0
        controller.record_level_peak_db = -60.0
        controller.record_level_tick = 0
        controller.record_capture_sr = int(engine.sr)
        controller.record_monitor_info = texts.fmt(texts.backend.recorder.monitor.engine_info, sample_rate=int(engine.sr))
        engine.set_input_monitoring(True)
        controller.status_message = texts.fmt(texts.backend.recorder.monitor.input_meter_on_engine, info=controller.record_monitor_info)
        return

    if not controller.record_device_ids:
        controller.record_level_db = -60.0
        controller.record_level_peak_db = -60.0
        controller.record_level_tick = 0
        controller.record_monitor_info = ""
        return

    dev_idx = max(0, min(len(controller.record_device_ids) - 1, int(controller.record_device_index)))
    dev_id = controller.record_device_ids[dev_idx]
    dev_sr = int(controller.record_device_sample_rates[dev_idx]) if 0 <= dev_idx < len(controller.record_device_sample_rates) else int(controller.seq.engine.sr)
    max_in = int(controller.record_device_channels[dev_idx]) if 0 <= dev_idx < len(controller.record_device_channels) else 1
    wanted_idx = controller._current_record_input_indices()
    wanted_channels = (max(wanted_idx) + 1) if wanted_idx else int(controller.record_channels)
    channels = max(1, min(max_in, int(wanted_channels)))

    try:
        monitor_stream = sd.InputStream(
            device=dev_id,
            channels=channels,
            samplerate=dev_sr,
            callback=controller._record_level_callback,
            blocksize=512,
            dtype="float32",
            latency="high",
        )
        monitor_stream.start()
        controller._record_monitor_stream = monitor_stream
        controller.record_monitor_running = True
        controller.record_level_db = -60.0
        controller.record_level_peak_db = -60.0
        controller.record_level_tick = 0
        controller.record_capture_sr = int(dev_sr)
        selected_name = controller.record_device_names[dev_idx] if 0 <= dev_idx < len(controller.record_device_names) else texts.fmt(texts.backend.recorder.monitor.device_fallback_name, device_id=dev_id)
        controller.record_monitor_info = texts.fmt(texts.backend.recorder.monitor.device_info, device_name=selected_name, sample_rate=int(dev_sr), channels=int(channels))
        controller.status_message = texts.fmt(texts.backend.recorder.monitor.input_meter_on_device, device_name=selected_name, sample_rate=int(dev_sr), channels=int(channels))
    except Exception as exc:
        controller._record_monitor_stream = None
        controller.record_monitor_running = False
        controller.record_level_db = -60.0
        controller.record_level_peak_db = -60.0
        controller.record_level_tick = 0
        controller.record_monitor_info = ""
        controller.status_message = texts.fmt(texts.backend.recorder.monitor.failed, error=exc)


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
            controller.status_message = texts.backend.recorder.capture.duplex_unavailable
            return False
        if not controller.record_device_ids:
            controller.status_message = texts.backend.recorder.capture.no_input_device
            return False
        if controller.seq.playing:
            controller.status_message = texts.backend.recorder.capture.requires_duplex
            return False
        controller.record_use_external_capture = True
        controller.record_capture_sr = int(engine.sr)
        controller.status_message = texts.backend.recorder.capture.fallback_mode
    controller.record_monitor_running = False
    return True


def open_record_dialog(controller, target_track=None, from_audio_view=False):
    """Open record device dialog and start live input level monitoring."""
    # Stop transport before opening dialog so input monitor can start immediately.
    if controller.seq.playing:
        controller.seq.toggle_playback()
    controller._refresh_record_devices()
    controller.dialog_record_active = True
    controller.dialog_record_index = 0
    controller.record_action_index = 1
    controller.record_precount_pattern = max(0, min(controller.seq.pattern_count() - 1, int(controller.seq.view_pattern)))
    controller.record_capture_context_track = target_track if isinstance(target_track, int) else None
    controller.record_capture_context_audio = bool(from_audio_view)
    controller.record_level_db = -60.0
    controller._start_record_monitor()


def close_record_dialog(controller):
    """Close record dialog and stop input monitor."""
    controller.dialog_record_active = False
    controller._stop_record_monitor()


def cancel_record_capture(controller, reason=None):
    """Abort any active two-pass recording session."""
    if reason is None:
        reason = texts.backend.recorder.capture.canceled
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
        controller.record_capture_trim_seconds = 0.0
        controller.seq.engine.stop_capture()
        controller.seq.engine.stop_all()
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
    """Finalize capture, write WAV, then open import dialog for routing."""
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
    pre_roll_seconds = float(getattr(controller, "record_capture_trim_seconds", 0.0) or 0.0)
    if recorded is not None:
        recorded = np.asarray(recorded, dtype=np.float32)
        if pre_roll_seconds > 0.0:
            trim_n = int(round(pre_roll_seconds * controller.seq.engine.sr))
            if trim_n > 0:
                recorded = recorded[trim_n:, ...]
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
    # Clear one-shot precount trim marker after applying it.
    controller.record_capture_trim_seconds = 0.0
    controller._stop_record_monitor()
    controller.seq.engine.stop_all()
    with controller.seq.transport_lock:
        controller.seq.pending_events.clear()
        if controller.seq.pending_midi_off:
            controller.seq.midi.all_notes_off()
            controller.seq.pending_midi_off.clear()
        controller.seq.transport_resync = True
    if recorded is None:
        controller.status_message = texts.backend.recorder.capture.failed_no_audio
        return
    if recorded.size <= 1:
        controller.status_message = texts.backend.recorder.capture.failed_no_audio
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
    controller.status_message = texts.fmt(texts.backend.recorder.capture.recorded, name=name, sr_hint=sr_hint)
    controller._close_record_dialog()
    controller._open_import_dialog(out_path, can_delete_source=True)
    if controller.record_capture_context_track is not None:
        track = max(0, min(TRACKS - 2, int(controller.record_capture_context_track)))
        controller.import_target_drum_track = track
        controller.import_target_audio_track = track
        if controller.record_capture_context_audio:
            controller.dialog_import_index = 2


def arm_record_capture(controller):
    """Start recording using pre-rendered backing for stable timing."""
    track = controller.record_capture_context_track
    if track is None and controller.nav.active_tab == 1 and controller.cursor_y < (TRACKS - 1):
        track = controller._track_for_row(controller.cursor_y)
    if track is None:
        track = max(0, min(TRACKS - 2, int(controller.cursor_y)))

    precount_pattern = max(0, min(controller.seq.pattern_count() - 1, int(controller.record_precount_pattern)))
    take_pattern = controller.seq.view_pattern
    scope = "song" if (0 <= track < (TRACKS - 1) and controller.seq.audio_track_mode[track] == 1) else "pattern"
    include_precount = bool(controller.record_precount_enabled)

    controller._cancel_record_capture("")
    controller.record_capture_channels = 2 if int(controller.record_channels) >= 2 else 1
    controller.record_capture_input_indices = controller._current_record_input_indices()

    with controller.seq.transport_lock:
        if controller.seq.playing:
            controller.seq.toggle_playback()
        controller.seq.step = 0
        controller.seq.next_pattern = None
        controller.seq.pending_events.clear()
        controller.seq.pending_midi_off.clear()
        controller.seq.transport_resync = True

    try:
        backing, pre_roll_seconds, total_seconds = controller.seq.render_record_backing(
            precount_pattern=precount_pattern,
            take_pattern=take_pattern,
            scope=scope,
            include_precount=include_precount,
        )
    except Exception as exc:
        controller.status_message = texts.fmt(texts.backend.recorder.capture.backing_render_error, error=exc)
        return

    if backing is None or len(backing) <= 1:
        controller.status_message = texts.backend.recorder.capture.empty_backing
        return

    controller.record_capture_buffer = None
    controller.record_capture_capacity = 0
    controller.record_capture_write = 0
    controller.record_capture_duration_seconds = max(0.05, float(total_seconds))
    controller.record_capture_started_at = 0.0
    controller.record_capture_controls_transport = False
    controller.record_capture_end_time = 0.0
    controller.record_capture_started_playback = False
    # Remove only deterministic precount duration from recorded take.
    controller.record_capture_trim_seconds = max(0.0, float(pre_roll_seconds if include_precount else 0.0))

    if not controller._start_record_capture_stream():
        return

    controller.record_capture_active = True
    controller.record_capture_stage = "recording"
    controller.record_capture_pattern = take_pattern
    controller.record_capture_scope = scope
    controller.record_capture_precount_loops = 1 if include_precount else 0
    controller.record_capture_take_loops = 1
    controller.record_capture_loop_count = 0
    controller.record_capture_precount_seconds = 0.0
    controller.record_capture_take_seconds = 0.0
    controller.record_capture_phase_start = time.perf_counter()
    controller.record_capture_context_track = track
    controller.record_capture_track = track
    controller.record_capture_last_step = 0
    controller.record_capture_chunks = []
    controller.record_level_db = -60.0

    try:
        _start_take_capture(controller)
    except Exception as exc:
        controller._cancel_record_capture(texts.fmt(texts.backend.recorder.capture.failed, error=exc))
        return

    controller.seq.engine.trigger_buffer(backing, 1.0, 5, rate=1.0, track=999, replace=True)
    controller.record_capture_end_time = time.perf_counter() + controller.record_capture_duration_seconds
    scope_text = "song" if scope == "song" else "pattern"
    if include_precount:
        controller.status_message = texts.fmt(texts.backend.recorder.capture.recording_with_precount, scope=scope_text)
    else:
        controller.status_message = texts.fmt(texts.backend.recorder.capture.recording, scope=scope_text)


def tick_record_capture(controller):
    """Advance recording timer for pre-rendered backing capture."""
    controller.record_level_db = controller.seq.engine.get_input_level_db()
    if not controller.record_capture_active:
        return
    if controller.record_capture_end_time > 0.0 and time.perf_counter() >= controller.record_capture_end_time:
        controller._finish_record_capture()
