---
name: r.mismatch
description: Fixture whose Markdown parameter name disagrees with XML.
---

# r.mismatch

A markdown/XML name-mismatch fixture.

=== "Python (grass.tools)"

    *grass.tools.Tools.r_mismatch*(**input**,
        **direction**=*None*,
        **flags**=*None*,
        **overwrite**=*None*,
        **verbose**=*None*,
        **quiet**=*None*,
        **superquiet**=*None*)

## DESCRIPTION

Fixture used to prove mismatches are persisted, not dropped.

## NOTES

The Markdown signature is authoritative for the API parameter name.
