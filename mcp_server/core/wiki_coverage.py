"""Wiki coverage audit — find missing scopes per project (domain).

source: ADR-0297"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final

from mcp_server.shared.wiki_skip_directories import SKIP_DIRECTORIES

# Composition-root injection seam (core may not import os or perform I/O;
# issue #560). Real implementations live in
# mcp_server/infrastructure/wiki_coverage_fs.py, wired once via
# configure_wiki_coverage_filesystem (mcp_server/__main__.py for
# production, tests_py/conftest.py for the test session).
StatPage = Callable[[str, str], "tuple[int, float] | None"]
MarkdownFileSizes = Callable[[str], "dict[str, int]"]
DomainKindMembership = Callable[[str, "frozenset[str]"], "dict[str, list[str]]"]
WalkSourceFiles = Callable[[str, "frozenset[str]", "frozenset[str]"], "list[str]"]
WalkMarkdownContents = Callable[[str], "list[str]"]

_stat_page: StatPage | None = None
_markdown_file_sizes: MarkdownFileSizes | None = None
_domain_kind_membership: DomainKindMembership | None = None
_walk_source_files: WalkSourceFiles | None = None
_walk_markdown_contents: WalkMarkdownContents | None = None


def configure_wiki_coverage_filesystem(
    *,
    stat_page: StatPage,
    markdown_file_sizes: MarkdownFileSizes,
    domain_kind_membership: DomainKindMembership,
    walk_source_files: WalkSourceFiles,
    walk_markdown_contents: WalkMarkdownContents,
) -> None:
    """Composition-root hook: register the real wiki-coverage filesystem ops.

    source: ADR-0297 (issue #560)"""
    global \
        _stat_page, \
        _markdown_file_sizes, \
        _domain_kind_membership, \
        _walk_source_files, \
        _walk_markdown_contents
    _stat_page = stat_page
    _markdown_file_sizes = markdown_file_sizes
    _domain_kind_membership = domain_kind_membership
    _walk_source_files = walk_source_files
    _walk_markdown_contents = walk_markdown_contents


def _unconfigured(what: str) -> RuntimeError:
    return RuntimeError(
        f"wiki_coverage {what} provider not configured — call "
        "configure_wiki_coverage_filesystem() at the composition root first"
    )


# Minimum useful page size in bytes. Below this, a page is a stub —
# the scope is not really covered.
_MIN_PAGE_BYTES = 800

# source: ADR-0297


_DEFAULT_MAX_AGE_DAYS = 90


@dataclass(frozen=True)
class Scope:
    """One structural documentation scope.

    Each scope names a category of knowledge every project should
    document. ``anchor_paths`` are wiki-relative paths (without the
    domain segment) the coverage scan looks for; the first match counts
    as coverage. ``directory`` is the wiki subtree where pages of this
    scope live — used to find substantive coverage beyond the anchor
    pages.
    """

    name: str
    title: str
    description: str
    anchor_filenames: tuple[str, ...]
    directories: tuple[str, ...]
    suggested_kind: str  # wiki kind to author the missing page as
    # source: ADR-0297

    groundable: bool = True


SCOPES: Final[tuple[Scope, ...]] = (
    # ── Technical foundation ────────────────────────────────────────────
    Scope(
        name="product-overview",
        title="Product overview",
        description=(
            "What the project IS, in one page a non-engineer (customer, "
            "partner, exec) can read. Problem, solution, who it's for, "
            "what makes it different. The page sales picks up to "
            "explain the project to a customer."
        ),
        anchor_filenames=(
            "product-overview.md",
            "overview.md",
            "what-is-this.md",
            "elevator-pitch.md",
        ),
        directories=("guides", "reference", "explanation"),
        suggested_kind="reference",
    ),
    Scope(
        name="architecture",
        title="Architecture overview",
        description=(
            "Overall design: layers, the dependency rule, the major "
            "subsystems and how they relate. The first page a new "
            "engineer should read."
        ),
        anchor_filenames=(
            "architecture-overview.md",
            "architecture.md",
        ),
        directories=("reference", "explanation", "architecture"),
        suggested_kind="explanation",
    ),
    Scope(
        name="services",
        title="Services / components inventory",
        description=(
            "Catalogue of the project's components, handlers, modules "
            "or services — what each one is responsible for, where its "
            "boundary lies, what it must not do."
        ),
        anchor_filenames=(
            "services.md",
            "components.md",
            "modules.md",
            "handlers.md",
        ),
        directories=("reference", "explanation"),
        suggested_kind="reference",
    ),
    Scope(
        name="code-walkthrough",
        title="Code walkthrough",
        description=(
            "Reading-the-code guide: where to start in the source "
            "tree, how the entry points connect, what each top-level "
            "directory means. Targeted at a new engineer cloning the "
            "repo for the first time."
        ),
        anchor_filenames=(
            "code-walkthrough.md",
            "codebase-tour.md",
            "reading-the-code.md",
        ),
        directories=("explanation", "guides", "reference"),
        suggested_kind="explanation",
    ),
    Scope(
        name="api",
        title="Public API surface",
        description=(
            "The contract the project exposes to callers — CLI flags, "
            "HTTP endpoints, MCP tools, library functions. What is "
            "stable, what is experimental, what is deprecated."
        ),
        anchor_filenames=(
            "api.md",
            "api-reference.md",
            "endpoints.md",
        ),
        directories=("reference",),
        suggested_kind="reference",
    ),
    Scope(
        name="data-flow",
        title="Data flow",
        description=(
            "Lifecycle of a record through the system: how it enters, "
            "what transforms it, where it is stored, how it is "
            "retrieved. Diagrams strongly preferred."
        ),
        anchor_filenames=(
            "data-flow.md",
            "dataflow.md",
            "pipeline.md",
            "ingest.md",
        ),
        directories=("reference", "explanation"),
        suggested_kind="explanation",
    ),
    Scope(
        name="commands",
        title="Commands & CLI",
        description=(
            "Every slash command, CLI subcommand, or invocable entry "
            "point. What each one does, when to use it, what to expect "
            "in the response. The reference a user hits when they ask "
            "'how do I do X?'"
        ),
        anchor_filenames=(
            "commands.md",
            "cli.md",
            "slash-commands.md",
        ),
        directories=("reference", "guides"),
        suggested_kind="reference",
    ),
    Scope(
        name="mcp",
        title="MCP integration",
        description=(
            "How the project exposes (or consumes) Model Context "
            "Protocol surfaces — tools, resources, prompts, the "
            "stability model. Only applies to projects that integrate "
            "with MCP; otherwise the scope page documents 'we don't "
            "use MCP.'"
        ),
        anchor_filenames=(
            "mcp.md",
            "mcp-integration.md",
            "mcp-tools.md",
        ),
        directories=("reference", "explanation"),
        suggested_kind="reference",
    ),
    Scope(
        name="tools",
        title="Tooling & dependencies",
        description=(
            "What's in the toolchain — runtime, package manager, "
            "testing framework, linters, build system, hosted services, "
            "third-party libraries the project takes hard dependencies "
            "on. Each entry with a one-line 'why this one'."
        ),
        anchor_filenames=(
            "tools.md",
            "tooling.md",
            "stack.md",
            "dependencies.md",
        ),
        directories=("reference",),
        suggested_kind="reference",
    ),
    Scope(
        name="ci-cd",
        title="CI / CD",
        description=(
            "Build, test, release pipeline. What runs on every push, "
            "what runs on merge to main, what runs on tag. Where the "
            "configuration lives, what fails block a merge."
        ),
        anchor_filenames=(
            "ci-cd.md",
            "ci.md",
            "build.md",
            "release.md",
            "deploy.md",
        ),
        directories=("reference", "runbook", "guides"),
        suggested_kind="reference",
    ),
    Scope(
        name="ai-usage",
        title="AI usage",
        description=(
            "Where AI / LLMs are used in the project — which models, "
            "which prompts, what's auto vs. human-in-the-loop, what "
            "data the models see, how cost and rate-limit are bounded. "
            "Skip with 'no AI usage' if the project doesn't use LLMs."
        ),
        anchor_filenames=(
            "ai-usage.md",
            "llm-usage.md",
            "ai-integration.md",
            "prompts.md",
        ),
        directories=("explanation", "reference"),
        suggested_kind="explanation",
    ),
    Scope(
        name="operations",
        title="Operations & runbooks",
        description=(
            "Deploy, monitor, recover. On-call procedures, health "
            "checks, common failure modes and how to respond to them."
        ),
        anchor_filenames=(
            "operations.md",
            "runbook.md",
            "monitoring.md",
        ),
        directories=("runbook", "guides"),
        suggested_kind="runbook",
    ),
    Scope(
        name="prd",
        title="Product requirements",
        description=(
            "Spec / RFC / PRD documents — what's been formally proposed "
            "and accepted as scope. Each PRD frames a problem, the "
            "goals, the non-goals, the design, and the open questions."
        ),
        anchor_filenames=(),  # source: ADR-0297
        directories=("specs", "rfc"),
        suggested_kind="rfc",
        # source: ADR-0297
        groundable=False,
    ),
    Scope(
        name="decisions",
        title="Decisions / task-records",
        description=(
            "Documented decisions and completed tasks — Entry, "
            "Mandatory elements, How, Result, Serves. The project's "
            "causal history."
        ),
        anchor_filenames=(),  # any ADR counts
        directories=("adr", "adrs"),
        suggested_kind="adr",
        # source: ADR-0297
        groundable=False,
    ),
    Scope(
        name="onboarding",
        title="Onboarding & getting started",
        description=(
            "Day-one path for a new contributor or integrator: install, "
            "configure, run the smoke test, ship the first change. "
            "The 'I just landed in this repo, what do I do' page."
        ),
        anchor_filenames=(
            "getting-started.md",
            "onboarding.md",
            "quickstart.md",
            "setup.md",
        ),
        directories=("guides", "tutorial"),
        suggested_kind="tutorial",
    ),
    # source: ADR-0297
    Scope(
        name="installation",
        title="Installation & configuration",
        description=(
            "Step-by-step install + configuration walk-through, OS by OS, "
            "with every environment variable named and its default. Beyond "
            "onboarding (which is the day-one path) this is the reference "
            "for every configuration knob, every install variant (CLI, "
            "Docker, source clone, plugin marketplace), and the post-"
            "install verification commands. Include screenshots / sample "
            "configs where useful."
        ),
        anchor_filenames=(
            "installation.md",
            "install.md",
            "configuration.md",
            "configure.md",
        ),
        directories=("guides", "how-to"),
        suggested_kind="how-to",
    ),
    Scope(
        name="troubleshooting",
        title="Troubleshooting & known issues",
        description=(
            "Symptom → diagnosis → fix table for every known issue, "
            "common error message, and pitfall. Each entry: the exact "
            "log line or symptom, root cause, recovery steps, prevention. "
            "Sourced from runbook incidents + ADR consequences + lessons "
            "captured in memory. The page a user opens when something "
            "breaks at 3am."
        ),
        anchor_filenames=(
            "troubleshooting.md",
            "known-issues.md",
            "faq.md",
            "common-errors.md",
        ),
        directories=("guides", "how-to", "runbook"),
        suggested_kind="how-to",
    ),
    Scope(
        name="contributing",
        title="Contributing guide",
        description=(
            "How to land a change in this project: fork / branch policy, "
            "test commands, lint rules, commit-message convention, PR "
            "template, code-review expectations, who reviews what, how "
            "long things typically take. Distinct from onboarding "
            "(reader is already set up); this is the path from edit to "
            "merge."
        ),
        anchor_filenames=(
            "contributing.md",
            "CONTRIBUTING.md",
            "contribute.md",
            "development.md",
        ),
        directories=("guides", "how-to"),
        suggested_kind="how-to",
    ),
    Scope(
        name="configuration",
        title="Configuration reference",
        description=(
            "Exhaustive table of every configurable knob: every "
            "environment variable, every config-file key, every CLI "
            "flag, every plugin setting. Columns: name | type | "
            "required/optional | default | valid range | effect. "
            "Distinct from the installation guide (which is task-"
            "oriented step-by-step); this is the reference for people "
            "who already know what they're doing."
        ),
        anchor_filenames=(
            "configuration.md",
            "config.md",
            "settings.md",
            "env-vars.md",
        ),
        directories=("reference", "guides"),
        suggested_kind="reference",
    ),
    Scope(
        name="security",
        title="Security model & hardening",
        description=(
            "The project's threat model + security posture. What "
            "secrets the project handles, how they're stored, what "
            "isolation guarantees exist, who can do what, the "
            "attack surface, mitigations in place, and the hardening "
            "checklist for production deployment. Sourced from "
            "security ADRs + audit findings. The page security review "
            "boards consult."
        ),
        anchor_filenames=(
            "security.md",
            "SECURITY.md",
            "threat-model.md",
            "hardening.md",
        ),
        directories=("guides", "reference"),
        suggested_kind="reference",
    ),
    Scope(
        name="performance",
        title="Performance characteristics & tuning",
        description=(
            "Measured throughput / latency / resource consumption "
            "characteristics, with the benchmarks that produced them. "
            "Tuning knobs and when to turn each one. Capacity planning "
            "advice. Profiling instructions. Failure modes under load. "
            "Distinct from operations (which covers runbook recovery) — "
            "this covers expected steady-state behaviour and how to "
            "shape it."
        ),
        anchor_filenames=(
            "performance.md",
            "benchmarks.md",
            "tuning.md",
            "scaling.md",
        ),
        directories=("guides", "reference"),
        suggested_kind="reference",
    ),
    Scope(
        name="migration-guides",
        title="Migration & upgrade guides",
        description=(
            "Version-to-version upgrade paths. Every breaking change "
            "between releases should have a guide: what changed, why, "
            "what the user's existing code must do to keep working, "
            "and the deprecation timeline for the old behaviour. Plus "
            "migration FROM competing tools (if applicable). Write "
            '"Not applicable — no breaking changes yet" for fresh '
            "projects rather than omitting the heading."
        ),
        anchor_filenames=(
            "migration.md",
            "migrations.md",
            "upgrade.md",
            "upgrading.md",
            "breaking-changes.md",
        ),
        directories=("guides", "how-to", "reference"),
        suggested_kind="how-to",
    ),
    Scope(
        name="debugging",
        title="Debugging guide",
        description=(
            "How to figure out what's happening at runtime: where logs "
            "go, log-level controls, the verbose / debug flags, the "
            "diagnostic commands, how to read a stack trace from this "
            "project's code, how to attach a debugger, the trace IDs "
            "/ correlation IDs and how to follow them. Distinct from "
            "troubleshooting (which is symptom → fix table) — this is "
            "the methodology of investigation."
        ),
        anchor_filenames=(
            "debugging.md",
            "diagnostics.md",
            "logging.md",
            "observability.md",
        ),
        directories=("guides", "how-to"),
        suggested_kind="how-to",
    ),
    Scope(
        name="testing",
        title="Testing guide",
        description=(
            "How to write and run tests for this project: the test "
            "layout (unit / integration / e2e), conventions for "
            "fixtures + mocks + factories, coverage targets per layer, "
            "the test commands, how to debug a flaky test, how to add "
            "a new test category. Distinct from CI/CD (which covers "
            "the pipeline that runs tests) — this is the developer's "
            "test-authoring workflow."
        ),
        anchor_filenames=(
            "testing.md",
            "tests.md",
            "test-strategy.md",
            "writing-tests.md",
        ),
        directories=("guides", "how-to"),
        suggested_kind="how-to",
    ),
    Scope(
        name="plugins-extensions",
        title="Plugins & extensions",
        description=(
            "The project's extension API: what surfaces can be "
            "extended, the lifecycle of an extension, the manifest / "
            "hook shape, the testing strategy for an extension. Write "
            '"Not applicable — this project does not expose an '
            'extension API" for monolithic projects rather than '
            "omitting the heading."
        ),
        anchor_filenames=(
            "plugins.md",
            "extensions.md",
            "plugin-api.md",
            "addons.md",
            "extending.md",
        ),
        directories=("reference", "guides", "explanation"),
        suggested_kind="reference",
    ),
    Scope(
        name="recipes",
        title="Recipes & cookbook",
        description=(
            'Common task walkthroughs — "how do I X?" answered with '
            "the exact commands and code. 8–20 short worked examples "
            "ordered from beginner to advanced, each one self-"
            "contained with copy-pasteable steps + expected output. "
            "The page users land on when they ask the project a "
            "concrete question."
        ),
        anchor_filenames=(
            "recipes.md",
            "cookbook.md",
            "examples.md",
            "patterns.md",
        ),
        directories=("guides", "how-to"),
        suggested_kind="how-to",
    ),
    Scope(
        name="glossary",
        title="Glossary",
        description=(
            "Project-specific terms with a one-paragraph definition. "
            "Domain abbreviations, internal aliases, every term the "
            "reader might hit in another page without context should "
            "resolve here. Sorted alphabetically. Include 'what it is "
            "NOT' notes for common confusions."
        ),
        anchor_filenames=(
            "glossary.md",
            "terms.md",
            "terminology.md",
            "definitions.md",
        ),
        directories=("reference", "guides"),
        suggested_kind="reference",
    ),
    # ── Diátaxis how-to / tutorial axis ────────────────────────────────
    Scope(
        name="how-to-guides",
        title="How-to guides",
        description=(
            "Task-oriented guides answering 'how do I X?' for the "
            "most common operations the project supports. Distinct "
            "from tutorials (which teach concepts) and reference "
            "(which catalogues fields): a how-to is a recipe that "
            "gets a user from a stated starting point to a stated "
            "outcome with the minimum number of steps. Anchor page "
            "is an index of the available how-tos; each individual "
            "recipe is a sibling page."
        ),
        anchor_filenames=(
            "how-to.md",
            "how-to-guides.md",
            "guides.md",
            "howto.md",
        ),
        directories=("guides", "how-to"),
        suggested_kind="how-to",
    ),
    Scope(
        name="tutorials",
        title="Tutorials & learning paths",
        description=(
            "Step-by-step learning sequences that take a beginner "
            "from zero to a working understanding of one concept. "
            "Distinct from onboarding (one-shot day-1 setup) and "
            "from how-to guides (which assume the reader knows what "
            "they're doing). A tutorial introduces concepts in "
            "order, with expected outputs at every step, ending "
            "with a working example the reader has built themselves."
        ),
        anchor_filenames=(
            "tutorials.md",
            "tutorial.md",
            "learn.md",
            "lessons.md",
        ),
        directories=("tutorial", "tutorials", "guides"),
        suggested_kind="tutorial",
    ),
    Scope(
        name="integration-guides",
        title="Integration guides",
        description=(
            "How to wire this project into external systems: the "
            "IDEs, CI providers, model APIs, databases, MCP "
            "clients, browser extensions, or downstream services "
            "that consume its output. Each integration entry gives "
            "the contract (what the external system must do), the "
            "wiring steps, and the smoke test that proves the "
            "integration works."
        ),
        anchor_filenames=(
            "integrations.md",
            "integration.md",
            "integration-guides.md",
        ),
        directories=("guides", "how-to", "reference"),
        suggested_kind="how-to",
    ),
    Scope(
        name="examples",
        title="Examples & sample code",
        description=(
            "End-to-end working examples in the form a reader can "
            "copy and run: a sample app, a demo workflow, a "
            "starter template. Distinct from recipes (which are "
            "snippets) — examples are complete buildable units "
            "that show several pieces working together."
        ),
        anchor_filenames=(
            "examples.md",
            "demos.md",
            "sample-apps.md",
        ),
        directories=("guides", "tutorial", "reference"),
        suggested_kind="tutorial",
    ),
    # ── Setup + local-dev ──────────────────────────────────────────────
    Scope(
        name="local-development",
        title="Local development",
        description=(
            "How a contributor sets the project up on their own "
            "machine: clone, install deps, run the dev server, run "
            "the watcher, swap in stub services. Includes the fast "
            "feedback loops (hot reload, incremental test runs) and "
            "the mocks / fixtures that make local work possible "
            "without production credentials."
        ),
        anchor_filenames=(
            "local-development.md",
            "dev-setup.md",
            "developing.md",
            "development.md",
        ),
        directories=("guides", "how-to"),
        suggested_kind="how-to",
    ),
    # ── Operational telemetry ──────────────────────────────────────────
    Scope(
        name="logging",
        title="Logging guide",
        description=(
            "Log format the project emits, log levels and what "
            "each one is for, where logs go (stdout / file / "
            "remote sink), how to filter, how to rotate, how to "
            "plumb structured fields. Names the libraries used and "
            "the conventions for adding new log sites."
        ),
        anchor_filenames=(
            "logging.md",
            "logs.md",
            "log-format.md",
        ),
        directories=("guides", "reference", "how-to"),
        suggested_kind="reference",
    ),
    Scope(
        name="observability",
        title="Observability",
        description=(
            "Metrics emitted, traces instrumented, dashboards "
            "available, alerts wired. The runbook a reader checks "
            "BEFORE production goes wrong: 'how do I see what this "
            "is doing?' Names the OpenTelemetry surface, "
            "Prometheus / Grafana boards, log queries to copy-paste."
        ),
        anchor_filenames=(
            "observability.md",
            "metrics.md",
            "telemetry.md",
            "tracing.md",
        ),
        directories=("guides", "reference", "runbook"),
        suggested_kind="reference",
    ),
    # ── Security ───────────────────────────────────────────────────────
    Scope(
        name="secrets-management",
        title="Secrets management",
        description=(
            "Where API keys, tokens, certificates, and other "
            "secrets live during local dev, in CI, and in "
            "production. Rotation procedure, scope of each "
            "credential, what happens when one leaks. Distinct "
            "from access-control because this is about the "
            "credentials themselves, not who can use them."
        ),
        anchor_filenames=(
            "secrets.md",
            "secrets-management.md",
            "credentials.md",
        ),
        directories=("guides", "how-to", "reference"),
        suggested_kind="how-to",
    ),
    Scope(
        name="access-control",
        title="Access control & permissions",
        description=(
            "Who can do what: roles, scopes, capabilities, the "
            "matrix of actions × principal. Includes the model "
            "(RBAC / ABAC / ACL / capability) and the enforcement "
            "points (middleware, policy engine). For projects "
            "without external users, documents the internal trust "
            "model."
        ),
        anchor_filenames=(
            "access-control.md",
            "permissions.md",
            "authorization.md",
            "rbac.md",
        ),
        directories=("reference", "guides"),
        suggested_kind="reference",
    ),
    # ── Contribution + governance ──────────────────────────────────────
    Scope(
        name="coding-standards",
        title="Coding standards & conventions",
        description=(
            "The mechanical rules every contribution honours: "
            "file-size limits, layer boundaries, naming, lint "
            "config, type-system discipline, source-citation "
            "requirements. Cite the lint / format / typecheck "
            "tools that enforce each rule."
        ),
        anchor_filenames=(
            "coding-standards.md",
            "style-guide.md",
            "conventions.md",
            "code-style.md",
        ),
        directories=("reference", "guides"),
        suggested_kind="reference",
    ),
    Scope(
        name="release-process",
        title="Release process",
        description=(
            "How a version ships: branch / tag / build pipeline, "
            "versioning scheme (semver / calver / commit-hash), "
            "changelog format, sign-off requirements, rollback "
            "procedure. Distinct from ci-cd which describes the "
            "pipeline; this describes how a human cuts a release."
        ),
        anchor_filenames=(
            "releasing.md",
            "release-process.md",
            "release.md",
            "publishing.md",
        ),
        directories=("guides", "how-to", "runbook"),
        suggested_kind="how-to",
    ),
    Scope(
        name="changelog",
        title="Changelog",
        description=(
            "User-facing record of what changed between versions. "
            "Each release entry calls out new features, breaking "
            "changes, deprecations, security fixes, and the "
            "migration guide that pairs with a breaking change. "
            "Format follows Keep a Changelog by default; project "
            "may override."
        ),
        anchor_filenames=(
            "CHANGELOG.md",
            "changelog.md",
            "history.md",
            "releases.md",
        ),
        directories=("reference",),
        suggested_kind="reference",
        # source: ADR-0297
        groundable=False,
    ),
    Scope(
        name="roadmap",
        title="Roadmap",
        description=(
            "What's planned, what's in progress, what's deferred "
            "and why. Not a release schedule (use release-process "
            "for cadence) — this is the strategic surface a reader "
            "checks before betting on the project. Honest about "
            "what isn't going to happen."
        ),
        anchor_filenames=(
            "roadmap.md",
            "ROADMAP.md",
            "future-work.md",
            "planned.md",
        ),
        directories=("explanation", "reference", "guides"),
        suggested_kind="explanation",
        # source: ADR-0297
        groundable=False,
    ),
    # source: ADR-0297
    Scope(
        name="accessibility",
        title="Accessibility",
        description=(
            "Accessibility standards the project follows (WCAG "
            "level, screen-reader support, keyboard navigation, "
            "colour contrast audit). For non-UI projects, write "
            "'Not applicable — this project has no user interface; "
            "downstream consumers are responsible for their own "
            "a11y' rather than omitting."
        ),
        anchor_filenames=(
            "accessibility.md",
            "a11y.md",
        ),
        directories=("reference", "explanation"),
        suggested_kind="reference",
        # source: ADR-0297
        groundable=False,
    ),
    Scope(
        name="localization",
        title="Localization & i18n",
        description=(
            "How the project handles translation, locale data, "
            "currency / date formatting, right-to-left layout. "
            "Names the i18n library, the source-of-truth strings "
            "file, the translator workflow. 'Not applicable — "
            "single-locale project' is a valid answer; write it "
            "explicitly."
        ),
        anchor_filenames=(
            "localization.md",
            "i18n.md",
            "translations.md",
        ),
        directories=("reference", "guides"),
        suggested_kind="reference",
        # source: ADR-0297
        groundable=False,
    ),
)


@dataclass
class ScopeCoverage:
    """Whether a single scope is covered for a domain, and how."""

    scope: Scope
    domain: str
    covered: bool
    page_count: int  # substantive pages found in this scope's directories
    anchor_page: str | None  # wiki-relative path of the page that anchors coverage
    suggested_path: str  # path to author if uncovered


@dataclass
class DomainCoverage:
    """Roll-up of all scopes for one domain.

    source: ADR-0297"""

    domain: str
    scopes: list[ScopeCoverage] = field(default_factory=list)


def domain_coverage_covered_count(coverage: "DomainCoverage") -> int:
    return sum(1 for s in coverage.scopes if s.covered)


def domain_coverage_missing_count(coverage: "DomainCoverage") -> int:
    return sum(1 for s in coverage.scopes if not s.covered)


def domain_coverage_coverage_ratio(coverage: "DomainCoverage") -> float:
    total = len(coverage.scopes)
    return domain_coverage_covered_count(coverage) / total if total else 0.0


def domain_coverage_missing_scopes(coverage: "DomainCoverage") -> list[ScopeCoverage]:
    return [s for s in coverage.scopes if not s.covered]


# ── Filesystem scan ─────────────────────────────────────────────────────


def _has_substantive_anchor(
    wiki_root: str,
    directories: tuple[str, ...],
    domain: str,
    anchor_filenames: tuple[str, ...],
    max_age_days: float | None = None,
) -> str | None:
    """Return the wiki-relative path of the first substantive anchor page,
    or None if no anchor exists.

    source: ADR-0297"""
    if _stat_page is None:
        raise _unconfigured("stat_page")

    for directory in directories:
        for filename in anchor_filenames:
            rel = f"{directory}/{domain}/{filename}"
            stat = _stat_page(wiki_root, rel)
            if stat is None:
                continue
            size, mtime = stat
            if size < _MIN_PAGE_BYTES:
                continue
            if max_age_days is not None:
                age_days = (time.time() - mtime) / 86400.0
                if age_days > max_age_days:
                    continue
            return rel
    return None


def _count_substantive_pages(
    wiki_root: str,
    directories: tuple[str, ...],
    domain: str,
) -> int:
    """Count substantive ``.md`` pages under ``<wiki>/<dir>/<domain>/`` for
    each directory in ``directories``.

    Used to detect scopes that are "covered by accumulation" — many ADRs
    cover the ``decisions`` scope even without an anchor file.
    """
    if _markdown_file_sizes is None:
        raise _unconfigured("markdown_file_sizes")
    count = 0
    for directory in directories:
        dom_path = f"{wiki_root}/{directory}/{domain}"
        sizes = _markdown_file_sizes(dom_path)
        count += sum(1 for size in sizes.values() if size >= _MIN_PAGE_BYTES)
    return count


def _suggested_path_for(scope: Scope, domain: str) -> str:
    """Where the LLM should write the missing scope's anchor page."""
    primary_dir = scope.directories[0] if scope.directories else "reference"
    if scope.anchor_filenames:
        filename = scope.anchor_filenames[0]
    else:
        filename = f"{scope.name}.md"
    return f"{primary_dir}/{domain}/{filename}"


_COVERAGE_THRESHOLDS: Final[dict[str, int]] = {
    # decisions scope is covered when any substantive ADR exists.
    "decisions": 1,
}


def audit_domain(
    wiki_root: str,
    domain: str,
    *,
    max_age_days: float | None = _DEFAULT_MAX_AGE_DAYS,
) -> DomainCoverage:
    """Compute coverage for one domain across all canonical scopes.

    Returns a ``DomainCoverage`` whose ``scopes`` list mirrors ``SCOPES``
    order, with ``covered=True`` for scopes that meet the coverage bar.

    source: ADR-0297

    Pass ``max_age_days=None`` to disable freshness checks — the older
    "any anchor counts" semantics.
    """
    out = DomainCoverage(domain=domain)
    for scope in SCOPES:
        anchor = _has_substantive_anchor(
            wiki_root,
            scope.directories,
            domain,
            scope.anchor_filenames,
            max_age_days=max_age_days,
        )
        page_count = _count_substantive_pages(wiki_root, scope.directories, domain)
        threshold = _COVERAGE_THRESHOLDS.get(scope.name, 1)
        covered = anchor is not None or (
            not scope.anchor_filenames and page_count >= threshold
        )
        out.scopes.append(
            ScopeCoverage(
                scope=scope,
                domain=domain,
                covered=covered,
                page_count=page_count,
                anchor_page=anchor,
                suggested_path=_suggested_path_for(scope, domain),
            )
        )
    return out


_DOMAIN_REJECT_RE = (
    # source: ADR-0297
    "year",
)


# source: ADR-0297

_YEAR_SLUG_DIGITS = 4

# source: ADR-0297


_MIN_KIND_DIRS_FOR_DOMAIN = 2


def _is_plausible_domain(name: str) -> bool:
    """Filter for ``list_domains`` — accept project names, reject buckets.

    source: ADR-0297"""
    if not name or name.startswith((".", "_")):
        return False
    if name.isdigit() and len(name) == _YEAR_SLUG_DIGITS:  # bare year
        return False
    return True


_KNOWN_KINDS: Final[frozenset[str]] = frozenset(
    {
        "reference",
        "explanation",
        "adr",
        "adrs",
        "runbook",
        "specs",
        "notes",
        "guides",
        "conventions",
        "lessons",
        "rfc",
        "how-to",
        "tutorial",
        "files",
        "architecture",
    }
)


def list_domains(wiki_root: str) -> list[str]:
    """Discover domains by scanning ``<wiki>/<kind>/<domain>/`` subdirs.

    A directory is considered a domain when at least two known wiki
    kinds contain it as a subdirectory. Reserved buckets (``_general``,
    bare years) are filtered.
    """
    if _domain_kind_membership is None:
        raise _unconfigured("domain_kind_membership")
    memberships = _domain_kind_membership(wiki_root, _KNOWN_KINDS)
    return sorted(
        entry
        for entry, kinds in memberships.items()
        if _is_plausible_domain(entry) and len(kinds) >= _MIN_KIND_DIRS_FOR_DOMAIN
    )


def audit_all_domains(
    wiki_root: str,
    *,
    max_age_days: float | None = _DEFAULT_MAX_AGE_DAYS,
) -> list[DomainCoverage]:
    """Audit every discovered domain.

    source: ADR-0297
    """
    rolls = [
        audit_domain(wiki_root, d, max_age_days=max_age_days)
        for d in list_domains(wiki_root)
    ]
    rolls.sort(key=domain_coverage_missing_count, reverse=True)
    return rolls


# source: ADR-0297


# File extensions Cortex treats as source. Documentation files (.md),
# generated artifacts, lock files, and binaries are filtered out at
# scan time, not by extension — but extensions narrow the set first.
_SOURCE_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".go",
        ".rs",
        ".rb",
        ".java",
        ".kt",
        ".swift",
        ".cpp",
        ".cc",
        ".c",
        ".h",
        ".hpp",
        ".cs",
        ".sql",
    }
)

# Directories never worth scanning — vendored deps, build artifacts,
# generated caches, IDE state. Shared with
# mcp_server/infrastructure/wiki_drift_fs.py (issue #560; infrastructure
# may not import core, so this pure data lives in shared/).
_SKIP_DIRECTORIES: Final[frozenset[str]] = SKIP_DIRECTORIES


def _project_source_root(domain: str) -> str | None:
    """Resolve a domain name to its filesystem source root.

    Returns ``None`` when the domain isn't tied to a git repo (e.g.
    the ``_general`` catch-all bucket, or a domain that exists only as
    a memory tag without a checked-out tree).
    """
    try:
        from mcp_server.shared.domain_mapping import _build_registry  # noqa: PLC0415 — source: ADR-0297
    except ImportError:
        return None
    registry = _build_registry()
    for repo in registry.repos:
        if repo.canonical == domain:
            return repo.fs_path
    return None


def list_source_files(root: str) -> list[str]:
    """Walk ``root`` and return wiki-relative paths of source files.

    Returns paths *relative to ``root``* — that's what the wiki page
    bodies typically cite (e.g. ``mcp_server/core/predictive_coding.py``).
    Filters out vendored deps, build artefacts, and non-source
    extensions. Returns an empty list when ``root`` doesn't exist.
    """
    if _walk_source_files is None:
        raise _unconfigured("walk_source_files")
    return _walk_source_files(root, _SKIP_DIRECTORIES, _SOURCE_EXTENSIONS)


def _index_wiki_file_references(
    wiki_root: str, domain: str
) -> tuple[set[str], set[str]]:
    """Index file paths and basenames mentioned anywhere in the wiki.

    Returns ``(rel_paths_referenced, basenames_referenced)`` where:

      * ``rel_paths_referenced`` — full relative paths cited verbatim
        (``mcp_server/core/predictive_coding.py``). High-precision match.
      * ``basenames_referenced`` — bare filenames cited (``predictive_coding.py``).
        Lower-precision but catches pages that name a file without its
        full directory prefix.

    source: ADR-0297"""
    if _walk_markdown_contents is None:
        raise _unconfigured("walk_markdown_contents")
    paths: set[str] = set()
    basenames: set[str] = set()
    _ = domain  # reserved for future scoping

    # File-path-shaped tokens: at least one slash, has a source extension,
    # ends at whitespace or punctuation.
    path_re = re.compile(
        r"[\w./\-]+\.(?:py|ts|tsx|js|jsx|go|rs|rb|java|kt|swift|cpp|cc|c|h|hpp|cs|sql)\b"
    )

    for text in _walk_markdown_contents(wiki_root):
        for m in path_re.finditer(text):
            token = m.group(0).lstrip("./").strip()
            if "/" in token:
                paths.add(token)
            basenames.add(token.rsplit("/", 1)[-1])
    return paths, basenames


@dataclass
class FileCoverage:
    """File-level coverage roll-up for one domain.

    source: ADR-0297"""

    domain: str
    source_root: str | None
    source_file_count: int
    covered_file_count: int  # matched by path or basename
    uncovered_files: list[str] = field(default_factory=list)


def file_coverage_coverage_ratio(coverage: "FileCoverage") -> float:
    if not coverage.source_file_count:
        return 1.0
    return coverage.covered_file_count / coverage.source_file_count


def audit_files(wiki_root: str, domain: str) -> FileCoverage:
    """Compute file-level coverage for one domain.

    source: ADR-0297"""
    src_root = _project_source_root(domain)
    if src_root is None:
        return FileCoverage(
            domain=domain,
            source_root=None,
            source_file_count=0,
            covered_file_count=0,
        )

    files = list_source_files(src_root)
    if not files:
        return FileCoverage(
            domain=domain,
            source_root=src_root,
            source_file_count=0,
            covered_file_count=0,
        )

    paths_ref, basenames_ref = _index_wiki_file_references(wiki_root, domain)
    uncovered: list[str] = []
    covered = 0
    for rel in files:
        bn = rel.rsplit("/", 1)[-1]
        if rel in paths_ref or bn in basenames_ref:
            covered += 1
        else:
            uncovered.append(rel)

    return FileCoverage(
        domain=domain,
        source_root=src_root,
        source_file_count=len(files),
        covered_file_count=covered,
        uncovered_files=uncovered[:50],
    )


def audit_all_file_coverage(wiki_root: str) -> list[FileCoverage]:
    """Audit file-level coverage for every discovered domain that has a
    resolvable source root. Sorted by uncovered count desc.
    """
    out: list[FileCoverage] = []
    for domain in list_domains(wiki_root):
        roll = audit_files(wiki_root, domain)
        if roll.source_root is not None:
            out.append(roll)
    out.sort(key=lambda r: r.source_file_count - r.covered_file_count, reverse=True)
    return out
