"""Tests for mcp_server.core.prospective — future-oriented triggers."""

from datetime import datetime, timezone

from mcp_server.core.prospective import (
    extract_prospective_intents,
    check_trigger,
)


class TestExtractProspectiveIntents:
    def test_todo_extraction(self):
        results = extract_prospective_intents("TODO: fix the memory leak in the parser")
        assert len(results) >= 1
        assert any("memory leak" in r["content"].lower() for r in results)
        assert results[0]["trigger_type"] == "keyword_match"

    def test_fixme_extraction(self):
        results = extract_prospective_intents("FIXME: handle edge case in decoder")
        assert len(results) >= 1

    def test_remember_to_extraction(self):
        results = extract_prospective_intents(
            "Remember to update the documentation after release."
        )
        assert len(results) >= 1
        assert any("update" in r["content"].lower() for r in results)

    def test_dont_forget_extraction(self):
        results = extract_prospective_intents(
            "Don't forget to run the migration script."
        )
        assert len(results) >= 1

    def test_next_time_extraction(self):
        results = extract_prospective_intents(
            "Next time check the config before deploying."
        )
        assert len(results) >= 1

    def test_no_matches_empty_content(self):
        assert extract_prospective_intents("") == []

    def test_no_matches_normal_content(self):
        results = extract_prospective_intents("The function returns a list of items.")
        assert results == []

    def test_too_short_ignored(self):
        results = extract_prospective_intents("TODO: x")
        assert results == []

    def test_multiple_intents(self):
        text = "TODO: fix parser\nFIXME: handle null\nRemember to update the docs."
        results = extract_prospective_intents(text)
        assert len(results) >= 2


class TestCheckTrigger:
    def test_directory_match(self):
        trigger = {
            "trigger_type": "directory_match",
            "trigger_condition": "/src/core",
            "target_directory": "/src/core",
        }
        assert check_trigger(trigger, directory="/src/core/module.py") is True
        assert check_trigger(trigger, directory="/other/dir") is False

    def test_keyword_match(self):
        trigger = {
            "trigger_type": "keyword_match",
            "trigger_condition": "memory leak parser",
        }
        assert check_trigger(trigger, content="Fix the memory leak") is True
        assert check_trigger(trigger, content="Hello world") is False

    def test_entity_match(self):
        trigger = {
            "trigger_type": "entity_match",
            "trigger_condition": "postgresql",
        }
        assert check_trigger(trigger, entities=["PostgreSQL"]) is True
        assert check_trigger(trigger, entities=["MySQL"]) is False
        assert check_trigger(trigger, entities=None) is False

    def test_time_based_hour(self):
        trigger = {
            "trigger_type": "time_based",
            "trigger_condition": "14:30",
        }
        match_time = datetime(2024, 1, 1, 14, 30, tzinfo=timezone.utc)
        no_match = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)
        assert check_trigger(trigger, current_time=match_time) is True
        assert check_trigger(trigger, current_time=no_match) is False

    def test_time_based_weekday(self):
        trigger = {
            "trigger_type": "time_based",
            "trigger_condition": "weekday:0",  # Monday
        }
        # 2024-01-01 is a Monday
        monday = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        tuesday = datetime(2024, 1, 2, 12, 0, tzinfo=timezone.utc)
        assert check_trigger(trigger, current_time=monday) is True
        assert check_trigger(trigger, current_time=tuesday) is False

    def test_unknown_trigger_type(self):
        trigger = {"trigger_type": "unknown", "trigger_condition": "anything"}
        assert check_trigger(trigger) is False

    def test_empty_trigger(self):
        assert check_trigger({}) is False
