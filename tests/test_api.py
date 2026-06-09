"""Integration tests for FastAPI endpoints — PostgreSQL test DB."""
import json
import io
import pandas as pd
import pytest


class TestHealthEndpoint:

    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"


class TestSessionEndpoints:

    def test_create_session_with_name(self, client):
        resp = client.post("/sessions", json={"name": "HTN Investigation Test"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "HTN Investigation Test"
        assert "id" in data
        assert data["turn_count"] == 0

    def test_create_session_without_name(self, client):
        resp = client.post("/sessions", json={})
        assert resp.status_code == 200
        assert "Investigation" in resp.json()["name"]

    def test_list_sessions_returns_list(self, client):
        client.post("/sessions", json={"name": "List Session 1"})
        client.post("/sessions", json={"name": "List Session 2"})
        resp = client.get("/sessions")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        assert len(resp.json()) >= 2

    def test_get_session_by_id(self, client):
        create_resp = client.post("/sessions", json={"name": "Fetch Me"})
        session_id  = create_resp.json()["id"]

        resp = client.get(f"/sessions/{session_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == session_id
        assert resp.json()["name"] == "Fetch Me"

    def test_get_nonexistent_session_returns_404(self, client):
        resp = client.get("/sessions/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    def test_delete_session_archives_it(self, client):
        create_resp = client.post("/sessions", json={"name": "Archive Me"})
        session_id  = create_resp.json()["id"]

        del_resp = client.delete(f"/sessions/{session_id}")
        assert del_resp.status_code == 200

        get_resp = client.get(f"/sessions/{session_id}")
        assert get_resp.json()["status"] == "archived"


class TestIngestEndpoints:

    def test_list_documents_returns_list(self, client):
        resp = client.get("/ingest/documents")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_upload_dm_csv(self, client):
        df = pd.DataFrame([{
            "USUBJID":   "API-DM-001",
            "SUBJID":    "API-001",
            "STUDYID":   "PHVIGIL2024",
            "DOMAIN":    "DM",
            "AGE":       "40",
            "AGEU":      "YEARS",
            "SEX":       "F",
            "RACE":      "WHITE",
            "ETHNIC":    "NOT HISPANIC OR LATINO",
            "DIAGNOSIS": "Hypertension",
            "DIAGCD":    "HTN",
            "BMI":       "24.0",
            "BMICAT":    "NORMAL",
            "SMOKESTAT": "NEVER",
            "ALCOHOLUSE":"NEVER",
        }])
        buf = io.BytesIO(df.to_csv(index=False).encode())
        resp = client.post(
            "/ingest/upload",
            files={"file": ("DM.csv", buf, "text/csv")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["records"] >= 1

    def test_upload_same_file_twice_is_skipped(self, client):
        df = pd.DataFrame([{
            "USUBJID": "DEDUP-API-001", "STUDYID": "PHVIGIL2024",
            "AGE": "30", "SEX": "M",
        }])
        content = df.to_csv(index=False).encode()

        resp1 = client.post("/ingest/upload", files={"file": ("DM.csv", content, "text/csv")})
        resp2 = client.post("/ingest/upload", files={"file": ("DM.csv", content, "text/csv")})

        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert "Already" in resp2.json()["message"]

    def test_upload_clinical_trials_json(self, client):
        study = {
            "protocolSection": {
                "identificationModule": {"nctId": "NCT77777001", "briefTitle": "API JSON Test"},
                "statusModule": {"overallStatus": "RECRUITING"},
                "descriptionModule": {},
                "conditionsModule": {"conditions": ["Diabetes"]},
                "designModule": {"studyType": "INTERVENTIONAL", "phases": ["PHASE2"]},
                "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Test Org"}},
                "eligibilityModule": {},
                "armsInterventionsModule": {},
            }
        }
        content = json.dumps(study).encode()
        resp = client.post(
            "/ingest/upload",
            files={"file": ("study.json", content, "application/json")},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_upload_unsupported_format(self, client):
        resp = client.post(
            "/ingest/upload",
            files={"file": ("data.xlsx", b"fake excel", "application/octet-stream")},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False


class TestAuditEndpoints:

    def test_get_audit_trail_returns_list(self, client):
        resp = client.get("/audit")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_filter_audit_by_session(self, client):
        create_resp = client.post("/sessions", json={"name": "Audit Filter Test"})
        session_id  = create_resp.json()["id"]

        resp = client.get(f"/audit?session_id={session_id}")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)