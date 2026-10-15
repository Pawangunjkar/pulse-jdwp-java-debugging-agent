import { fallbackGet, fallbackWrite, usingFallback as fallbackFlag } from "./fallback";

export type Target = {
  id: string;
  name: string;
  domain: string;
  startupScript: string;
  packagePrefix: string;
  jdwpPort: number;
  host: string;
  skills: string[];
  latestSession?: Session | null;
};

export type Session = {
  id: string;
  targetId: string;
  status: string;
  summary: string;
  stepper?: string;
  stack?: string;
  frames: { className: string; method: string; file: string; line: number; applicationFrame: boolean }[];
  breakpoints: { className: string; line: number; output?: string }[];
  variables: { threadId?: string; frame?: number; locals?: { name: string; value: string }[]; text?: string }[];
  threads: string[];
  startupScript?: string;
  startupText?: string;
  jdwpPort?: number | null;
  jdwpConnected?: boolean;
  skills: string[];
  extraContext?: string;
  pending?: { kind: string; summary: string; diff?: string } | null;
  createdAt?: string;
  events: { kind: string; at: string; token?: string; command?: string; output?: string; detail?: unknown; status?: string; stepper?: string; event?: string }[];
};

export type Skill = {
  id: string;
  name: string;
  description: string;
  domain: string;
  triggerPatterns: string[];
  systemInstructions: string;
  customCommands: string[];
};

export type QueueItem = {
  sessionId: string;
  targetId: string;
  bucket: string;
  summary: string;
  waited?: string;
  diff?: string;
};

const STATUS_LABEL: Record<string, string> = {
  neutral: "Detached",
  info: "Inspecting JDWP",
  attention: "Awaiting Gate",
  success: "Root Cause Found",
  danger: "Fault / Unreachable",
  agent: "Agent Streaming",
};

export function statusLabel(status: string) {
  return STATUS_LABEL[status] || status;
}

export function offline() {
  return fallbackFlag;
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  if (fallbackFlag) {
    const body = init?.body ? JSON.parse(String(init.body)) : {};
    const value = init?.method && init.method !== "GET" ? fallbackWrite(path, init.method, body) : fallbackGet(path);
    if (value == null) throw new Error("Missing in local fallback");
    return value as T;
  }
  try {
    const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
    if (!response.ok) throw new Error(await response.text());
    return response.json();
  } catch (error) {
    const mod = await import("./fallback");
    if (!mod.usingFallback) {
      mod.usingFallback = true;
      window.dispatchEvent(new Event("pulse-fallback"));
    }
    const body = init?.body ? JSON.parse(String(init.body)) : {};
    const value = init?.method && init.method !== "GET" ? fallbackWrite(path, init.method || "POST", body) : fallbackGet(path);
    if (value == null) throw error;
    return value as T;
  }
}

export const api = {
  summary: () => json<Record<string, number>>("/api/summary"),
  targets: () => json<Target[]>("/api/targets"),
  sessions: (status = "") => json<Session[]>(`/api/sessions${status ? `?status=${status}` : ""}`),
  session: (id: string) => json<Session>(`/api/sessions/${id}`),
  skills: () => json<Skill[]>("/api/skills"),
  queue: () => json<QueueItem[]>("/api/queue"),
  createSession: (body: unknown) => json<Session>("/api/sessions", { method: "POST", body: JSON.stringify(body) }),
  createTarget: (body: unknown) => json<Target>("/api/targets", { method: "POST", body: JSON.stringify(body) }),
  saveSkill: (body: unknown) => json<Skill>("/api/skills", { method: "POST", body: JSON.stringify(body) }),
  deleteSkill: (id: string) => json<{ deleted: boolean }>(`/api/skills/${id}`, { method: "DELETE" }),
  approve: (id: string, approved: boolean) =>
    json(`/api/queue/${id}/approve`, { method: "POST", body: JSON.stringify({ approved }) }),
};
