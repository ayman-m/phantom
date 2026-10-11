---
name: scoped-tests
description: >-
  Use after changing code, before claiming work is done — pick the narrowest
  test command that still covers the change. Avoids the timeout-and-context-
  waste of full-suite runs on a one-service change. Generic — names no
  specific service; consult the changed directory's CLAUDE.md for its scoped
  command.
paths:
  - "**/*"
---

# Scoped test runner

The article's rule: running the full suite on a one-service change wastes context and time. Pick the narrowest command that still covers the change.

## How to pick

1. **Read the changed file(s)' nearest `CLAUDE.md`.** Most well-organized repos document the scoped test command per subsystem (e.g. *"Run pytest in this directory's `tests/`"*). If the subdirectory `CLAUDE.md` names a command, use it.
2. **If the change touches a shared package** (imported by multiple services), run the FULL suite — the blast radius is too wide for scoped testing.
3. **Default**: run the smallest test surface that exercises the change, then expand only if a failure suggests a cross-cutting issue.

## Decision pattern

| What you changed | Run |
|------------------|-----|
| A single service / module's source | That service's tests + any obviously related cross-cutting tests |
| A shared library, base class, or interface | **Full suite** — anything could break |
| Configuration, docs, scripts | Targeted smoke if needed; usually nothing |
| One test file | That test file only — fast feedback before broader validation |

## Why this matters

A 10-minute full-suite run on a 1-line change burns context, blocks fast feedback, and trains you to skip tests entirely. A 30-second scoped run gives you confidence in seconds.

A full-suite run on a shared-library change catches the regression you'd otherwise discover in CI 20 minutes later.

The discipline is matching the test surface to the change blast radius — not minimizing OR maximizing test runtime as a goal in itself.

## When in doubt

Run the FULL suite. Over-testing wastes minutes; under-testing wastes hours when CI catches a regression you'd have caught locally.
