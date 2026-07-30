"""Language-aware decision / error / success cue detection (issue #158).

Pure business logic — no I/O. Single purpose: decide whether memory
content carries a decision, error, or success cue so the write gate can
honor ``bypass_decision`` / ``bypass_error`` and the neuromodulation
success signal regardless of the language the note is written in.

Detection order and rationale
-----------------------------
1. **Structural markers** (error detector only, checked first): runtime
   artifacts — traceback headers, stack-trace frames, CamelCase
   exception class names, POSIX signal names — are emitted by
   interpreters and runtimes in fixed ASCII form regardless of the
   author's natural language. They are matched case-SENSITIVELY because
   the casing is the signal (``ValueError`` vs. prose "value error").
2. **Multilingual keyword sets**: per-language regex fragments, one
   entry per language, each with a provenance comment listing the
   surface forms it covers. English entries are byte-for-byte the
   pre-#158 patterns, so English behavior is a strict superset of the
   old behavior (no English regressions).

Language selection (each language must trace to a source):
  - en — original behavior (``_DECISION_KW`` / ``_ERROR_KW`` /
    ``_SUCCESS_KW`` before this module existed).
  - es, pt, ru, ja — the four languages Stack Overflow runs dedicated
    non-English sites for (es/pt/ru/ja.stackoverflow.com), the best
    available demand signal for non-English developer populations.
    source: https://en.wikipedia.org/wiki/Stack_Overflow ("available in
    English, Spanish, Russian, Portuguese, and Japanese").
  - de, fr — remaining top web content languages after the above.
    source: https://w3techs.com/technologies/overview/content_language
    (W3Techs, Usage statistics of content languages for websites).
  - ro — the reporting user's repro language in issue #158.

Precision/recall trade-off (deliberate, recall-biased): a false
positive here costs one extra stored memory that ``try_curation``
merges/links afterwards (see ``write_gate.determine_bypass`` docstring);
a false negative silently drops a decision/error note as a "duplicate"
(the issue #158 failure). Stems therefore use ``\\w*`` suffixes to cover
inflection, and rare cross-language collisions (noted inline) are
accepted. The ``important``/``critical`` tag and ``force=True`` remain
the universal, language-independent fallback.

For languages not listed, keyword detection does not fire; structural
error markers still work, and the tag/force fallback always works.
"""

from __future__ import annotations

import re

# ── Structural error markers (language-agnostic, case-sensitive) ──────────
# Runtime-emitted shapes; the author's natural language never changes them.
_STRUCTURAL_ERROR_PATTERNS: tuple[str, ...] = (
    # CPython traceback header — fixed string emitted by the interpreter.
    # source: https://docs.python.org/3/library/traceback.html
    r"Traceback \(most recent call last\)",
    # CPython traceback frame line: File "app.py", line 3
    # source: https://docs.python.org/3/library/traceback.html
    r"File \"[^\"]+\", line \d+",
    # JVM / Node stack frame: "at pkg.Cls.m(File.java:42)" /
    # "at fn (/app/x.js:10:5)".
    # sources: java.lang.Throwable#printStackTrace javadoc;  # noqa: ERA001
    # https://v8.dev/docs/stack-trace-api
    r"\bat [^\s(]+ ?\([^()]*:\d+(?::\d+)?\)",
    # CamelCase exception class identifiers (ValueError,
    # NullPointerException) as printed by runtimes.
    # sources: PEP 8 (exception names use the suffix "Error");
    # Java tutorial/JLS convention (suffix "Exception")
    r"\b[A-Z][A-Za-z0-9]*(?:Error|Exception)\b",
    # POSIX signal names printed by shells/runtimes on abnormal exit.
    # source: POSIX.1-2017 <signal.h>
    r"\bSIG(?:SEGV|ABRT|BUS|FPE|ILL|KILL|TERM)\b",
)

# ── Decision cues ──────────────────────────────────────────────────────────
# "made a choice": decide / choose / switch / migrate / select / opt.
_DECISION_PATTERNS: dict[str, str] = {
    # en: verbatim pre-#158 _DECISION_KW (thermodynamics.py) — regression anchor
    "en": r"\b(?:decided|chose|switched|migrated|selected|picked|opted)\b",
    # es: decidí/decidimos/decidido, decisión, elegí/elegimos/elegido,
    #     eligió, escogimos/escogido, optamos/opté/optó/optado,
    #     seleccionó/seleccionado, cambiamos/cambié/cambió (switched)  # noqa: ERA001
    "es": (
        r"\bdecid\w*|\bdecisi[oó]n\w*|\beleg[ií]\w*|\beligi\w*|\bescog\w*"
        r"|\bopt(?:amos|é|ó|ado|aron)\b|\bseleccion\w*"
        r"|\bcambi(?:amos|é|ó)\b"
    ),
    # pt: decidimos/decidiu/decidido, decisão/decisões, escolhemos/escolhido/
    #     escolha, optamos/optou/optado, selecionou/selecionado,
    #     migramos/migrou/migrado, mudamos (switched)  # noqa: ERA001
    "pt": (
        r"\bdecid\w*|\bdecis[aã]o\b|\bdecis[oõ]es\b|\bescolh\w*"
        r"|\bopt(?:amos|ou|ado|aram)\b|\bselecion\w*"
        r"|\bmigr(?:amos|ou|ado|aram)\b|\bmudamos\b"
    ),
    # fr: décidé/décidons (accented or not), décision, choisi/choisie/
    #     choisissons, opté, sélectionné, migré/migration,
    #     basculé (switched)  # noqa: ERA001 -- multi-language prose gloss, not code
    "fr": (
        r"\bd[ée]cid\w*|\bd[ée]cisi\w*|\bchoisi\w*|\bopt[ée]\b"
        r"|\bs[ée]lectionn\w*|\bmigr[ée]\w*|\bbascul[ée]\w*"
    ),
    # de: entschied/entschieden, Entscheidung, gewählt, ausgewählt,
    #     entschlossen, migriert, gewechselt/umgestiegen (switched)  # noqa: ERA001
    "de": (
        r"\bentschied\w*|\bentscheidung\w*|\bgew[äa]hlt\b|\bausgew[äa]hlt\b"
        r"|\bentschlossen\b|\bmigriert\w*|\bgewechselt\b|\bumgestiegen\b"
    ),
    # ru: решил/решили/решено/решение, выбрал/выбрали/выбрано, выбор,
    #     перешёл/перешли (switched to), мигрировали
    "ru": (
        r"\bреши\w*|\bрешен\w*|\bрешён\w*|\bвыбр\w*|\bвыбор\w*"
        r"|\bпереш[её]л\w*|\bперешли\b|\bмигрир\w*"
    ),
    # ja: 決定 (decision), 決め(た/ました) (decided), 選択 (selection),
    #     選ん/選び (chose), 採用 (adopted), 移行 (migrated). No \b — CJK
    #     text has no word boundaries; substring match is the correct form.
    "ja": r"決定|決め|選択|選ん|選び|採用|移行",
    # ro: (am) decis, decidem, decizie/decizia, (am) ales, alegem,
    #     aleasă, optat, optăm, migrat. Issue #158 repro language.
    #     Collision note: \bales\b also matches the English plural "ales"
    #     (beers) — accepted, see recall-bias rationale in module docstring.
    "ro": (
        r"\bdecis\w*|\bdecid\w*|\bdecizi\w*|\bales\b|\baleas[aă]\b"
        r"|\baleg\w*|\boptat\b|\bopt[aă]m\b|\bmigrat\w*"
    ),
}

# ── Error cues ─────────────────────────────────────────────────────────────
_ERROR_PATTERNS: dict[str, str] = {
    # en: verbatim pre-#158 _ERROR_KW (thermodynamics.py) — regression anchor
    "en": (
        r"\b(?:error|exception|traceback|failed|failure|bug|crash|broken|"
        r"timeout|denied|rejected|deprecated)\b"
    ),
    # es: excepción, falla/fallo/falló/fallado/fallando/fallaron/fallamos,
    #     roto/rota (broken), rechazado, caída (crash/outage).
    #     "error" is identical in Spanish — already covered by en.
    #     Collision note: \brota\b also matches BrE "rota" (schedule) —
    #     accepted (recall bias).
    "es": (
        r"\bexcepci[oó]n\w*|\bfall(?:[aoó]|ad[oa]s?|ando|aron|amos)\b"
        r"|\brot[oa]s?\b|\brechazad\w*|\bca[ií]da\b"
    ),
    # pt: erro(s), exceção/exceções, falha/falhou/falhado, quebrado (broken),
    #     rejeitado, travou (froze/crashed)  # noqa: ERA001 -- language gloss, not code
    "pt": (
        r"\berros?\b|\bexce[çc][aã]o\w*|\bexce[çc][oõ]es\b|\bfalh\w*"
        r"|\bquebrad\w*|\brejeitad\w*|\btravou\b"
    ),
    # fr: erreur(s), échec(s), échoué/échouons (accented or not),
    #     rejeté, cassé/cassée(s) (broken), expiré (timed out).
    #     "exception" is identical in French — already covered by en.
    "fr": (
        r"\berreurs?\b|\b[ée]checs?\b|\b[ée]chou\w*|\brejet[ée]\w*"
        r"|\bcass[ée]e?s?\b|\bexpir[ée]\w*"
    ),
    # de: Fehler(-meldung), fehlgeschlagen/Fehlschlag, Ausnahme,
    #     Absturz/abgestürzt, kaputt, abgelehnt, defekt
    "de": (
        r"\bfehler\w*|\bfehlgeschlagen\b|\bfehlschlag\w*|\bausnahme\w*"
        r"|\babsturz\w*|\babgest[üu]rzt\b|\bkaputt\b|\babgelehnt\b|\bdefekt\w*"
    ),
    # ru: ошибка/ошибки/ошибок/ошибся, исключение, сбой/сбоя/сбои,
    #     не удалось (failed to), упал/упало (crashed), сломался (broke),
    #     отклонен/отклонён, таймаут/тайм-аут
    "ru": (
        r"\bошиб\w*|\bисключени\w*|\bсбо[йяие]\w*|\bне удалось\b"
        r"|\bупал[оаи]?\b|\bслома\w*|\bотклонен\w*|\bотклонён\w*"
        r"|\bтайм-?аут\w*"
    ),
    # ja: エラー (error), 例外 (exception), 失敗 (failure), バグ (bug),
    #     クラッシュ (crash), タイムアウト (timeout),  # noqa: ERA001
    #     拒否 (denied/rejected),  # noqa: ERA001
    #     壊れ (broken), 不具合 (defect/glitch)  # noqa: ERA001
    "ja": r"エラー|例外|失敗|バグ|クラッシュ|タイムアウト|拒否|壊れ|不具合",
    # ro: eroare/erori, excepție/excepția, eșuat/eșec (accented or not),
    #     defect, stricat (broken), respins (rejected),  # noqa: ERA001 -- gloss
    #     căzut (crashed/down)  # noqa: ERA001 -- language gloss, not code
    "ro": (
        r"\beroare\b|\berori\w*|\bexcep[țt]i\w*|\be[șs]uat\w*|\be[șs]ec\w*"
        r"|\bdefect\w*|\bstricat\w*|\brespins\w*|\bc[ăa]zut\w*"
    ),
}

# ── Success cues ───────────────────────────────────────────────────────────
_SUCCESS_PATTERNS: dict[str, str] = {
    # en: verbatim pre-#158 _SUCCESS_KW (write_gate.py) — regression anchor
    "en": r"\b(?:fixed|resolved|succeeded|passed|completed|done)\b",
    # es: arreglado/arreglamos/arreglé, resuelto/resolvimos, éxito/exitoso,
    #     completado, corregido/corregimos, funcionó, aprobado (passed),  # noqa: ERA001
    #     terminado
    "es": (
        r"\barregl\w*|\bresuelt\w*|\bresolvi\w*|\b[ée]xito\w*|\bexitos\w*"
        r"|\bcompletad\w*|\bcorregid\w*|\bcorregimos\b|\bfuncion[oó]\b"
        r"|\baprobad\w*|\bterminad\w*"
    ),
    # pt: consertado, corrigido, resolvido/resolvemos, sucesso(s),
    #     concluído, aprovado (passed), funcionou  # noqa: ERA001 -- gloss, not code
    "pt": (
        r"\bconsertad\w*|\bcorrigid\w*|\bresolvid\w*|\bresolvemos\b"
        r"|\bsucessos?\b|\bconclu[ií]d\w*|\baprovad\w*|\bfuncionou\b"
    ),
    # fr: corrigé, résolu, réussi, terminé, achevé, réparé
    #     (all with or without accents)
    "fr": (
        r"\bcorrig[ée]\w*|\br[ée]solu\w*|\br[ée]ussi\w*|\btermin[ée]\w*"
        r"|\bachev[ée]\w*|\br[ée]par[ée]\w*"
    ),
    # de: behoben, gelöst, erfolgreich, abgeschlossen, repariert,
    #     bestanden (passed), funktioniert  # noqa: ERA001 -- language gloss, not code
    "de": (
        r"\bbehoben\b|\bgel[öo]st\b|\berfolgreich\w*|\babgeschlossen\b"
        r"|\brepariert\w*|\bbestanden\b|\bfunktioniert\w*"
    ),
    # ru: исправил/исправлено/исправили, решено/решен (also "decided" —
    #     решить means both decide and solve; the overlap is inherent to the
    #     language and both cues bypass anyway), успешно/успех, завершено,
    #     починил, заработало (works now), готово (done)
    "ru": (
        r"\bисправ\w*|\bрешен\w*|\bрешён\w*|\bуспешн\w*|\bуспех\w*"
        r"|\bзаверш\w*|\bпочин\w*|\bзаработал\w*|\bготово\b"
    ),
    # ja: 修正 (fix), 解決 (resolved), 成功 (success), 完了 (completed),
    #     直した/直しました (fixed)  # noqa: ERA001
    "ja": r"修正|解決|成功|完了|直した|直しました",
    # ro: reparat, rezolvat/rezolvăm, reușit (accented or not), succes,
    #     finalizat, corectat, funcționează (it works)
    "ro": (
        r"\breparat\w*|\brezolvat\w*|\brezolv[aă]m\b|\breu[șs]it\w*"
        r"|\bsucces\w*|\bfinalizat\w*|\bcorectat\w*"
        r"|\bfunc[țt]ioneaz[ăa]\b"
    ),
}


def _compile_keyword_union(patterns: dict[str, str]) -> re.Pattern[str]:
    """Union of the per-language fragments, case-insensitive.

    IGNORECASE folds Latin and Cyrillic; it is a no-op for CJK.
    """
    return re.compile("|".join(patterns.values()), re.IGNORECASE)


_DECISION_RE = _compile_keyword_union(_DECISION_PATTERNS)
_ERROR_RE = _compile_keyword_union(_ERROR_PATTERNS)
_SUCCESS_RE = _compile_keyword_union(_SUCCESS_PATTERNS)
# Case-sensitive on purpose — casing is the structural signal (see docstring).
_STRUCTURAL_ERROR_RE = re.compile("|".join(_STRUCTURAL_ERROR_PATTERNS))


def is_decision_cue(content: str) -> bool:
    """True when content carries a decision cue in any covered language."""
    return bool(_DECISION_RE.search(content))


def is_error_cue(content: str) -> bool:
    """True on structural error markers (any language) or error keywords."""
    return bool(_STRUCTURAL_ERROR_RE.search(content) or _ERROR_RE.search(content))


def is_success_cue(content: str) -> bool:
    """True when content carries a success cue in any covered language."""
    return bool(_SUCCESS_RE.search(content))
