# ADR-0480: mcp_server/hooks/_telemetry.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/hooks/_telemetry.py`; original SHA-256 `aca8d202e92966636f10b65c0911a72e2e7441d4cb2b213de156a5387ff51ef2`.

## Original comment, lines 36–36

````text
# source: UTF-8 encoding of the text accepted by TextIO.write.
````

## Original comment, lines 88–89

````text
# TextIOWrapper may defer encoding until flush; count that output
            # before restoring the original binary write method.
````

## Original comment, lines 117–117

````text
# source: Python sys.exit: None and zero signal successful exit.
````

## Original comment, lines 123–123

````text
# source: SI conversion, one second equals 1000 milliseconds.
````

