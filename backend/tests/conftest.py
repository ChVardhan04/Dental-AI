import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="dentedge-test-")
os.environ.update({
    "APP_ENV": "test", "DATABASE_URL": os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_TMP}/test.db"), "UPLOAD_DIR": f"{_TMP}/uploads",
    "RATE_LIMIT_PER_MINUTE": "100000", "AUTH_RATE_LIMIT_PER_MINUTE": "100000", "UPLOAD_RATE_LIMIT_PER_MINUTE": "100000",
    "LLM_PROVIDER": "template", "VISION_PROVIDER": "research", "SPEECH_PROVIDER": "none", "JWT_SECRET_KEY": "test-secret-" + "x" * 40,
})
sys.path.insert(0, str(Path(__file__).parent))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.core.security import CONSENT_VERSION, hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models.user import User  # noqa: E402

PASSWORD = "Str0ngPassw0rd!"


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def _make_user(role: str, email: str) -> str:
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == email).first()
        if not u:
            u = User(full_name=f"Test {role.title()}", email=email, password_hash=hash_password(PASSWORD), role=role)
            db.add(u)
            db.commit()
        return u.id


def login(client, email: str) -> dict:
    r = client.post("/api/v1/auth/login", data={"username": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def consent_all(client, headers):
    r = client.post("/api/v1/consents", json={"consents": [{"consent_type": t, "version": CONSENT_VERSION, "accepted": True}
                                                           for t in ("ai_analysis", "data_processing", "privacy_notice")]}, headers=headers)
    assert r.status_code == 201, r.text
    assert r.json()["missing"] == []


_counter = {"n": 0}


@pytest.fixture
def world(client):
    """A consenting patient, an assigned dentist, an unassigned dentist, a second patient and an admin."""
    _counter["n"] += 1
    n = _counter["n"]
    admin_id = _make_user("admin", f"admin{n}@example.com")
    dentist_id = _make_user("dentist", f"dentist{n}@example.com")
    other_dentist_id = _make_user("dentist", f"other{n}@example.com")
    r = client.post("/api/v1/auth/register", json={"full_name": "Pat Patient", "email": f"patient{n}@example.com", "password": PASSWORD})
    assert r.status_code == 201, r.text
    patient_id = r.json()["user"]["id"]
    p_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r2 = client.post("/api/v1/auth/register", json={"full_name": "Second Patient", "email": f"patient{n}b@example.com", "password": PASSWORD})
    p2_headers = {"Authorization": f"Bearer {r2.json()['access_token']}"}
    a_headers = login(client, f"admin{n}@example.com")
    r = client.post("/api/v1/admin/assignments", json={"dentist_id": dentist_id, "patient_id": patient_id}, headers=a_headers)
    assert r.status_code == 201, r.text
    consent_all(client, p_headers)
    return {
        "patient_id": patient_id, "patient": p_headers, "patient2": p2_headers, "patient2_id": r2.json()["user"]["id"],
        "dentist_id": dentist_id, "dentist": login(client, f"dentist{n}@example.com"),
        "other_dentist": login(client, f"other{n}@example.com"), "other_dentist_id": other_dentist_id,
        "admin": a_headers, "admin_id": admin_id,
    }
