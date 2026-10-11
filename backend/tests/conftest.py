"""The historical tests exercise the explicitly opt-in fictional demo API.
This fixture does NOT change the default runtime security settings.
"""
import pytest
from app.config import settings


@pytest.fixture(autouse=True)
def allow_insecure_demo_for_legacy_tests(monkeypatch):
    monkeypatch.setattr(settings, 'allow_insecure_demo_login', True)
    monkeypatch.setattr(settings, 'allow_insecure_demo_admin', True)
