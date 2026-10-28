"""SQL counterpart of recall_helpers._is_system_capture (issue #706).

Only internal SQL fragments are exposed; user values remain bound parameters.
An explicit deliberate origin overrides the legacy system source marker.
"""

# source: issue #706, ADR-0114; same provenance rule as default recall.
HOOK_CAPTURE_FILTER = """(m.capture_origin = 'deliberate' OR
    (COALESCE(m.capture_origin, '') NOT IN ('local_action', 'network')
     AND COALESCE(m.source, '') <> 'post_tool_capture'))"""
