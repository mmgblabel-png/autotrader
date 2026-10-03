from types import SimpleNamespace

from autotrader.core.live_arm_state import LiveArmIntentStore
from autotrader.api import server


def test_live_arm_store_persists_for_same_release(tmp_path):
    path = tmp_path / "live-arm.json"
    store = LiveArmIntentStore(path, release_id="deploy-1")

    assert store.should_resume() is False
    record = store.write(True)
    assert record.armed is True
    assert store.load().armed is True
    assert store.should_resume() is True

    status = store.status()
    assert status["persisted_armed"] is True
    assert status["release_match"] is True
    assert status["auto_resume_eligible"] is True


def test_live_arm_store_does_not_resume_on_new_release(tmp_path):
    path = tmp_path / "live-arm.json"
    LiveArmIntentStore(path, release_id="deploy-1").write(True)

    new_release = LiveArmIntentStore(path, release_id="deploy-2")
    assert new_release.load().armed is True
    assert new_release.should_resume() is False
    assert new_release.status()["release_match"] is False


def test_live_arm_store_corrupt_state_fails_closed(tmp_path):
    path = tmp_path / "live-arm.json"
    path.write_text("{bad json", encoding="utf-8")

    store = LiveArmIntentStore(path, release_id="deploy-1")
    assert store.load().armed is False
    assert store.should_resume() is False


def test_persisted_live_arm_restores_only_after_readiness(monkeypatch, tmp_path):
    path = tmp_path / "live-arm.json"
    store = LiveArmIntentStore(path, release_id="deploy-1")
    store.write(True)

    fake_app = SimpleNamespace(
        state=SimpleNamespace(
            live_mode=True,
            live_armed=False,
            live_arm_store=store,
            live_arm_intent=True,
            live_arm_auto_resume_eligible=True,
            live_arm_restore_last_attempt=0.0,
        )
    )

    monkeypatch.setattr(
        server,
        "live_readiness",
        lambda: {"ready_to_arm": False, "gates": {"fund_nav_verified_fresh": False}},
    )
    blocked = server._maybe_restore_persisted_live_arm(fake_app)
    assert blocked["restored"] is False
    assert fake_app.state.live_armed is False

    fake_app.state.live_arm_restore_last_attempt = 0.0
    monkeypatch.setattr(
        server,
        "live_readiness",
        lambda: {"ready_to_arm": True, "gates": {"fund_nav_verified_fresh": True}},
    )
    restored = server._maybe_restore_persisted_live_arm(fake_app)
    assert restored["restored"] is True
    assert fake_app.state.live_armed is True


def test_activate_live_persists_before_arming(monkeypatch, tmp_path):
    path = tmp_path / "live-arm.json"
    store = LiveArmIntentStore(path, release_id="deploy-1")

    old_store = getattr(server.app.state, "live_arm_store", None)
    old_armed = getattr(server.app.state, "live_armed", False)
    old_intent = getattr(server.app.state, "live_arm_intent", False)
    old_eligible = getattr(server.app.state, "live_arm_auto_resume_eligible", False)
    try:
        server.app.state.live_arm_store = store
        server.app.state.live_armed = False
        server.app.state.live_arm_intent = False
        server.app.state.live_arm_auto_resume_eligible = False
        monkeypatch.setattr(server, "live_readiness", lambda: {"ready_to_arm": True, "gates": {}})

        result = server.activate_live(
            {"confirmation": "I_UNDERSTAND_LIVE_ORDERS"},
            None,
        )

        assert result["armed"] is True
        assert result["persistent"] is True
        assert server.app.state.live_armed is True
        assert store.should_resume() is True
    finally:
        server.app.state.live_arm_store = old_store
        server.app.state.live_armed = old_armed
        server.app.state.live_arm_intent = old_intent
        server.app.state.live_arm_auto_resume_eligible = old_eligible
