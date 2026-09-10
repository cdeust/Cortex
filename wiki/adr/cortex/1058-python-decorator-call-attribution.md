# ADR-1058: Attribute explicit decorator calls to the decorated definition

Status: accepted implementation decision for issue #372.

## Decision

Use option 1 from [issue #372](https://github.com/cdeust/Cortex/issues/372):
`extract_calls_per_function` attributes explicit Python decorator call expressions
to the decorated definition. Functions use their existing name, methods retain
`Class.method`, and class decorators use the class name emitted by Python
definition extraction. Nested classes retain the existing immediate-class naming
convention, rather than acquiring an accumulated outer-class prefix.

Decorator callees precede body callees in source order and are deduplicated with
them using the existing basename convention: `@app.route(...)` contributes
`route`. Nested call expressions in decorator arguments are included. Bare
`@property` and `@register` contain no explicit call expression and add no edge;
we do not synthesize the implicit decorator application. A decorated class adds
only its decorator calls to its own entry; its methods keep their separate
entries, and ordinary class-body calls remain outside this change.

The explicit `decorated_definition` dispatch arm transports the decorator calls
to the wrapped definition. It is not interchangeable with generic traversal.
Definition extraction's corresponding arm remains unchanged.

## Meaning and tradeoff

These are static lexical call associations, not a runtime trace. Python evaluates
decorator expressions when a definition executes and later applies their results
to the function or class. A function's call list therefore mixes definition-time
and body references. Its existing body scan already includes nested-function and
lambda calls regardless of whether they execute. Calls in a nested decorated
function remain visible to its enclosing body's lexical scan as before, and now
also become visible on the nested definition's own entry.

A module pseudo-name would require a new source-symbol contract. A separate
DECORATES relation would better distinguish execution phases but requires new
producer, storage and display support. Neither is necessary to repair the
missing registration references in the existing CALLS graph. No relation name,
edge shape, backend schema, score, threshold or runtime execution is changed.
Defaults, superclass expressions and bare decorators retain their previous
call-extraction behavior. Repeated definitions still share a name key rather
than a lexical binding identity: a later undecorated class does not erase an
earlier same-name class registration entry. Runtime rebinding remains outside
this static extractor; no new binding-state machinery is introduced. The output list order is deterministic source order,
not Python's nested decorator application order.

## Evidence and verification

- [Python function definitions](https://docs.python.org/3/reference/compound_stmts.html#function-definitions)
  specifies decorator-expression evaluation when a function is defined and
  nested application to the function object.
- [Python class definitions](https://docs.python.org/3/reference/compound_stmts.html#class-definitions)
  specifies class decorator evaluation and application.
- The repository's existing `_callee_basename`, `_collect_call_basenames`, and
  Python definition extractor are the naming and lexical-coverage contracts.
- Focused tests cover bare, called, stacked, argument-call, async, method, class,
  nested-class, duplicate-callee, default-expression and scope-isolation cases.
  A real parser-to-resolver test verifies qualified registration edges.

## Downstream assessment

`ast_parser.parse_file_ast` populates `FileAnalysis.calls_per_function`.
`core/codebase_graph.build_resolved_call_edges` accepts both function and class
caller names and resolves known callee basenames without a new relation or
storage schema. The integration test exercises this real parser-to-resolver
path. Existing local consumers must reparse to obtain the added associations.

A repository-wide caller audit found no production invocation of
`build_resolved_call_edges`. `handlers/codebase_analyze` calls `parse_file_ast`
but persists definitions, imports and inheritance, not this call map.
`handlers/ingest_codebase` obtains an external AP graph through
`ingest_codebase_graph.ensure_graph` and reads `ingest_codebase_cypher.iter_call_edges`;
it does not consume Cortex's local extractor. Its stored call edges therefore
do not change from this fix alone. Wiki reference-page summaries also originate
upstream. This change does not claim to repair or refresh those AP-fed graphs.

Validation results and the measured before/after edge fixture are recorded in
`docs/program/issue-372-decorator-calls.md`.
