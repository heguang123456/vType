"""Unit tests for core/audio.py — Audio Capture Module.

Covers:
- Callback data format and routing
- Lifecycle: start/stop/pause/resume
- Device enumeration
- Error handling (device not found, PortAudio errors)
- Queue behavior (full queue, drain on stop)
"""

import queue
from unittest import mock

import numpy as np
import pytest
import sounddevice as sd

from core.audio import AudioCapture, AudioCaptureError, DeviceNotFoundError


# ============================================================================
# Mock Helpers
# ============================================================================


class _FakeInputStream:
    """Minimal mock for sounddevice.InputStream."""

    def __init__(self, **kwargs):
        self.samplerate = kwargs.get("samplerate", 16000)
        self.channels = kwargs.get("channels", 1)
        self.dtype = kwargs.get("dtype", "int16")
        self.blocksize = kwargs.get("blocksize", 320)
        self.device = kwargs.get("device", None)
        self._callback = kwargs.get("callback", None)
        self._started = False
        self._closed = False

    def start(self):
        self._started = True

    def stop(self):
        self._started = False

    def close(self):
        self._closed = True

    @property
    def active(self):
        return self._started and not self._closed


def _fake_indata(frames=320, channels=1):
    """Create a fake audio frame (simulates microphone input)."""
    return np.random.randn(frames, channels).astype(np.float32)


def _fake_time_info():
    """Simulated PortAudio CData time info."""
    return mock.MagicMock()


def _fake_query_devices():
    """Return a list with a default input device."""
    return [
        {
            "name": "Microsoft Sound Mapper - Input",
            "max_input_channels": 2,
            "max_output_channels": 0,
            "default_samplerate": 44100.0,
        },
        {
            "name": "Microphone (USB Audio Device)",
            "max_input_channels": 1,
            "max_output_channels": 0,
            "default_samplerate": 48000.0,
        },
        {
            "name": "Speakers (Realtek)",
            "max_input_channels": 0,
            "max_output_channels": 2,
            "default_samplerate": 48000.0,
        },
    ]


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_devices():
    """Patch sounddevice.query_devices and default.device."""
    with mock.patch("sounddevice.query_devices", return_value=_fake_query_devices()):
        with mock.patch.object(sd, "default", mock.MagicMock(device=[1, -1])):
            yield


@pytest.fixture
def mock_input_stream():
    """Patch sounddevice.InputStream with FakeInputStream."""
    with mock.patch("sounddevice.InputStream", new=_FakeInputStream):
        yield


@pytest.fixture
def capture(mock_devices, mock_input_stream):
    """Create a fresh AudioCapture instance for testing."""
    return AudioCapture(sample_rate=16000, channels=1, block_size=320)


# ============================================================================
# Initialization
# ============================================================================


class TestInit:
    """Verify AudioCapture initialization."""

    def test_default_parameters(self, mock_devices, mock_input_stream):
        cap = AudioCapture()
        assert cap._sample_rate == 16000
        assert cap._channels == 1
        assert cap._block_size == 320
        assert cap._dtype == "int16"
        assert cap._device_id is None

    def test_custom_parameters(self, mock_devices, mock_input_stream):
        cap = AudioCapture(
            sample_rate=44100, channels=2, block_size=512, dtype="float32", device_id=1
        )
        assert cap._sample_rate == 44100
        assert cap._channels == 2
        assert cap._block_size == 512
        assert cap._dtype == "float32"
        assert cap._device_id == 1

    def test_initial_state_not_running(self, capture):
        assert not capture.is_running
        assert not capture.is_paused

    def test_raw_queue_is_empty(self, capture):
        assert capture.raw_queue.empty()

    def test_raises_when_no_input_devices(self):
        with mock.patch("sounddevice.query_devices", return_value=[
            {"name": "Output Only", "max_input_channels": 0, "max_output_channels": 2, "default_samplerate": 48000.0}
        ]):
            with pytest.raises(DeviceNotFoundError, match="No audio input device"):
                AudioCapture()

    def test_raises_when_specific_device_not_found(self, mock_devices):
        with pytest.raises(DeviceNotFoundError, match="Device 99 not found"):
            AudioCapture(device_id=99)

    def test_raises_when_device_has_no_input_channels(self, mock_devices):
        """Device #2 in fake list is output-only."""
        with pytest.raises(DeviceNotFoundError, match="has no input channels"):
            AudioCapture(device_id=2)


# ============================================================================
# Lifecycle: start / stop
# ============================================================================


class TestStartStop:
    """Verify start/stop lifecycle."""

    def test_start_sets_running_flag(self, capture):
        capture.start()
        assert capture.is_running
        assert not capture.is_paused

    def test_stop_clears_running_flag(self, capture):
        capture.start()
        capture.stop()
        assert not capture.is_running
        assert not capture.is_paused

    def test_double_start_is_safe(self, capture):
        capture.start()
        capture.start()  # should log warning but not crash
        assert capture.is_running

    def test_double_stop_is_safe(self, capture):
        capture.start()
        capture.stop()
        capture.stop()  # should be a no-op
        assert not capture.is_running

    def test_stop_without_start_is_safe(self, capture):
        capture.stop()  # should be a no-op
        assert not capture.is_running

    def test_start_creates_stream(self, capture):
        capture.start()
        assert capture._stream is not None

    def test_stop_releases_stream(self, capture):
        capture.start()
        capture.stop()
        assert capture._stream is None

    def test_start_failure_raises(self, mock_devices):
        """If PortAudio raises, AudioCaptureError is raised."""
        with mock.patch("sounddevice.InputStream", side_effect=sd.PortAudioError("test error")):
            cap = AudioCapture()
            with pytest.raises(AudioCaptureError, match="Failed to open audio stream"):
                cap.start()


# ============================================================================
# Lifecycle: pause / resume
# ============================================================================


class TestPauseResume:
    """Verify pause/resume behavior."""

    def test_pause_sets_flag(self, capture):
        capture.start()
        capture.pause()
        assert capture.is_paused

    def test_resume_clears_flag(self, capture):
        capture.start()
        capture.pause()
        capture.resume()
        assert not capture.is_paused

    def test_pause_while_not_running_is_safe(self, capture):
        capture.pause()  # should log warning, not crash

    def test_resume_while_not_running_is_safe(self, capture):
        capture.resume()  # should log warning, not crash

    def test_stop_clears_pause_flag(self, capture):
        capture.start()
        capture.pause()
        capture.stop()
        assert not capture.is_paused


# ============================================================================
# Callback Behavior
# ============================================================================


class TestCallback:
    """Verify the audio callback function behavior."""

    def test_callback_puts_data_into_queue(self, capture):
        capture.start()
        indata = _fake_indata(320, 1)
        capture._audio_callback(indata, 320, _fake_time_info(), None)

        assert not capture.raw_queue.empty()
        frame = capture.raw_queue.get(timeout=0.1)
        assert frame.shape == (320, 1)
        assert frame.dtype == np.float32

    def test_callback_copies_data(self, capture):
        """Verify that copy() is used — modifying original doesn't affect queue."""
        capture.start()
        indata = _fake_indata(320, 1)
        original_sum = indata.sum()
        capture._audio_callback(indata, 320, _fake_time_info(), None)

        # Modify original — queued copy should be unaffected
        indata.fill(0)
        frame = capture.raw_queue.get(timeout=0.1)
        assert frame.sum() == original_sum

    def test_callback_discards_when_paused(self, capture):
        capture.start()
        capture.pause()

        indata = _fake_indata(320, 1)
        capture._audio_callback(indata, 320, _fake_time_info(), None)

        assert capture.raw_queue.empty()

    def test_callback_raises_stop_when_not_running(self, capture):
        capture.start()
        capture.stop()
        indata = _fake_indata(320, 1)
        with pytest.raises(sd.CallbackStop):
            capture._audio_callback(indata, 320, _fake_time_info(), None)

    def test_callback_handles_queue_full(self, capture):
        """When raw_queue is full, drop frame instead of blocking."""
        capture.start()
        # Fill the queue by temporarily replacing with a small queue
        capture.raw_queue = queue.Queue(maxsize=1)
        capture.raw_queue.put(np.zeros((320, 1)))  # fill it

        indata = _fake_indata(320, 1)
        # Should not block — drops frame silently
        capture._audio_callback(indata, 320, _fake_time_info(), None)
        # Queue still has only the original item
        assert capture.raw_queue.qsize() == 1

    def test_callback_handles_overflow_status(self, capture, caplog):
        capture.start()
        status = mock.MagicMock()
        status.input_overflow = True
        status.input_underflow = False
        indata = _fake_indata(320, 1)

        import logging
        with caplog.at_level(logging.WARNING):
            capture._audio_callback(indata, 320, _fake_time_info(), status)

        assert any("overflow" in msg.lower() for msg in caplog.text.lower().split())


# ============================================================================
# Device Enumeration
# ============================================================================


class TestListDevices:
    """Verify device listing."""

    def test_returns_input_devices_only(self, mock_devices):
        devices = AudioCapture.list_devices()
        # Fake list has 2 input + 1 output devices
        assert len(devices) == 2

    def test_device_has_required_keys(self, mock_devices):
        devices = AudioCapture.list_devices()
        for dev in devices:
            assert "id" in dev
            assert "name" in dev
            assert "channels" in dev
            assert "sample_rate" in dev
            assert "is_default" in dev

    def test_default_device_marked(self, mock_devices):
        devices = AudioCapture.list_devices()
        # Device #1 is default in fixture (sd.default.device[0] = 1)
        default_devices = [d for d in devices if d["is_default"]]
        assert len(default_devices) == 1
        assert default_devices[0]["id"] == 1

    def test_handles_portaudio_error(self, mock_devices):
        with mock.patch("sounddevice.query_devices", side_effect=sd.PortAudioError("error")):
            devices = AudioCapture.list_devices()
            assert devices == []  # returns empty list on error


# ============================================================================
# Queue Drain
# ============================================================================


class TestDrainQueue:
    """Verify queue drain on stop."""

    def test_drain_empties_queue(self, capture):
        for _ in range(5):
            capture.raw_queue.put(np.zeros((320, 1)))
        assert capture.raw_queue.qsize() == 5

        capture._drain_queue()
        assert capture.raw_queue.empty()

    def test_drain_empty_queue_is_safe(self, capture):
        capture._drain_queue()  # should not raise
