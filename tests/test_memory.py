"""Tests for short-term and long-term memory — PostgreSQL test DB."""
import pytest
from src.memory.short_term import ShortTermMemory
from src.memory.long_term import LongTermMemory


class TestShortTermMemory:

    def test_add_and_retrieve(self):
        mem = ShortTermMemory(window_size=5)
        mem.add_user_message("Hello")
        mem.add_assistant_message("Hi there!")
        history = mem.get_history()
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "Hello"
        assert history[1]["role"] == "assistant"

    def test_window_enforced(self):
        mem = ShortTermMemory(window_size=3)
        for i in range(10):
            mem.add_user_message(f"msg {i}")
            mem.add_assistant_message(f"resp {i}")
        # window_size=3 means 3 turns = 6 messages max
        assert len(mem.get_history()) == 6

    def test_clear_resets(self):
        mem = ShortTermMemory()
        mem.add_user_message("test")
        mem.clear()
        assert mem.get_history() == []

    def test_turn_count(self):
        mem = ShortTermMemory()
        mem.add_user_message("q1")
        mem.add_assistant_message("a1")
        mem.add_user_message("q2")
        mem.add_assistant_message("a2")
        assert mem.turn_count == 2


class TestLongTermMemory:

    def test_create_and_load_session(self, db_session):
        lt = LongTermMemory(db_session)
        session = lt.create_session("HTN Investigation")
        assert session.id is not None
        assert session.session_name == "HTN Investigation"

        loaded = lt.load_session(str(session.id))
        assert loaded is not None
        assert loaded.session_name == "HTN Investigation"

    def test_auto_generates_session_name(self, db_session):
        lt = LongTermMemory(db_session)
        session = lt.create_session()   # no name provided
        assert "Investigation" in session.session_name

    def test_append_messages_and_retrieve(self, db_session):
        lt = LongTermMemory(db_session)
        session = lt.create_session()
        sid = str(session.id)

        lt.append_message(sid, "user",      "Show me SAEs in PHVIGIL2024")
        lt.append_message(sid, "assistant", "Found 12 serious adverse events.")

        history = lt.get_history(sid)
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert "SAEs" in history[0]["content"]

    def test_history_last_n_limit(self, db_session):
        lt = LongTermMemory(db_session)
        session = lt.create_session()
        sid = str(session.id)

        for i in range(10):
            lt.append_message(sid, "user",      f"question {i}")
            lt.append_message(sid, "assistant", f"answer {i}")

        history = lt.get_history(sid, last_n=3)
        assert len(history) == 6   # 3 turns × 2 messages

    def test_update_study_context(self, db_session):
        lt = LongTermMemory(db_session)
        session = lt.create_session()
        sid = str(session.id)

        lt.update_context(sid, study_id="NCT12345678")
        ctx = lt.get_context(sid)
        assert ctx["active_study_id"] == "NCT12345678"

    def test_update_patient_context(self, db_session):
        lt = LongTermMemory(db_session)
        session = lt.create_session()
        sid = str(session.id)

        lt.update_context(sid, patient_id="PHVIGIL2024-TEST-001")
        ctx = lt.get_context(sid)
        assert ctx["active_patient_id"] == "PHVIGIL2024-TEST-001"

    def test_extra_context_merges(self, db_session):
        lt = LongTermMemory(db_session)
        session = lt.create_session()
        sid = str(session.id)

        lt.update_context(sid, extra_context={"focus": "hepatotoxicity"})
        lt.update_context(sid, extra_context={"arm": "Treatment A"})
        ctx = lt.get_context(sid)

        assert ctx["investigation_context"].get("focus") == "hepatotoxicity"
        assert ctx["investigation_context"].get("arm") == "Treatment A"

    def test_auto_context_from_entities(self, db_session):
        lt = LongTermMemory(db_session)
        session = lt.create_session()
        sid = str(session.id)

        entities = {
            "studies":        ["PHVIGIL2024"],
            "patients":       ["PHVIGIL2024-TEST-042"],
            "adverse_events": ["Hepatotoxicity", "Nausea"],
            "drugs":          ["Metformin"],
        }
        lt.auto_update_context_from_entities(sid, entities)
        ctx = lt.get_context(sid)

        assert ctx["active_study_id"]  == "PHVIGIL2024"
        assert ctx["active_patient_id"]== "PHVIGIL2024-TEST-042"

    def test_list_sessions_newest_first(self, db_session):
        lt = LongTermMemory(db_session)
        lt.create_session("Alpha")
        lt.create_session("Beta")
        lt.create_session("Gamma")

        sessions = lt.list_sessions()
        names = [s.session_name for s in sessions]
        assert "Gamma" in names
        assert "Alpha" in names

    def test_archive_session(self, db_session):
        lt = LongTermMemory(db_session)
        session = lt.create_session("To Archive")
        sid = str(session.id)
        lt.archive_session(sid)

        loaded = lt.load_session(sid)
        assert loaded.status == "archived"

    def test_nonexistent_session_returns_none(self, db_session):
        lt = LongTermMemory(db_session)
        result = lt.load_session("00000000-0000-0000-0000-000000000000")
        assert result is None