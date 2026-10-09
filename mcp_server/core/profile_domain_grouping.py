"""Group scanned conversations by the domain they belong to."""

from __future__ import annotations

from mcp_server.shared.domain_mapping import resolve_domain
from mcp_server.shared.project_ids import domain_id_from_label, project_id_to_label


def build_project_domain_map(
    profiles: dict,
    by_project: dict[str, list[dict]],
) -> dict[str, str]:
    """Map each project ID to its domain ID."""
    project_domains: dict[str, str] = {}
    for domain_id, domain in (profiles.get("domains") or {}).items():
        for proj in domain.get("projects") or []:
            project_domains[proj] = domain_id

    for proj in by_project:
        if proj in project_domains:
            continue
        canonical = resolve_domain(proj)
        if canonical and not canonical.startswith("-"):
            project_domains[proj] = canonical
            continue
        label = project_id_to_label(proj)
        project_domains[proj] = domain_id_from_label(label)

    return project_domains


def group_conversations_by_domain(
    by_project: dict[str, list[dict]],
    project_domains: dict[str, str],
    target_domain: str | None,
) -> dict[str, dict]:
    """Group conversations by domain, optionally filtering to target_domain."""
    domain_conversations: dict[str, dict] = {}
    for proj, convs in by_project.items():
        domain_id = project_domains.get(proj)
        if not domain_id:
            continue
        if target_domain and domain_id != target_domain:
            continue
        if domain_id not in domain_conversations:
            domain_conversations[domain_id] = {"conversations": [], "projects": set()}
        domain_conversations[domain_id]["conversations"].extend(convs)
        domain_conversations[domain_id]["projects"].add(proj)
    return domain_conversations
