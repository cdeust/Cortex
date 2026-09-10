# ADR-0774: scripts/pg_storage_calibration.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/pg_storage_calibration.py`; original SHA-256 `9f7384b1a3961393eb66607a6c26d28c8d13184167d36a3f28ac617d390be2b7`.

## Original comment, lines 15–15

````text
# source: green-remediation §3 requires >=30,000 rows for isolated PG work.
````

## Original comment, lines 17–17

````text
# source: same plan §3: four repetitions, discard the first.
````

## Original comment, lines 19–19

````text
# source: PostgreSQL SQL lexical syntax, default NAMEDATALEN minus terminator.
````

## Original comment, lines 21–21

````text
# source: PostgreSQL CREATE TABLE storage parameters, valid range/default.
````

## Original comment, lines 57–58

````text
# source: PostgreSQL identifiers are at most 63 bytes by default; these
    # restricted ASCII names are reserved solely for this disposable task.
````

## Original comment, lines 64–65

````text
# source: PostgreSQL CREATE TABLE: fillfactor valid range 10..100,
    # default 100. The baseline is required, no lower candidate is invented.
````

## Original comment, lines 141–144

````text
# source: pg_store_consolidation_stage.increment_replay_count; the other
    # writer follows pg_store_heat.bump_heat_raw's two-column UPDATE shape.
    # Heat endpoints 0/1 are its existing CHECK bounds, used to force a change;
    # this synthetic control does not claim to reproduce the traffic mix.
````

