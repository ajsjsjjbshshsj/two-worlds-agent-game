"""T11.2: current authorized cues/words and protected WAV bytes, both real stores."""

import json
from io import BytesIO
import wave

import pytest

from tests.api import test_save_isolation as isolation
from tests.api.test_media import denied, get_media, granted
from tests.contracts.support import command, error

games = isolation.games
save_repository_factory = isolation.save_repository_factory
sqlite_repository_factory = isolation.sqlite_repository_factory


def audio(snapshot):
    return {
        asset["asset_id"]: (cue["id"], asset)
        for cue in snapshot["presentation"]["cues"]
        for asset in cue["assets"]
        if asset["kind"] != "image"
    }


@pytest.mark.parametrize("story", ["lighthouse", "starline"])
def test_authorized_audio_words_and_real_wav_are_available_for_each_role(games, story):
    factory, store, _ = games
    game, repo = factory()
    a, b, pair = game.pair()
    save = game.save(a, pair, story)
    before = repo.get_save(save["id"])
    for actor in (a, b):
        snapshot = game.read(actor, save)
        refs = audio(snapshot)
        assert refs and any(v[1]["kind"] == "narration" for v in refs.values())
        for asset_id, (_, asset) in refs.items():
            response = get_media(game, actor, save, asset_id)
            raw = store.read_media(story, "1.0.0", asset_id)
            granted(response, raw, "audio/wav")
            with wave.open(BytesIO(raw), "rb") as decoded:
                assert decoded.getnframes() > 0
            assert asset["alt_text"]
            if asset["kind"] == "narration":
                assert asset["transcript"]
    assert repo.get_save(save["id"]) == before


@pytest.mark.parametrize(
    "story,a_target,b_target,a_sound,b_sound",
    [
        (
            "lighthouse",
            "maintenance_log",
            "sea_chart",
            "emitter_click",
            "receiver_tone",
        ),
        ("starline", "station_log", "power_board", "gate_movement", "power_switch"),
    ],
)
def test_private_sound_is_not_projected_or_downloadable_until_authorized(
    games, story, a_target, b_target, a_sound, b_sound
):
    factory, _, _ = games
    game, repo = factory()
    a, b, pair = game.pair()
    outsider = game.account("第三人")
    save = game.save(a, pair, story)
    for actor, own, other in ((a, a_sound, b_sound), (b, b_sound, a_sound)):
        assert own not in audio(game.read(actor, save))
        denied(get_media(game, actor, save, own))
        denied(get_media(game, actor, save, other))
    save = game.accept(a, save, "inspect", {"target": a_target})
    save = game.accept(b, save, "inspect", {"target": b_target})
    for actor, own, other in ((a, a_sound, b_sound), (b, b_sound, a_sound)):
        received = game.read(actor, save)
        assert own in audio(received) and other not in audio(received)
        assert get_media(game, actor, save, own).status_code == 200
        denied(get_media(game, actor, save, other))
        denied(get_media(game, outsider, save, own), 404, "SAVE_NOT_FOUND")
        denied(get_media(game, None, save, own), 401, "UNAUTHENTICATED")
        assert other not in json.dumps(received["presentation"])
    # Failed commands cannot create an audio event or change words/world state.
    prior = game.read(a, save)
    aggregate = repo.get_save(save["id"])
    error(game.post(a, save, command(save, "unknown_action")), 422, "UNKNOWN_ACTION")
    assert repo.get_save(save["id"]) == aggregate
    assert game.read(a, save) == prior


def test_manual_partner_read_and_duplicate_command_keep_stable_cue_ids(games):
    factory, _, _ = games
    game, _ = factory()
    a, b, pair = game.pair()
    save = game.save(a, pair, "starline")
    save = game.accept(a, save, "inspect", {"target": "station_log"})
    save = game.accept(b, save, "inspect", {"target": "power_board"})
    save = game.accept(
        b, save, "allocate_power", {"engine": False, "sonar": True, "lamp": False}
    )
    save = game.accept(a, save, "set_echo_gate", {"position": "east"})
    before = game.read(b, save)
    assert "sonar_pulse" not in audio(before)
    payload = command(save, "scan_track")
    accepted = game.post(b, save, payload).json()
    repeated = game.post(b, save, payload).json()
    assert repeated["receipt"]["duplicate"] is True
    assert audio(accepted["save"]) == audio(repeated["save"])
    assert "sonar_pulse" in audio(accepted["save"])
    assert "sonar_pulse" not in audio(game.read(a, accepted["save"]))
