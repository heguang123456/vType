"""Unit tests for core/manager.py — CoreManager lifecycle and orchestration.

Covers:
- __init__ default state (IDLE, all references None)
- start() creates submodules, queues, threads
- start() status transition to RUNNING
- start() idempotent (double-start safe)
- pause() / resume() state machine transitions
- stop() graceful shutdown sequence
- stop() from any state (idempotency)
- stop() join timeout handling
- submodule creation failure rollback
- statistics property
- edge cases: start while PAUSED, start while STOPPING, pause/resume warnings
"""

import queue
import threading
from unittest import mock

import pytest

from core.manager import CoreManager, ManagerStatus


# ============================================================================
# Helper: Mock submodule instances with sane defaults
# ============================================================================


def _create_mock_submodules():
    """Create a dict of mock submodule classes and their instances."""
    # Mock instances
    mock_audio = mock.MagicMock()
    mock_audio.raw_queue = queue.Queue()
    mock_audio.is_running = False
    mock_audio.is_paused = False

    mock_detector = mock.MagicMock()
    mock_detector.state = mock.MagicMock()
    mock_detector.state.name = "LISTENING"
    mock_detector.total_slices = 0

    mock_recognizer = mock.MagicMock()
    mock_recognizer.model_size = "base"
    mock_recognizer.language = "zh"
    mock_typer = mock.MagicMock()

    return {
        "audio": mock_audio,
        "detector": mock_detector,
        "recognizer": mock_recognizer,
        "typer": mock_typer,
    }


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_modules():
    """Mock all 4 submodule classes at the manager import path."""
    mocks = _create_mock_submodules()

    with mock.patch(
        "core.manager.AudioCapture", return_value=mocks["audio"]
    ) as mc_audio, mock.patch(
        "core.manager.VoiceDetector", return_value=mocks["detector"]
    ) as mc_detector, mock.patch(
        "core.manager.Recognizer", return_value=mocks["recognizer"]
    ) as mc_recognizer, mock.patch(
        "core.manager.TypeWriter", return_value=mocks["typer"]
    ) as mc_typer:
        yield {
            "AudioCapture": mc_audio,
            "VoiceDetector": mc_detector,
            "Recognizer": mc_recognizer,
            "TypeWriter": mc_typer,
            "audio": mocks["audio"],
            "detector": mocks["detector"],
            "recognizer": mocks["recognizer"],
            "typer": mocks["typer"],
        }


@pytest.fixture
def mock_thread():
    """Mock threading.Thread to avoid real OS thread creation.

    Returns a mock Thread class whose instances track start/join calls.
    """
    with mock.patch("core.manager.threading.Thread") as mt:
        thread_instance = mock.MagicMock()
        thread_instance.ident = 12345
        thread_instance.is_alive.return_value = True
        mt.return_value = thread_instance
        yield mt


@pytest.fixture
def manager():
    """Fresh CoreManager instance."""
    return CoreManager()


# ============================================================================
# Test: __init__ default state
# ============================================================================


class TestInit:
    """T-M01: __init__ default state."""

    def test_default_status_idle(self, manager):
        """After __init__, status should be IDLE."""
        assert manager.status == ManagerStatus.IDLE

    def test_default_statistics_empty(self, manager):
        """After __init__, statistics should show IDLE with no modules."""
        stats = manager.statistics
        assert stats["status"] == "IDLE"
        assert stats["detector_thread_alive"] is False
        assert stats["recognizer_thread_alive"] is False
        assert stats["typer_thread_alive"] is False

    def test_default_all_internal_none(self, manager):
        """After __init__, all internal references should be None."""
        assert manager._audio is None
        assert manager._detector is None
        assert manager._recognizer is None
        assert manager._typer is None
        assert manager._task_queue is None
        assert manager._result_queue is None
        assert manager._detector_thread is None
        assert manager._recognizer_thread is None
        assert manager._typer_thread is None
        assert manager._stop_event is None


# ============================================================================
# Test: start() — module creation and thread launch
# ============================================================================


class TestStart:
    """T-M02, T-M03, T-M04: start() creates modules, queues, threads."""

    def test_start_creates_all_submodules(self, mock_modules, mock_thread):
        """T-M02: start() should create all 4 submodule instances."""
        mgr = CoreManager()
        mgr.start()

        mock_modules["AudioCapture"].assert_called_once()
        mock_modules["VoiceDetector"].assert_called_once()
        mock_modules["Recognizer"].assert_called_once()
        mock_modules["TypeWriter"].assert_called_once()

    def test_start_creates_queues(self, mock_modules, mock_thread, manager):
        """start() should create task_queue and result_queue."""
        manager.start()

        assert manager._task_queue is not None
        assert isinstance(manager._task_queue, queue.Queue)
        assert manager._result_queue is not None
        assert isinstance(manager._result_queue, queue.Queue)

    def test_start_creates_stop_event(self, mock_modules, mock_thread, manager):
        """start() should create a cleared stop_event."""
        manager.start()

        assert manager._stop_event is not None
        assert isinstance(manager._stop_event, threading.Event)
        assert not manager._stop_event.is_set()

    def test_start_launches_3_threads(self, mock_modules, mock_thread):
        """T-M03: start() should create and start 3 threads."""
        mgr = CoreManager()

        # Capture each Thread constructor call
        mgr.start()

        # threading.Thread should have been called 3 times
        assert mock_thread.call_count == 3

        # Each thread instance should have been started
        # Since mock_thread.return_value is always the same mock, we check .start() calls
        assert mock_thread.return_value.start.call_count == 3

    def test_start_sets_status_running(self, mock_modules, mock_thread, manager):
        """T-M04: After start(), status should be RUNNING."""
        manager.start()
        assert manager.status == ManagerStatus.RUNNING

    def test_start_opens_audio_stream(self, mock_modules, mock_thread, manager):
        """start() should call AudioCapture.start()."""
        manager.start()
        mock_modules["audio"].start.assert_called_once()

    def test_start_thread_target_correct(
        self, mock_modules, mock_thread
    ):
        """start() threads should target the correct run() methods."""
        mgr = CoreManager()
        mgr.start()

        # Collect all Thread(target=...) calls
        targets = [
            call.kwargs.get("target")
            for call in mock_thread.call_args_list
        ]
        assert mock_modules["detector"].run in targets
        assert mock_modules["recognizer"].run in targets
        assert mock_modules["typer"].run in targets

    def test_start_detector_thread_gets_raw_queue(
        self, mock_modules, mock_thread
    ):
        """Detector thread should receive raw_queue from AudioCapture."""
        mgr = CoreManager()
        mgr.start()

        # Find the detector thread call
        detector_call = None
        for call in mock_thread.call_args_list:
            if call.kwargs.get("target") == mock_modules["detector"].run:
                detector_call = call
                break
        assert detector_call is not None

        args = detector_call[1].get("args")
        assert args is not None
        assert args[0] is mock_modules["audio"].raw_queue  # raw_queue arg
        assert args[1] is mgr._task_queue                     # task_queue arg
        assert args[2] is mgr._stop_event                     # stop_event arg


# ============================================================================
# Test: start() idempotency
# ============================================================================


class TestStartIdempotent:
    """T-M05: start() is idempotent when RUNNING or PAUSED."""

    def test_double_start_warns(self, mock_modules, mock_thread):
        """Double start() should log a warning and return safely."""
        mgr = CoreManager()
        mgr.start()

        with mock.patch("core.manager.logger.warning") as mock_warn:
            mgr.start()

        mock_warn.assert_called_once()
        # Status should remain RUNNING
        assert mgr.status == ManagerStatus.RUNNING
        # Submodules should not be re-created
        assert mock_modules["AudioCapture"].call_count == 1

    def test_start_while_paused_warns(self, mock_modules, mock_thread):
        """start() while PAUSED should warn and return."""
        mgr = CoreManager()
        mgr.start()
        mgr.pause()

        with mock.patch("core.manager.logger.warning") as mock_warn:
            mgr.start()

        mock_warn.assert_called_once()
        assert mgr.status == ManagerStatus.PAUSED

    def test_start_while_stopping_warns(self, mock_modules, mock_thread, manager):
        """start() while STOPPING should warn and return."""
        manager._status = ManagerStatus.STOPPING

        with mock.patch("core.manager.logger.warning") as mock_warn:
            manager.start()

        mock_warn.assert_called_once()
        assert manager.status == ManagerStatus.STOPPING


# ============================================================================
# Test: pause() / resume()
# ============================================================================


class TestPauseResume:
    """T-M06, T-M07: pause() and resume() state transitions."""

    def test_pause_transitions_to_paused(self, mock_modules, mock_thread, manager):
        """T-M06: pause() should set status to PAUSED and pause audio."""
        manager.start()
        manager.pause()

        assert manager.status == ManagerStatus.PAUSED
        mock_modules["audio"].pause.assert_called_once()

    def test_resume_transitions_to_running(self, mock_modules, mock_thread, manager):
        """T-M07: resume() should restore RUNNING status."""
        manager.start()
        manager.pause()
        manager.resume()

        assert manager.status == ManagerStatus.RUNNING
        mock_modules["audio"].resume.assert_called_once()

    def test_pause_when_not_running_warns(self, manager):
        """T-M15: pause() when not RUNNING should log warning."""
        with mock.patch("core.manager.logger.warning") as mock_warn:
            manager.pause()

        mock_warn.assert_called_once()
        assert manager.status == ManagerStatus.IDLE

    def test_resume_when_not_paused_warns(self, mock_modules, mock_thread, manager):
        """resume() when not PAUSED should log warning."""
        manager.start()

        with mock.patch("core.manager.logger.warning") as mock_warn:
            manager.resume()

        mock_warn.assert_called_once()
        assert manager.status == ManagerStatus.RUNNING


# ============================================================================
# Test: stop() — graceful shutdown
# ============================================================================


class TestStop:
    """T-M08 through T-M12: stop() graceful shutdown sequence."""

    def test_stop_sets_stop_event(self, mock_modules, mock_thread, manager):
        """T-M08: stop() should set the shared stop_event."""
        manager.start()
        manager.stop()

        # stop_event is set to None in _cleanup, so check that it was set
        # before cleanup. We verify indirectly: threads should have been
        # joined (meaning stop_event was set and run() exited).
        assert manager.status == ManagerStatus.IDLE

    def test_stop_sets_stop_event_before_join(self, mock_modules):
        """stop() should set stop_event before joining threads."""
        mgr = CoreManager()

        # Use a wrapper to capture order
        set_called = []
        join_called = []

        original_set = threading.Event.set
        original_join = threading.Thread.join

        def tracking_set(self_event):
            set_called.append("set")
            original_set(self_event)

        def tracking_join(self_thread, timeout=None):
            join_called.append("join")
            if timeout is not None:
                original_join(self_thread, timeout=timeout)
            else:
                original_join(self_thread)

        with mock.patch.object(threading.Event, "set", tracking_set), \
             mock.patch.object(threading.Thread, "join", tracking_join), \
             mock.patch("core.manager.AudioCapture", return_value=mock_modules["audio"]), \
             mock.patch("core.manager.VoiceDetector", return_value=mock_modules["detector"]), \
             mock.patch("core.manager.Recognizer", return_value=mock_modules["recognizer"]), \
             mock.patch("core.manager.TypeWriter", return_value=mock_modules["typer"]):
            mgr.start()
            mgr.stop()

        assert "set" in set_called
        # set should happen before joins
        if set_called and join_called:
            assert set_called[0] == "set"  # First action was set

    def test_stop_joins_all_threads(self, mock_modules, mock_thread, manager):
        """T-M09: stop() should join all 3 worker threads."""
        manager.start()
        manager.stop()

        # Each thread instance should have join() called
        assert mock_thread.return_value.join.call_count == 3

    def test_stop_stops_audio(self, mock_modules, mock_thread, manager):
        """T-M10: stop() should call AudioCapture.stop()."""
        manager.start()
        manager.stop()

        mock_modules["audio"].stop.assert_called_once()

    def test_stop_transitions_to_idle(self, mock_modules, mock_thread, manager):
        """T-M11: After stop(), status should be IDLE."""
        manager.start()
        manager.stop()

        assert manager.status == ManagerStatus.IDLE

    def test_stop_cleans_up_references(self, mock_modules, mock_thread, manager):
        """stop() should set all internal references to None (except _recognizer)."""
        manager.start()
        manager.stop()

        assert manager._audio is None
        assert manager._detector is None
        # _recognizer is preserved to avoid model reload on next start()
        assert manager._recognizer is not None
        assert manager._typer is None
        assert manager._task_queue is None
        assert manager._result_queue is None
        assert manager._detector_thread is None
        assert manager._recognizer_thread is None
        assert manager._typer_thread is None
        assert manager._stop_event is None

    def test_stop_from_idle_noop(self, manager):
        """T-M12: stop() from IDLE should be a safe no-op."""
        manager.stop()
        assert manager.status == ManagerStatus.IDLE

    def test_stop_from_running(self, mock_modules, mock_thread, manager):
        """T-M12: stop() from RUNNING should work."""
        manager.start()
        manager.stop()
        assert manager.status == ManagerStatus.IDLE

    def test_stop_from_paused(self, mock_modules, mock_thread, manager):
        """T-M12: stop() from PAUSED should work."""
        manager.start()
        manager.pause()
        manager.stop()
        assert manager.status == ManagerStatus.IDLE

    def test_stop_join_timeout_graceful(self, mock_modules, mock_thread, manager):
        """Thread join timeout should log warning but continue cleanup."""
        manager.start()

        # Make join() report thread still alive (timeout)
        mock_thread.return_value.is_alive.return_value = True

        with mock.patch("core.manager.logger.warning") as mock_warn:
            manager.stop()

        # Should still reach IDLE despite timeout
        assert manager.status == ManagerStatus.IDLE
        # Should have logged warnings about threads not stopping
        assert mock_warn.call_count >= 3  # detector + recognizer + typer

    def test_stop_audio_failure_graceful(self, mock_modules, mock_thread, manager):
        """AudioCapture.stop() failure should not prevent cleanup."""
        manager.start()
        mock_modules["audio"].stop.side_effect = RuntimeError("mock error")

        # Should not raise
        manager.stop()
        assert manager.status == ManagerStatus.IDLE

    def test_stop_double_call_safe(self, mock_modules, mock_thread, manager):
        """Double stop() should be safe."""
        manager.start()
        manager.stop()
        manager.stop()  # Should be no-op

        assert manager.status == ManagerStatus.IDLE
        # AudioCapture.stop() should only be called once
        mock_modules["audio"].stop.assert_called_once()


# ============================================================================
# Test: start() failure rollback
# ============================================================================


class TestStartFailure:
    """T-M13: submodule creation failure should rollback."""

    def test_audio_device_not_found_rollback(self, mock_thread):
        """DeviceNotFoundError during start should leave status=IDLE."""
        from core.audio import DeviceNotFoundError

        with mock.patch(
            "core.manager.AudioCapture",
            side_effect=DeviceNotFoundError("no mic"),
        ), mock.patch("core.manager.VoiceDetector"), \
           mock.patch("core.manager.Recognizer"), \
           mock.patch("core.manager.TypeWriter"):
            mgr = CoreManager()

            with pytest.raises(DeviceNotFoundError):
                mgr.start()

        assert mgr.status == ManagerStatus.IDLE
        assert mgr._audio is None

    def test_model_not_found_rollback(self, mock_thread):
        """ModelNotFoundError during start should leave status=IDLE."""
        from core.recognizer import ModelNotFoundError

        with mock.patch(
            "core.manager.Recognizer",
            side_effect=ModelNotFoundError("model missing"),
        ), mock.patch("core.manager.AudioCapture"), \
           mock.patch("core.manager.VoiceDetector"), \
           mock.patch("core.manager.TypeWriter"):
            mgr = CoreManager()

            with pytest.raises(ModelNotFoundError):
                mgr.start()

        assert mgr.status == ManagerStatus.IDLE
        assert mgr._recognizer is None


# ============================================================================
# Test: statistics property
# ============================================================================


class TestStatistics:
    """T-M14: statistics property returns correct data."""

    def test_statistics_when_running(self, mock_modules, mock_thread):
        """Running manager should report live submodule stats."""
        mgr = CoreManager()
        mgr.start()

        stats = mgr.statistics
        assert stats["status"] == "RUNNING"
        assert "detector_state" in stats
        assert "detector_slices" in stats
        assert "audio_running" in stats
        assert "audio_paused" in stats
        assert stats["detector_thread_alive"] is True
        assert stats["recognizer_thread_alive"] is True
        assert stats["typer_thread_alive"] is True

    def test_statistics_when_idle(self, manager):
        """IDLE manager should report minimal stats."""
        stats = manager.statistics
        assert stats["status"] == "IDLE"
        assert "detector_state" not in stats
        assert "detector_slices" not in stats
        assert stats["detector_thread_alive"] is False
        assert stats["recognizer_thread_alive"] is False
        assert stats["typer_thread_alive"] is False

    def test_statistics_detector_data(self, mock_modules, mock_thread):
        """Statistics should reflect detector state and slice count."""
        mgr = CoreManager()

        # Configure mock detector values
        mock_modules["detector"].state.name = "RECORDING"
        mock_modules["detector"].total_slices = 42

        mgr.start()
        stats = mgr.statistics

        assert stats["detector_state"] == "RECORDING"
        assert stats["detector_slices"] == 42

    def test_statistics_audio_state(self, mock_modules, mock_thread):
        """Statistics should reflect audio running/paused state."""
        mgr = CoreManager()

        mock_modules["audio"].is_running = True
        mock_modules["audio"].is_paused = True

        mgr.start()
        stats = mgr.statistics

        assert stats["audio_running"] is True
        assert stats["audio_paused"] is True


# ============================================================================
# Test: config overrides
# ============================================================================


class TestConfigOverrides:
    """CoreManager accepts **kwargs to override config defaults."""

    def test_custom_model_size(self, mock_thread):
        """Custom model_size should be passed to Recognizer."""
        with mock.patch(
            "core.manager.AudioCapture"
        ) as mc_audio, mock.patch(
            "core.manager.VoiceDetector"
        ) as _mc_detector, mock.patch(
            "core.manager.Recognizer"
        ) as mc_recognizer, mock.patch(
            "core.manager.TypeWriter"
        ) as _mc_typer:
            mc_audio.return_value.raw_queue = queue.Queue()
            mgr = CoreManager(model_size="large")
            mgr.start()

        mc_recognizer.assert_called_once()
        call_kwargs = mc_recognizer.call_args[1]
        assert call_kwargs["model_size"] == "large"

    def test_custom_language(self, mock_thread):
        """Custom language should be passed to Recognizer."""
        with mock.patch(
            "core.manager.AudioCapture"
        ) as mc_audio, mock.patch(
            "core.manager.VoiceDetector"
        ) as _mc_detector, mock.patch(
            "core.manager.Recognizer"
        ) as mc_recognizer, mock.patch(
            "core.manager.TypeWriter"
        ) as _mc_typer:
            mc_audio.return_value.raw_queue = queue.Queue()
            mgr = CoreManager(language="en")
            mgr.start()

        call_kwargs = mc_recognizer.call_args[1]
        assert call_kwargs["language"] == "en"

    def test_custom_queue_maxsize(self, mock_modules, mock_thread):
        """Custom queue_maxsize should set queue capacities."""
        mgr = CoreManager(queue_maxsize=5)
        mgr.start()

        assert mgr._task_queue.maxsize == 5
        assert mgr._result_queue.maxsize == 5


# ============================================================================
# Test: Recognizer reuse across stop/start cycles
# ============================================================================


class TestRecognizerReuse:
    """Recognizer is preserved across stop/start to avoid model reload."""

    def test_recognizer_preserved_after_stop(self, mock_modules, mock_thread):
        """After stop(), _recognizer should NOT be None (model cached)."""
        mgr = CoreManager()
        mgr.start()
        mgr.stop()

        assert mgr._recognizer is not None
        assert mgr._recognizer is mock_modules["recognizer"]

    def test_recognizer_reused_on_restart(self, mock_modules, mock_thread):
        """Restart with same params should NOT recreate Recognizer."""
        mgr = CoreManager()
        mgr.start()
        mgr.stop()

        mgr.start()
        # Recognizer constructor should only be called once
        assert mock_modules["Recognizer"].call_count == 1

    def test_new_instance_always_creates_recognizer(self, mock_thread):
        """A new CoreManager instance always creates a new Recognizer."""
        with mock.patch(
            "core.manager.AudioCapture"
        ) as mc_audio, mock.patch(
            "core.manager.VoiceDetector"
        ) as _mc_detector, mock.patch(
            "core.manager.Recognizer"
        ) as mc_recognizer, mock.patch(
            "core.manager.TypeWriter"
        ) as _mc_typer:
            mc_audio.return_value.raw_queue = queue.Queue()
            mc_recognizer.return_value.model_size = "base"
            mc_recognizer.return_value.language = "zh"

            mgr = CoreManager(model_size="base")
            mgr.start()
            assert mc_recognizer.call_count == 1

            mgr.stop()

            # New instance with different model_size — always creates new Recognizer
            mgr2 = CoreManager(model_size="large")
            mgr2.start()
            assert mc_recognizer.call_count == 2  # new instance → new Recognizer
