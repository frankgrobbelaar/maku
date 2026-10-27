"""Maku's core: the library logic, with no I/O.

Each step of the pipeline is a pure function from data to data:
parse names → match titles → plan changes → check results → estimate time and space.
The core never touches files, the network or the database; the code around it
does that and passes plain values in. That keeps every rule easy to test.
See docs/architecture.md.
"""
