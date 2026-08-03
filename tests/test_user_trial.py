"""Trial activation rules — legacy BYOK trial disabled."""

from app.db import SessionLocal, Base, engine
from app.models import knowledge as knowledge_models  # noqa: F401
from app.models import seo  # noqa: F401
from app.models.user_trial import TrialKeyClaim, UserTrial
from app.services.user_trial_service import try_activate_trial


def test_legacy_byok_trial_activation_disabled():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        db.query(TrialKeyClaim).delete()
        db.query(UserTrial).delete()
        db.commit()
        r = try_activate_trial(db, user_id=1, plain_api_key="sk-test-user-trial-abc123456789")
        assert r["activated"] is False
        assert r["reason"] == "legacy_disabled"
        assert r["trial"]["is_active"] is False
        assert r["trial"]["never_used"] is True
    finally:
        db.close()
