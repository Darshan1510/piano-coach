"""MIDI service logic without CoreMIDI: a fake backend feeds messages directly."""

import mido
import pytest

from riyaz.midi_io import MidiService


class FakePort:
    def __init__(self, name, callback=None):
        self.name = name
        self.callback = callback
        self.sent = []
        self.closed = False

    def send(self, msg):
        self.sent.append(msg)

    def close(self):
        self.closed = True

    def feed(self, msg):
        self.callback(msg)


class FakeBackend:
    def __init__(self, inputs=(), outputs=None):
        self.inputs = list(inputs)
        self.outputs = list(inputs if outputs is None else outputs)
        self.opened_in = {}
        self.opened_out = {}

    def get_input_names(self):
        return list(self.inputs)

    def get_output_names(self):
        return list(self.outputs)

    def open_input(self, name, callback=None):
        if name not in self.inputs:
            raise OSError("unknown port")
        port = FakePort(name, callback)
        self.opened_in[name] = port
        return port

    def open_output(self, name):
        port = FakePort(name)
        self.opened_out[name] = port
        return port


@pytest.fixture
def events():
    return []


def make(store, events, inputs=("USB MIDI Interface",)):
    backend = FakeBackend(inputs)
    svc = MidiService(store, sink=events.append, backend=backend)
    return svc, backend


def on(note, vel=80, ch=0):
    return mido.Message("note_on", note=note, velocity=vel, channel=ch)


def types(events, kind):
    return [e for e in events if e["type"] == kind]


def test_auto_pick_single_port_and_remember(store, events):
    svc, backend = make(store, events)
    status = svc.scan()
    assert status["connected"] and status["port"] == "USB MIDI Interface"
    assert store.get("midi.input") == "USB MIDI Interface"


def test_no_auto_pick_with_two_ports_but_ignores_iac(store, events):
    svc, _ = make(store, events, inputs=("Cable A", "Cable B"))
    assert not svc.scan()["connected"]
    svc2, _ = make(store, [], inputs=("IAC Driver Bus 1", "UM-ONE"))
    assert svc2.scan()["port"] == "UM-ONE"


def test_remembered_port_wins(store, events):
    store.set("midi.input", "Cable B")
    svc, _ = make(store, events, inputs=("Cable A", "Cable B"))
    assert svc.scan()["port"] == "Cable B"


def test_select_port(store, events):
    svc, _ = make(store, events, inputs=("Cable A", "Cable B"))
    svc.scan()
    assert svc.select_port("Cable A")["port"] == "Cable A"
    assert store.get("midi.input") == "Cable A"
    with pytest.raises(ValueError):
        svc.select_port("Nope")


def test_velocity_zero_is_note_off(store, events):
    svc, _ = make(store, events)
    svc.handle_message(on(60, 90), t=1.0)
    svc.handle_message(on(60, 0), t=1.5)
    notes = [e for e in events if e["type"] in ("note_on", "note_off")]
    assert notes[0] == {"type": "note_on", "pitch": 60, "raw": 60, "vel": 90, "ch": 1, "t": 1.0}
    assert notes[1]["type"] == "note_off" and notes[1]["pitch"] == 60
    # real note_off also works
    svc.handle_message(on(62), t=2.0)
    svc.handle_message(mido.Message("note_off", note=62), t=2.1)
    assert types(events, "note_off")[-1]["pitch"] == 62


def test_ignores_clock_sysex_program_change_other_cc(store, events):
    svc, _ = make(store, events)
    for msg in (mido.Message("clock"), mido.Message("start"), mido.Message("stop"),
                mido.Message("sysex", data=[1, 2]), mido.Message("program_change", program=3),
                mido.Message("control_change", control=7, value=100),
                mido.Message("active_sensing")):
        assert svc.handle_message(msg) is None
    assert events == []


def test_sustain_cc64(store, events):
    svc, _ = make(store, events)
    svc.handle_message(mido.Message("control_change", control=64, value=127))
    svc.handle_message(mido.Message("control_change", control=64, value=0))
    cc = types(events, "cc")
    assert [c["value"] for c in cc] == [127, 0]
    assert cc[0]["control"] == 64


def test_keys_event_has_chord(store, events):
    svc, _ = make(store, events)
    for n in (60, 64, 67):
        svc.handle_message(on(n))
    keys = types(events, "keys")[-1]
    assert keys["held"] == [60, 64, 67]
    assert keys["names"] == ["C", "E", "G"]
    assert keys["chord"]["name"] == "C"


def test_calibration_middle_c_with_plus_12_shift(store, events):
    svc, _ = make(store, events)
    svc.start_capture("middle_c")
    svc.handle_message(on(72))  # keyboard OCTAVE +1: middle C arrives as 72
    cal = types(events, "calibration")[-1]
    assert cal["offset"] == -12 and cal["channel"] == 1
    assert types(events, "note_on")[-1]["pitch"] == 60
    # Stored
    assert store.get("calibration.offset") == -12
    # Shifted melody shows correct notes
    events.clear()
    for n in (60, 62, 64, 65, 67):
        svc.handle_message(on(n + 12))
        svc.handle_message(on(n + 12, 0))
    assert [e["pitch"] for e in types(events, "note_on")] == [60, 62, 64, 65, 67]
    assert [e["pitch"] for e in types(events, "note_off")] == [60, 62, 64, 65, 67]
    # New service (app restart) loads the stored offset
    events2 = []
    svc2 = MidiService(store, sink=events2.append, backend=FakeBackend(["USB MIDI Interface"]))
    svc2.handle_message(on(72))
    assert types(events2, "note_on")[0]["pitch"] == 60


def test_channel_filter_after_calibration(store, events):
    svc, _ = make(store, events)
    svc.start_capture("middle_c")
    svc.handle_message(on(60, ch=0))
    events.clear()
    assert svc.handle_message(on(48, ch=2)) is None  # style / split notes on channel 3
    assert svc.handle_message(on(64, ch=0))["pitch"] == 64


def test_note_off_uses_pitch_from_press_time(store, events):
    svc, _ = make(store, events)
    svc.handle_message(on(72))
    svc.set_calibration(-12, 0)
    svc.handle_message(on(72, 0))
    assert types(events, "note_off")[-1]["pitch"] == 72


def test_setup_test_step(store, events):
    svc, _ = make(store, events)
    svc.start_capture("test")
    svc.handle_message(on(50, ch=4))
    setup = types(events, "setup")
    assert setup and setup[0]["ok"] and setup[0]["ch"] == 5
    assert svc.capture_mode is None


def test_touch_step_and_touch_off_detection(store, events):
    svc, _ = make(store, events)
    svc.start_capture("touch")
    for v in (30, 35, 28, 40, 100, 110, 105, 120):
        svc.handle_message(on(60, v))
        svc.handle_message(on(60, 0))
    result = [e for e in types(events, "calibration") if e["step"] == "touch"][-1]
    assert result["touch_on"] and result["velocity_range"] == [28, 120]
    assert store.get("calibration.velocity_range") == [28, 120]
    # TOUCH off: all velocities equal
    events.clear()
    svc.start_capture("touch")
    for _ in range(8):
        svc.handle_message(on(60, 100))
    result = [e for e in types(events, "calibration") if e["step"] == "touch"][-1]
    assert result["touch_on"] is False


def test_hotplug_disconnect_releases_held_keys_and_reconnects(store, events):
    svc, backend = make(store, events)
    svc.scan()
    port = backend.opened_in["USB MIDI Interface"]
    port.feed(on(60))
    port.feed(mido.Message("control_change", control=64, value=127))
    backend.inputs = []  # cable pulled
    status = svc.scan()
    assert not status["connected"]
    off = types(events, "note_off")[-1]
    assert off["pitch"] == 60 and off["reason"] == "disconnect"
    assert types(events, "cc")[-1]["value"] == 0
    assert port.closed
    backend.inputs = ["USB MIDI Interface"]  # plugged in again
    assert svc.scan()["connected"]
    assert [e["connected"] for e in types(events, "status")][-2:] == [False, True]


def test_local_on_at_stop_if_app_set_local_off(store, events):
    svc, backend = make(store, events)
    svc.scan()
    assert svc.set_local_control(False)
    out = backend.opened_out["USB MIDI Interface"]
    assert out.sent[-1].control == 122 and out.sent[-1].value == 0
    assert store.get("midi.local_off_pending") is True
    svc.stop()
    assert out.sent[-1].control == 122 and out.sent[-1].value == 127
    assert store.get("midi.local_off_pending") is False


def test_local_on_after_crash(store, events):
    store.set("midi.local_off_pending", True)
    svc, backend = make(store, events)
    svc.scan()
    sent = backend.opened_out["USB MIDI Interface"].sent
    assert sent and sent[-1].control == 122 and sent[-1].value == 127


def test_play_test_note_uses_output(store, events):
    svc, backend = make(store, events)
    svc.scan()
    assert svc.play_test_note(seconds=0.01)
    assert backend.opened_out["USB MIDI Interface"].sent[0].type == "note_on"
    svc2, _ = make(store, [], inputs=())
    assert not svc2.play_test_note()


def test_port_filter_shows_only_matching_ports(store, events):
    backend = FakeBackend(["USB MIDI Interface", "Riyaz Test Keyboard"])
    svc = MidiService(store, sink=events.append, backend=backend, port_filter="Riyaz Test")
    status = svc.scan()
    assert status["inputs"] == ["Riyaz Test Keyboard"] and status["port"] == "Riyaz Test Keyboard"


def test_port_filter_from_env(store, events, monkeypatch):
    monkeypatch.setenv("RIYAZ_PORT_FILTER", "Riyaz Test")
    svc, _ = make(store, events, inputs=("USB MIDI Interface", "Riyaz Test Keyboard"))
    assert svc.scan()["inputs"] == ["Riyaz Test Keyboard"]


def test_key_held_before_calibration_is_released_on_other_channel(store, events):
    # Stuck-key case: a key on channel 10 is down, then middle C calibrates channel 1.
    svc, _ = make(store, events)
    svc.handle_message(on(48, ch=9))
    svc.start_capture("middle_c")
    svc.handle_message(on(60, ch=0))
    assert svc.channel == 0
    off = svc.handle_message(on(48, 0, ch=9))  # its note_off must not be dropped
    assert off is not None and off["type"] == "note_off" and off["pitch"] == 48
    assert types(events, "keys")[-1]["held"] == [60]
    # A new press on channel 10 is still dropped.
    assert svc.handle_message(on(50, ch=9)) is None
    assert svc.handle_message(on(50, 0, ch=9)) is None


def test_setup_test_step_uses_known_channel(store, events):
    svc, _ = make(store, events)
    svc.set_calibration(0, 0)
    svc.start_capture("test")
    assert svc.handle_message(on(48, ch=9)) is None  # style note on channel 10: not the test key
    assert svc.capture_mode == "test" and not types(events, "setup")
    assert svc.held == {}  # nothing on channel 10 can get stuck
    svc.handle_message(on(60, ch=0))
    assert types(events, "setup")[0]["ch"] == 1 and svc.capture_mode is None


def test_disconnect_sustain_off_uses_channel_1_to_16(store, events):
    svc, backend = make(store, events)
    svc.scan()
    backend.opened_in["USB MIDI Interface"].feed(mido.Message("control_change", control=64, value=127))
    backend.inputs = []
    svc.scan()
    cc = types(events, "cc")[-1]
    assert cc["reason"] == "disconnect" and cc["ch"] == 1


def test_stop_sends_pending_test_note_off_and_cancels_timer(store, events):
    svc, backend = make(store, events)
    svc.scan()
    assert svc.play_test_note(seconds=30)
    timer = next(iter(svc._pending_offs))
    assert timer.daemon
    out = backend.opened_out["USB MIDI Interface"]
    svc.stop()
    assert not timer.is_alive() or timer.finished.is_set()
    assert [(m.type, m.velocity) for m in out.sent if m.type == "note_on"] == [("note_on", 90), ("note_on", 0)]
    assert svc._outport is None
    # After stop: no new test note, and the output port is not opened again.
    n_opened = len(backend.opened_out)
    assert not svc.play_test_note()
    assert not svc.send(mido.Message("note_on", note=60, velocity=0))
    assert svc._outport is None and len(backend.opened_out) == n_opened


def test_echo_of_app_song_note_is_dropped_and_real_press_counts(store, events):
    """A song note that the app sends to the keyboard and that comes back (MIDI thru) is no key."""
    from riyaz import config
    from riyaz.practice import EchoGuard

    svc, _ = make(store, events)
    guard = EchoGuard()
    svc.echo_filter = guard.is_echo
    guard.sent(60, 10.0)  # the app sent raw note 60 at t = 10.0
    assert svc.handle_message(on(60), t=10.0 + config.ECHO_WINDOW_S / 2) is None  # the echo
    assert svc.handle_message(on(60, 0), t=10.4) is None  # its note off
    assert types(events, "note_on") == [] and types(events, "note_off") == [] and svc.held == {}
    # The user presses the same key after the window: it counts.
    assert svc.handle_message(on(60), t=10.0 + config.ECHO_WINDOW_S + 0.2)["type"] == "note_on"
    assert svc.handle_message(on(60, 0), t=11.0)["type"] == "note_off"
    # A different key at the time of a send is not an echo.
    guard.sent(62, 20.0)
    assert svc.handle_message(on(64), t=20.01)["type"] == "note_on"
    # One send = one echo: a second note_on of the same key in the window counts.
    guard.sent(65, 30.0)
    assert svc.handle_message(on(65), t=30.01) is None
    assert svc.handle_message(on(65, 0), t=30.02) is None
    assert svc.handle_message(on(65), t=30.03)["type"] == "note_on"
