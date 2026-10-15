---
id: npe-root-cause-tracer
name: Null pointer tracer
description: Walk backward from a NullPointerException and name the null local or field.
domain: Core JVM
triggers: NullPointerException
commands: where|locals|print this
---

The first application frame is the breakpoint. Read locals at that line and state which variable is null. Quote the class, method, and line. Do not invent a field that was not captured.
