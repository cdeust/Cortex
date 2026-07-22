"""Unit tests for mcp_server.core.content_cues — language-aware cue detection.

Issue #158: the write-gate bypass heuristics (decision/error/success) were
English-only regexes, so non-English decision/error notes never earned
``bypass_decision``/``bypass_error`` and were rejected by novelty gating.

Covers, per detector:
  - the exact Romanian repro string from issue #158
  - at least 3 further non-English languages
  - the pre-#158 English keyword behavior (regression anchor)
  - negatives in English and a covered non-English language
  - the structural error-marker path with NO keyword match in any language
    (traceback header, stack frames, exception class names, POSIX signals)

Pure logic, no I/O, no DB.
"""

from __future__ import annotations

from mcp_server.core.content_cues import (
    is_decision_cue,
    is_error_cue,
    is_success_cue,
)


class TestDecisionCue:
    def test_issue_158_english_repro(self):
        assert is_decision_cue("DECISION: we decided to choose option A")

    def test_issue_158_romanian_repro(self):
        # Exact repro string from issue #158 — was False before the fix.
        assert is_decision_cue("Am decis sa alegem optiunea A")

    def test_spanish(self):
        assert is_decision_cue("Decidimos usar PostgreSQL en lugar de MySQL")
        assert is_decision_cue("Elegimos la opción B")

    def test_portuguese(self):
        assert is_decision_cue("Decidimos migrar para PostgreSQL")
        assert is_decision_cue("Escolhemos a segunda abordagem")

    def test_french(self):
        assert is_decision_cue("Nous avons choisi PostgreSQL")
        assert is_decision_cue("Décision : basculé vers PostgreSQL")

    def test_german(self):
        assert is_decision_cue("Wir haben uns entschieden, PostgreSQL zu verwenden")
        assert is_decision_cue("Wir sind auf PostgreSQL umgestiegen")

    def test_russian(self):
        assert is_decision_cue("Мы решили использовать PostgreSQL")
        assert is_decision_cue("Выбрали второй вариант")

    def test_japanese(self):
        assert is_decision_cue("PostgreSQLを採用することに決定した")
        assert is_decision_cue("オプションBを選んだ")

    def test_english_regressions_pre_158_keywords(self):
        # Byte-for-byte the pre-#158 _DECISION_KW words must still match.
        for kw in (
            "decided",
            "chose",
            "switched",
            "migrated",
            "selected",
            "picked",
            "opted",
        ):
            assert is_decision_cue(f"We {kw} something"), kw

    def test_negative_english(self):
        assert not is_decision_cue("The weather is nice")
        assert not is_decision_cue("Updated the README with installation instructions")

    def test_negative_romanian(self):
        assert not is_decision_cue("Vremea este frumoasa azi")


class TestErrorCue:
    def test_romanian(self):
        assert is_error_cue("A aparut o eroare la compilare")
        assert is_error_cue("Testul a esuat din nou")

    def test_spanish(self):
        assert is_error_cue("Falló la conexión a la base de datos")
        assert is_error_cue("Fallo la conexion")  # unaccented typing

    def test_german(self):
        assert is_error_cue("Der Build ist fehlgeschlagen")
        assert is_error_cue("Die Anwendung ist abgestürzt")

    def test_russian(self):
        assert is_error_cue("Произошла ошибка при сборке")
        assert is_error_cue("Не удалось подключиться к базе")

    def test_japanese(self):
        assert is_error_cue("ビルドが失敗しました")
        assert is_error_cue("タイムアウトが発生")

    def test_french(self):
        assert is_error_cue("Le déploiement a échoué")

    def test_portuguese(self):
        assert is_error_cue("O teste falhou de novo")

    def test_english_regressions_pre_158_keywords(self):
        # Byte-for-byte the pre-#158 _ERROR_KW words must still match.
        for kw in (
            "error",
            "exception",
            "traceback",
            "failed",
            "failure",
            "bug",
            "crash",
            "broken",
            "timeout",
            "denied",
            "rejected",
            "deprecated",
        ):
            assert is_error_cue(f"Saw a {kw} today"), kw

    def test_negative_english(self):
        assert not is_error_cue("Everything is fine")
        assert not is_error_cue("Normal memory")

    def test_negative_romanian(self):
        assert not is_error_cue("Totul merge bine")


class TestErrorCueStructuralMarkers:
    """Structural runtime markers fire with NO keyword match in any covered
    language — the surrounding prose below is Finnish/Romanian/German, none
    of whose words appear in any keyword set."""

    def test_python_traceback_header(self):
        assert is_error_cue("Traceback (most recent call last):")

    def test_python_frame_line(self):
        assert is_error_cue('File "app.py", line 3, in <module>')

    def test_jvm_stack_frame_in_uncovered_language(self):
        # Finnish prose (uncovered language) + JVM frame.
        assert is_error_cue("Sovellus kaatui: at com.acme.Main.run(Main.java:42)")

    def test_node_stack_frame(self):
        assert is_error_cue("at processTicks (/app/index.js:10:5)")

    def test_camelcase_exception_class(self):
        assert is_error_cue("Sovellus lopetti: NullPointerException nähtiin")
        assert is_error_cue("ValueError: invalid literal for int()")

    def test_posix_signal_name(self):
        assert is_error_cue("Prozess beendet: SIGSEGV")

    def test_structural_markers_are_case_sensitive(self):
        # Lowercase "sigsegv" is prose, not a runtime-printed signal name.
        # (No keyword set contains it either.)
        assert not is_error_cue("wrote about sigsegv handling someday")


class TestSuccessCue:
    def test_romanian(self):
        assert is_success_cue("Am rezolvat problema de memorie")

    def test_spanish(self):
        assert is_success_cue("Arreglamos el problema de memoria")
        assert is_success_cue("Los tests aprobados")

    def test_russian(self):
        assert is_success_cue("Исправлено, тесты проходят")

    def test_japanese(self):
        assert is_success_cue("バグを修正しました")

    def test_french(self):
        assert is_success_cue("Problème résolu")

    def test_german(self):
        assert is_success_cue("Der Fehler wurde behoben")

    def test_portuguese(self):
        assert is_success_cue("Problema resolvido")

    def test_english_regressions_pre_158_keywords(self):
        # Byte-for-byte the pre-#158 _SUCCESS_KW words must still match.
        for kw in ("fixed", "resolved", "succeeded", "passed", "completed", "done"):
            assert is_success_cue(f"Task {kw} today"), kw

    def test_negative_english(self):
        assert not is_success_cue("Investigating the memory layout")

    def test_negative_romanian(self):
        assert not is_success_cue("Investigam structura memoriei")
