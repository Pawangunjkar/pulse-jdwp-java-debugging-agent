---
id: kafka-consumer-deserialization
name: Kafka consumer inspection
description: Inspect listener frames, record offset, and payload when deserialization fails.
domain: Kafka / Messaging
triggers: SerializationException,RecordDeserializationException,ListenerExecutionFailedException
commands: where|locals|print record
---

Capture the listener method locals. Look for topic, partition, offset, and the raw payload type. Say whether the failure is a schema mismatch or a null payload.
