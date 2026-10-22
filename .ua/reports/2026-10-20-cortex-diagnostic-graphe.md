# Cortex — diagnostic par le graphe Understand-Anything (2026-10-20)

Dépôt `cdeust/Cortex`, `main` = `df3a4479`. Graphe : `Cortex/.ua/knowledge-graph.json`
(Understand-Anything v2.9.7, 4 197 fichiers, 11 771 nœuds, 24 578 liens après corrections, validation 0 issue).
Toutes les mesures ci-dessous sont reproductibles avec `Cortex/.ua/probe/` (harnais) depuis un HOME vierge,
sans `DATABASE_URL` ni variable `PG*`, avec un faux serveur qui journalise toute connexion sur `127.0.0.1:5432`.

---

## D1 — Corrections du graphe (gaps)

**Modifications**
1. `gapfix/link_runtime_tested_by.py` : +111 liens `tested_by` (scripts/* → tests qui les chargent à
   l'exécution : `from scripts…`, `sys.path` + import, chemin littéral non-docstring). 38 nœuds tagués `tested`.
   Preuve `fichier:ligne` dans chaque lien (`evidence`). Liste : `gapfix/added_tested_by.json`.
2. `gapfix/link_ast_calls.py` : +2 191 liens `calls` reconstruits par AST, y compris les **imports différés
   à l'intérieur des fonctions** (idiome de latence des hooks) que les analyseurs LLM avaient manqués.
   Liste : `gapfix/added_calls.json`.
3. `gapfix/flag_stale_docs.py` : contrôle des ADR dont la source est absente, **en tenant compte du statut**.
   Résultat dans `gapfix/stale_sources.json`.

**Raison** — le graphe ne montrait pas la chaîne `_auto_wire_pipeline → ensure_pipeline_connection →
install_pipeline → _install_locked` (3 liens manquants), ni les tests du lanceur : impossible de tracer
les issues d'installation sans eux.

**Résultante** — chaîne complète présente ; graphe revalidé (0 issue) ; état « avant » conservé dans
`gapfix/knowledge-graph.before.json`.

**Rectification** — j'avais annoncé 7 « ADR périmés ». C'est faux pour 4 d'entre eux : ADR-0737/0750/0752/0775
sont marqués `superseded by ADR-1092` ; l'absence de leur source est attendue. Résidu réel : 5 paires d'ADR
(0703, 0710, 0711, 0764 et miroirs `docs/adr/`) citent `tasks/codex-green-remediation-plan.md`, **jamais
commité** (`git log` vide) ; ADR-0618 cite un fichier local `~/.claude/plans/…`. Ce sont des sources non
vérifiables au sens de la règle zététique du dépôt.

---

## D2 — Issue #704 (connexion à un PostgreSQL non configuré) : **partiellement corrigée**

| Point d'entrée (HOME vierge) | Dial `:5432` | Marqueur | Mesure |
|---|---|---|---|
| A. Hook Claude Code via `scripts/launcher.py` (`plugin.json`) | **0** | `sqlite` (fresh install) | `probe` A/A3 |
| B. Hook wheel `python -m mcp_server.hooks.entry session_start` (`hypermnesia-mcp-hook`) | **1** | aucun | `B_entry_session_start` |
| B'. idem `auto_recall` | **1** | aucun | `B_entry_auto_recall` |
| C. Serveur wheel `python -m mcp_server` (`hypermnesia-mcp`) | **1** | aucun | `C_server_direct` |

**Cause (code)** — trois résolutions du backend coexistent :
- `scripts/launcher_backend.py:145` : `apply_backend_resolution(os.environ, default="sqlite")` ✔ (ADR-1104).
- `mcp_server/hooks/entry.py:75` : `apply_backend_resolution(environ, marker_path)` **sans `default`**, puis
  `entry.py:81-82` injecte `DATABASE_URL=postgresql://localhost:5432/cortex` quand `CORTEX_RUNTIME≠cowork`.
- `mcp_server/__main__.py:22` : `apply_backend_resolution(os.environ)` **sans `default`** → moteur `auto`,
  URL par défaut `infrastructure/memory_config.py:50`.
Valeurs par défaut PG encore présentes : `hooks/session_start_common.py:14`, `hooks/auto_recall.py:60`,
`hooks/entry.py:59`, `infrastructure/memory_config.py:50`, `scripts/setup.sh:236`, `scripts/setup_db.py:58`.

**Résultante attendue de la correction** — une seule fonction de résolution (celle du lanceur, `default="sqlite"`)
appelée aussi par `hooks/entry.py` et `__main__.py`, suppression des URL PG par défaut, et le test demandé
par #704 (port 5432 écouté par un faux serveur, aucune connexion) étendu aux points d'entrée B et C.

---

## D3 — Issue #703 (`remember` échoue sans PostgreSQL) : **corrigée pour le plugin, encore vraie pour la wheel**

- `postInstall` a disparu de `.claude-plugin/plugin.json` (#749, ADR-1104) ; le marqueur est écrit au premier
  lancement (mesure A).
- Mesure C (wheel, HOME vierge) : `remember` → `database_not_connected … Cortex requires PostgreSQL in CLI mode`,
  **après** avoir journalisé « falling back to SQLite » : le log et le comportement se contredisent, et la
  promesse PRIVACY « falls back to this SQLite store » est fausse sur ce chemin.

---

## D4 — Issue #705 (installation dans un hook de 30 s) : **toujours vraie**, nouvelle cause mesurée

Pile capturée (faulthandler) sur le hook SessionStart via le lanceur, dépendances déjà installées :
`session_start.py:158 _auto_wire_pipeline` → `session_start_background.py:31` →
`pipeline_discovery.py:209 ensure_pipeline_connection` → `pipeline_installer.py:89 install_pipeline` →
`pipeline_installer.py:144 cargo build --release` (timeout 1 800 s).

- Le hook (timeout hôte **30 s**, `plugin.json`) était encore bloqué à **40 s** ; une seconde exécution a été
  tuée à 120 s. Le HOME vierge a reçu **1,2 Go et 1,5 Go** (rustup, registre cargo, clone de
  `ai-architect-mcp-codebase`).
- Chemin nominal (release disponible) : téléchargement synchrone d'un binaire d'**un autre produit** (54 Mo
  mesurés, `v0.14.0`) sans consentement — point de #705 confirmé.
- Repli : si l'API GitHub Releases échoue (hors ligne, quota non authentifié, proxy), le hook installe rustup,
  clone et compile en ligne. Dans la mesure, le repli a été pris parce que l'environnement `env -i` ne
  transmettait pas le proxy ; la condition déclenchante (échec de la release) est donc réelle mais son
  occurrence chez un utilisateur n'est pas mesurée ici.
- Désactivation existante : `CORTEX_AUTO_INSTALL_PIPELINE=0` (non documentée dans PRIVACY).

**Résultante attendue** — `_auto_wire_pipeline` hors du chemin synchrone du hook (job d'arrière-plan
borné ou commande explicite), consentement explicite pour installer un autre produit, aucun repli
rustup/cargo dans un hook, et PRIVACY listant chaque téléchargement (taille, origine).

---

## Ordre de correction proposé (une PR par sujet)

1. **#704/#703 — résolution unique du backend** (B, C) : risque données utilisateur (connexion à une base
   réelle non configurée). Test : faux serveur sur 5432, 0 connexion, `remember` OK sur SQLite.
2. **#705 — sortir l'auto-install du pipeline du hook** + consentement + PRIVACY.
3. **Marketplace pin gate** : bump `zetetic-team-subagents` v2.42.0 → v2.45.1 dans `.claude-plugin/marketplace.json`.
4. Provenance : committer ou retirer la citation `tasks/codex-green-remediation-plan.md` (5 ADR) et le chemin
   local d'ADR-0618.

## Limites

- Mesures sur Linux x86_64 (conteneur), pas sur macOS. Les durées dépendent du réseau.
- Le graphe reste incomplet sur les appels dynamiques (`getattr`, registres de handlers) : l'AST ne les résout pas.
- Une partie des résumés de fonctions de test a été générée à partir des noms (signalé par les analyseurs).

---

## D5 — Le lanceur écrit dans l'arbre du plugin quand `CLAUDE_PLUGIN_DATA` est vide (confirmé)

**Mesure** — mes sondes lancées avec `CLAUDE_PLUGIN_DATA` vide ont créé dans la racine du dépôt
`uv-0.11.3/` (58 Mo), `sets/` et `deps-install.log` (13:34:20–13:34:24 UTC). Supprimés ensuite.

**Cause** — `scripts/launcher.py:73` : `data = os.environ.get("CLAUDE_PLUGIN_DATA", "") or plugin_root`.
Repli silencieux vers le répertoire du plugin (cache en lecture seule chez l'utilisateur, ou clone
de développement). Confirme l'hypothèse non vérifiée du diagnostic initial (pollution de
`test_locate_prefers_path_uv_only_at_the_pinned_version`).

**Résultante attendue** — refus explicite (« Cortex not ready: CLAUDE_PLUGIN_DATA unset ») ou un
répertoire de données hors de l'arbre, conformément à la règle « no silent fallbacks » du dépôt.
