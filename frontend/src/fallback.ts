import type { QueueItem, Session, Skill, Target } from "./api";

export let usingFallback = false;

const skills: Skill[] = [
  { id: "npe-root-cause-tracer", name: "NPE root cause tracer", description: "Walk locals backward from a null dereference.", domain: "Core JVM", triggerPatterns: ["NullPointerException"], systemInstructions: "Slice locals on the application frame.", customCommands: ["locals", "where"] },
  { id: "spring-boot-tx-debugger", name: "Spring transaction debugger", description: "Inspect the transaction proxy.", domain: "Spring Boot", triggerPatterns: ["UnexpectedRollbackException"], systemInstructions: "Check @Transactional self-invocation.", customCommands: ["print this"] },
  { id: "jvm-deadlock-thread-analyzer", name: "Deadlock analyzer", description: "Read monitor owners.", domain: "Core JVM", triggerPatterns: ["deadlock"], systemInstructions: "Dump threads and lock owners.", customCommands: ["threads"] },
  { id: "kafka-consumer-deserialization", name: "Kafka deserialization", description: "Inspect the record payload.", domain: "Kafka / Messaging", triggerPatterns: ["SerializationException"], systemInstructions: "Print offset and raw bytes.", customCommands: ["locals"] },
];

const targets: Target[] = [
  { id: "order-orchestrator", name: "order-orchestrator", domain: "Spring Boot", startupScript: "/opt/ecs/bin/setenv.sh", packagePrefix: "com.ecs.oms", jdwpPort: 5005, host: "127.0.0.1", skills: ["npe-root-cause-tracer"] },
  { id: "offer-promotion", name: "offer-promotion", domain: "Kafka / Messaging", startupScript: "/opt/ecs/bin/start.sh", packagePrefix: "com.ecs.mec.offer", jdwpPort: 5006, host: "127.0.0.1", skills: ["kafka-consumer-deserialization"] },
  { id: "customer-360", name: "customer-360", domain: "Jakarta EE", startupScript: "/etc/systemd/system/customer-360.service", packagePrefix: "com.ecs.crm", jdwpPort: 5007, host: "127.0.0.1", skills: [] },
];

const sessions: Session[] = [
  {
    id: "npe-214",
    targetId: "order-orchestrator",
    status: "success",
    summary: "taxable is null at CheckoutSagaService.capture:214 because the quote line never set it.",
    stepper: "Root Cause Synthesized",
    stack: "java.lang.NullPointerException\n\tat com.ecs.oms.saga.CheckoutSagaService.capture(CheckoutSagaService.java:214)",
    frames: [{ className: "com.ecs.oms.saga.CheckoutSagaService", method: "capture", file: "CheckoutSagaService.java", line: 214, applicationFrame: true }],
    breakpoints: [{ className: "com.ecs.oms.saga.CheckoutSagaService", line: 214 }],
    variables: [{ threadId: "1", frame: 0, locals: [{ name: "taxable", value: "null" }, { name: "orderId", value: "8c2e-demo" }] }],
    threads: ["main RUNNABLE"],
    startupScript: "/opt/ecs/bin/setenv.sh",
    startupText: "JAVA_TOOL_OPTIONS=-agentlib:jdwp=transport=dt_socket,server=y,suspend=n,address=*:5005",
    jdwpPort: 5005,
    jdwpConnected: true,
    skills: ["npe-root-cause-tracer"],
    extraContext: "taxable is unset after ATP",
    pending: null,
    createdAt: new Date().toISOString(),
    events: [{ kind: "llm_token", at: new Date().toISOString(), token: "taxable is null at capture:214. " }],
  },
  {
    id: "offer-64",
    targetId: "offer-promotion",
    status: "attention",
    summary: "Inject JDWP on port 5006 into /opt/ecs/bin/start.sh",
    stepper: "SSH MCP Startup Check",
    stack: "org.apache.kafka.common.errors.SerializationException\n\tat com.ecs.mec.offer.OfferListener.onMessage(OfferListener.java:64)",
    frames: [{ className: "com.ecs.mec.offer.OfferListener", method: "onMessage", file: "OfferListener.java", line: 64, applicationFrame: true }],
    breakpoints: [],
    variables: [],
    threads: [],
    startupScript: "/opt/ecs/bin/start.sh",
    startupText: "",
    jdwpPort: 5006,
    jdwpConnected: false,
    skills: ["kafka-consumer-deserialization"],
    extraContext: "payload bytes look like JSON",
    pending: { kind: "Startup Script & JDWP Port Injection", summary: "Inject JDWP on port 5006 into /opt/ecs/bin/start.sh", diff: "JAVA_TOOL_OPTIONS=-agentlib:jdwp=transport=dt_socket,server=y,suspend=n,address=*:5006" },
    createdAt: new Date().toISOString(),
    events: [{ kind: "human_gate", at: new Date().toISOString(), detail: "Awaiting startup script approval" }],
  },
];

function withLatest(): Target[] {
  return targets.map((target) => ({
    ...target,
    latestSession: [...sessions].reverse().find((session) => session.targetId === target.id) || null,
  }));
}

export function fallbackGet(path: string): unknown {
  if (path === "/api/summary") {
    return {
      active: sessions.filter((item) => item.status === "agent").length,
      queue: sessions.filter((item) => item.pending).length,
      targets: targets.length,
      skills: skills.length,
      resolved: sessions.filter((item) => item.status === "success").length,
    };
  }
  if (path === "/api/targets") return withLatest();
  if (path === "/api/skills") return skills;
  if (path === "/api/queue") {
    return sessions.filter((item) => item.pending).map((item) => ({
      sessionId: item.id,
      targetId: item.targetId,
      bucket: item.pending?.kind || "Startup Script & JDWP Port Injection",
      summary: item.pending?.summary || item.summary,
      waited: item.createdAt,
      diff: item.pending?.diff,
    })) satisfies QueueItem[];
  }
  if (path.startsWith("/api/sessions/") && !path.endsWith("/stream")) {
    const id = path.split("/")[3];
    return sessions.find((item) => item.id === id) || null;
  }
  if (path.startsWith("/api/sessions")) {
    const status = new URLSearchParams(path.split("?")[1] || "").get("status");
    return sessions.filter((item) => !status || item.status === status);
  }
  return null;
}

export function fallbackWrite(path: string, method: string, body: Record<string, unknown>): unknown {
  if (path === "/api/sessions" && method === "POST") {
    const session: Session = {
      id: Math.random().toString(16).slice(2, 10),
      targetId: String(body.targetId || "order-orchestrator"),
      status: "agent",
      summary: "Agent streaming a local JDWP simulation.",
      stepper: "Breakpoint & Frame Capture",
      stack: String(body.stack || ""),
      frames: [{ className: "com.ecs.oms.saga.CheckoutSagaService", method: "capture", file: "CheckoutSagaService.java", line: 214, applicationFrame: true }],
      breakpoints: [{ className: "com.ecs.oms.saga.CheckoutSagaService", line: 214 }],
      variables: [{ locals: [{ name: "taxable", value: "null" }] }],
      threads: ["main RUNNABLE"],
      startupScript: "/opt/ecs/bin/setenv.sh",
      startupText: "JAVA_TOOL_OPTIONS=-agentlib:jdwp=transport=dt_socket,server=y,suspend=n,address=*:5005",
      jdwpPort: 5005,
      jdwpConnected: true,
      skills: (body.skillIds as string[]) || [],
      extraContext: String(body.extraContext || ""),
      pending: null,
      createdAt: new Date().toISOString(),
      events: [],
    };
    sessions.unshift(session);
    return session;
  }
  if (path.startsWith("/api/queue/") && path.endsWith("/approve")) {
    const id = path.split("/")[3];
    const session = sessions.find((item) => item.id === id);
    if (session) {
      session.pending = null;
      session.status = "info";
      session.summary = "Startup script gate approved in the local fallback.";
    }
    return { sessionId: id, approved: true };
  }
  if (path === "/api/skills" && method === "POST") {
    const skill: Skill = {
      id: String(body.id || body.name).toLowerCase().replace(/\s+/g, "-"),
      name: String(body.name),
      description: String(body.description || body.name),
      domain: String(body.domain || "Core JVM"),
      triggerPatterns: (body.triggerPatterns as string[]) || [],
      systemInstructions: String(body.systemInstructions || ""),
      customCommands: (body.customCommands as string[]) || [],
    };
    skills.push(skill);
    return skill;
  }
  if (method === "DELETE" && path.startsWith("/api/skills/")) {
    const id = path.split("/")[3];
    const index = skills.findIndex((item) => item.id === id);
    if (index >= 0) skills.splice(index, 1);
    return { deleted: true };
  }
  return { ok: true };
}

export function playFallbackStream(sessionId: string, onEvent: (event: { kind: string; token?: string; status?: string; stepper?: string; command?: string; output?: string }) => void) {
  const lines = [
    { kind: "mcp_command", command: "ssh_read_file /opt/ecs/bin/setenv.sh", output: "JAVA_TOOL_OPTIONS=-agentlib:jdwp=transport=dt_socket,server=y,suspend=n,address=*:5005" },
    { kind: "jdwp_event", command: "stop at CheckoutSagaService:214", output: "breakpoint set" },
    { kind: "llm_token", token: "taxable ", status: "agent" },
    { kind: "llm_token", token: "is null ", status: "agent" },
    { kind: "llm_token", token: "at capture:214.", status: "agent" },
    { kind: "lifecycle_step", status: "success", stepper: "Root Cause Synthesized", output: "diagnosis complete" },
  ];
  let index = 0;
  const timer = window.setInterval(() => {
    const event = lines[index];
    if (!event) {
      window.clearInterval(timer);
      return;
    }
    onEvent(event);
    const session = sessions.find((item) => item.id === sessionId);
    if (session && event.status) session.status = event.status;
    index += 1;
  }, 180);
  return () => window.clearInterval(timer);
}
