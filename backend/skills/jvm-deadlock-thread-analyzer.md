---
id: jvm-deadlock-thread-analyzer
name: JVM deadlock analyzer
description: Read thread dumps and monitor ownership when the JVM stops making progress.
domain: Core JVM
triggers: deadlock,BLOCKED,waiting to lock
commands: threads|threadlocks
---

List threads that own monitors and threads blocked on them. Name the two frames in the cycle. Recommend a lock-order change instead of a restart when the cycle is in application code.
