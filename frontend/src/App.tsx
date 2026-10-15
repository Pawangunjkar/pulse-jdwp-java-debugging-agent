import { FormEvent, useEffect, useMemo, useState } from "react";
import { NavLink, Route, Routes, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, offline, Session, Skill, statusLabel, Target, QueueItem } from "./api";
import { playFallbackStream } from "./fallback";

type Toast = { id: number; text: string };

const NAV = [
  ["/", "Dashboard", "M2 12h4l2-5 3 10 2-5h5"],
  ["/catalog", "Catalog", "M4 6h14M4 11h14M4 16h14"],
  ["/sessions", "Debug Sessions", "M4 5h16v12H4zM7 9h6M7 12h10"],
  ["/queue", "Human Queue", "M12 3l8 4v5c0 4-3 7-8 9-5-2-8-5-8-9V7z"],
  ["/settings", "Settings & Skills", "M4 8h14M4 14h10"],
] as const;

function Mark() {
  return (
    <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true">
      <path d="M11 2 19 7v8l-8 5-8-5V7z" fill="none" stroke="#f9b848" strokeWidth="1.4" />
      <path d="M3 13c2-3 4-1 6-3s3-2 4 0 3 2 6-1" fill="none" stroke="#c9317f" strokeWidth="1.4" />
    </svg>
  );
}

function Badge({ status }: { status: string }) {
  const color = `var(--${["neutral", "info", "attention", "success", "danger", "agent"].includes(status) ? status : "neutral"})`;
  return (
    <span className="badge" style={{ color, borderColor: color, background: `color-mix(in srgb, ${color} 14%, transparent)` }}>
      <i className={`dot ${status === "agent" || status === "info" ? "pulse" : ""}`} />
      {statusLabel(status)}
    </span>
  );
}

export function App() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [palette, setPalette] = useState(false);
  const [panel, setPanel] = useState(false);
  const [queueCount, setQueueCount] = useState(0);
  const [query, setQuery] = useState("");
  const [theme, setTheme] = useState(document.documentElement.dataset.theme || "dark");
  const [localMode, setLocalMode] = useState(offline());
  const location = useLocation();
  const navigate = useNavigate();

  function toast(text: string) {
    const id = Date.now();
    setToasts((items) => [...items, { id, text }]);
    setTimeout(() => setToasts((items) => items.filter((item) => item.id !== id)), 2800);
  }

  useEffect(() => {
    api.summary().then((data) => setQueueCount(data.queue)).catch(() => setQueueCount(0));
  }, [location.pathname]);

  useEffect(() => {
    const mark = () => setLocalMode(true);
    window.addEventListener("pulse-fallback", mark);
    return () => window.removeEventListener("pulse-fallback", mark);
  }, []);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement;
      const typing = target.tagName === "INPUT" || target.tagName === "TEXTAREA";
      if ((event.key === "/" && !typing) || ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k")) {
        event.preventDefault();
        setPalette(true);
      }
      if (event.key === "Escape") setPalette(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function applyTheme(next: string) {
    const resolved = next === "system" ? (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark") : next;
    document.documentElement.dataset.theme = resolved;
    localStorage.setItem("pulse-theme", next);
    setTheme(next);
  }

  const crumb = location.pathname.startsWith("/sessions/")
    ? "Debug Session"
    : NAV.find(([path]) => path === location.pathname)?.[1] || "PulseJDWP";

  return (
    <div className="shell">
      <a className="skip" href="#page">Skip to content</a>
      <header className="global">
        <div className="brand"><Mark /><span className="hairline" /><span>PulseJDWP</span></div>
        <nav className="nav">
          {NAV.map(([path, label, icon]) => (
            <NavLink key={path} to={path} end={path === "/"} className={({ isActive }) => (isActive ? "active" : "")}>
              <svg width="14" height="14" viewBox="0 0 22 22" aria-hidden="true"><path d={icon} fill="none" stroke="currentColor" strokeWidth="1.6" /></svg>
              <span className="label">{label}</span>
              {path === "/queue" && queueCount > 0 ? <b className="count">{queueCount}</b> : null}
            </NavLink>
          ))}
        </nav>
        <div className="grow" />
        <button className="search-btn focus" onClick={() => setPalette(true)}>Search or jump to… <span className="muted">Ctrl/Cmd-K</span></button>
        <button className="icon-btn bell focus" aria-label="Alerts" onClick={() => setPanel((open) => !open)}>
          <span aria-hidden>!</span>
          {queueCount > 0 ? <i>{queueCount}</i> : null}
        </button>
        <select aria-label="Theme" value={theme} onChange={(event) => applyTheme(event.target.value)}>
          <option value="system">system</option>
          <option value="light">light</option>
          <option value="dark">dark</option>
        </select>
      </header>
      <div className="context">
        <div className="crumbs">PulseJDWP / <strong>{crumb}</strong></div>
        <div className="actions">
          {location.pathname === "/settings" || location.pathname === "/catalog" ? (
            <button className="btn primary focus" onClick={() => navigate("/settings")}>+ Add Skill / Target</button>
          ) : (
            <button className="btn primary focus" onClick={() => navigate("/sessions/new")}>+ New Debug Session</button>
          )}
        </div>
      </div>
      <main id="page" className="page">
        {localMode ? <div className="banner card">Local fallback stream is on. Token, breakpoint, and startup-script frames are simulated until the API answers.</div> : null}
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/catalog" element={<Catalog toast={toast} />} />
          <Route path="/sessions" element={<SessionList />} />
          <Route path="/sessions/new" element={<NewSession toast={toast} />} />
          <Route path="/sessions/:id" element={<SessionDetail toast={toast} />} />
          <Route path="/queue" element={<QueuePage toast={toast} />} />
          <Route path="/settings" element={<Settings toast={toast} />} />
        </Routes>
      </main>
      {palette ? <Palette query={query} setQuery={setQuery} onClose={() => setPalette(false)} /> : null}
      {panel ? (
        <aside className="panel">
          <strong>Alerts</strong>
          <p className="muted">{queueCount ? `${queueCount} gate${queueCount === 1 ? "" : "s"} waiting.` : "No unread gates."}</p>
          <button className="btn secondary" onClick={() => { setPanel(false); navigate("/queue"); }}>Open Human Queue</button>
        </aside>
      ) : null}
      <div className="toasts">{toasts.map((item) => <div key={item.id} className="toast">{item.text}</div>)}</div>
    </div>
  );
}

function Home() {
  const [summary, setSummary] = useState<Record<string, number> | null>(null);
  const [targets, setTargets] = useState<Target[] | null>(null);
  const [sessions, setSessions] = useState<Session[] | null>(null);
  const [error, setError] = useState("");
  const navigate = useNavigate();

  function load() {
    setError("");
    Promise.all([api.summary(), api.targets(), api.sessions()])
      .then(([sum, items, runs]) => { setSummary(sum); setTargets(items); setSessions(runs); })
      .catch((exc) => setError(String(exc)));
  }
  useEffect(load, []);
  if (error) return <ErrorState detail={error} onRetry={load} />;
  if (!summary || !targets || !sessions) return <div className="skel" />;

  const stats = [
    ["Active Debug Sessions", summary.active, "Streaming via LangGraph & JDWP", "/sessions?status=agent"],
    ["Human Queue Gates", summary.queue, "Awaiting breakpoint or script approval", "/queue"],
    ["Application Targets", summary.targets, "Startup scripts mapped via SSH MCP", "/catalog"],
    ["Loaded Agent Skills", summary.skills, "Pluggable diagnostic playbooks", "/catalog?group=Skills"],
    ["Root Causes Resolved", summary.resolved, "Avg diagnostic time 3m 40s", "/sessions?status=success"],
  ];
  const queue = sessions.filter((item) => item.pending);
  const live = sessions.filter((item) => item.status === "agent" || item.status === "info");

  return (
    <>
      <div className="stats">
        {stats.map(([label, number, note, href]) => (
          <button key={label} className="stat" onClick={() => navigate(String(href))}>
            <span>{label}</span><b>{number}</b><span>{note}</span>
          </button>
        ))}
      </div>
      {queue.length > 0 ? (
        <>
          <h2 className="h2">Needs you</h2>
          <div className="grid-tiles">{queue.map((item) => <SessionCard key={item.id} session={item} />)}</div>
        </>
      ) : null}
      <h2 className="h2">Live JDWP and SSH events</h2>
      <div className="row">
        <div className="card ticker">{sessions.flatMap((item) => item.events).slice(-6).map((event) => event.kind).join("\n") || "No events yet."}</div>
        <div className="card"><span className="muted">In flight</span>{live.map((item) => <p key={item.id}><Badge status={item.status} /> {item.targetId}</p>)}</div>
        <div className="card"><span className="muted">Recent</span>{sessions.slice(0, 4).map((item) => <p key={item.id}>{item.id}</p>)}</div>
      </div>
      <h2 className="h2">Application Targets</h2>
      <TargetTable targets={targets} />
    </>
  );
}

function Catalog({ toast }: { toast: (text: string) => void }) {
  const [targets, setTargets] = useState<Target[] | null>(null);
  const [skills, setSkills] = useState<Skill[] | null>(null);
  const [mode, setMode] = useState(localStorage.getItem("catalog-mode") || "tiles");
  const [group, setGroup] = useSearchParams();
  const [q, setQ] = useState("");
  const selectedRaw = group.get("group") || "All";
  const selected = selectedRaw === "Skills" ? "Agent Skills" : selectedRaw;
  useEffect(() => { Promise.all([api.targets(), api.skills()]).then(([t, s]) => { setTargets(t); setSkills(s); }); }, []);
  if (!targets || !skills) return <div className="skel" />;
  const groups = ["All", "Spring Boot", "Quarkus", "Jakarta EE", "Kafka / Messaging", "Core JVM", "Tomcat", "WebLogic", "WebSphere", "Agent Skills"];
  const filteredTargets = targets.filter((item) => selected !== "Agent Skills" && (selected === "All" || item.domain === selected) && item.name.includes(q));
  const showSkills = selected === "All" || selected === "Agent Skills";
  return (
    <>
      <div className="card" style={{ marginBottom: 12 }}>
        {targets.length} Application Targets · {skills.length} Agent Skills
      </div>
      <div className="actions" style={{ marginBottom: 12 }}>
        <input aria-label="Search catalog" placeholder="Search" value={q} onChange={(event) => setQ(event.target.value)} />
        <button className="btn secondary" onClick={() => { const next = mode === "tiles" ? "table" : "tiles"; localStorage.setItem("catalog-mode", next); setMode(next); }}>{mode === "tiles" ? "Table" : "Tiles"}</button>
      </div>
      <div className="chips">
        {groups.map((item) => (
          <button key={item} className={item === selected ? "chip on" : "chip"} onClick={() => setGroup(item === "All" ? {} : { group: item })}>{item}</button>
        ))}
      </div>
      {mode === "tiles" ? (
        <div className="grid-tiles" style={{ marginTop: 12 }}>
          {filteredTargets.map((target) => (
            <article key={target.id} className="tile">
              <strong>{target.name}</strong>
              <p className="muted">{target.domain} · JDWP {target.jdwpPort}</p>
              {target.latestSession ? <Badge status={target.latestSession.status} /> : <span className="muted">No Debug Session</span>}
            </article>
          ))}
          {showSkills ? skills.filter((skill) => skill.name.toLowerCase().includes(q.toLowerCase())).map((skill) => (
            <article key={skill.id} className="tile"><strong>{skill.name}</strong><p className="muted">{skill.domain}</p></article>
          )) : null}
        </div>
      ) : <TargetTable targets={filteredTargets} />}
    </>
  );
}

function SessionList() {
  const [params] = useSearchParams();
  const [rows, setRows] = useState<Session[] | null>(null);
  const [error, setError] = useState("");
  const status = params.get("status") || "";
  function load() {
    api.sessions(status).then(setRows).catch((exc) => setError(String(exc)));
  }
  useEffect(load, [status]);
  if (error) return <ErrorState detail={error} onRetry={load} />;
  if (!rows) return <div className="skel" />;
  if (!rows.length) return <div className="empty card"><h2>No Debug Sessions</h2><p>Start one from the context bar.</p></div>;
  return <div className="grid-tiles">{rows.map((session) => <SessionCard key={session.id} session={session} />)}</div>;
}

function SessionCard({ session }: { session: Session }) {
  const navigate = useNavigate();
  return (
    <button className="tile" onClick={() => navigate(`/sessions/${session.id}`)}>
      <Badge status={session.status} />
      <strong style={{ display: "block", marginTop: 8 }}>{session.targetId}</strong>
      <p className="muted">{session.summary}</p>
      <span className="muted">{session.createdAt || session.id}</span>
    </button>
  );
}

function formatEvent(event: Session["events"][number]) {
  if (event.kind === "llm_token") return event.token || "";
  const detail = event.detail && typeof event.detail === "object" ? event.detail as { locals?: { name: string; value: string }[]; frames?: string[] } : null;
  const locals = detail?.locals?.map((item) => `${item.name}=${item.value}`).join(", ") || "";
  const frames = detail?.frames?.join("\n") || "";
  const text = typeof event.detail === "string" ? event.detail : "";
  const body = [event.output, locals, frames, text].filter(Boolean).join("\n");
  return `\n[${event.kind}${event.event ? ` ${event.event}` : ""}] ${event.command || event.stepper || ""}\n${body}\n`;
}

function SessionDetail({ toast }: { toast: (text: string) => void }) {
  const { id = "" } = useParams();
  const [session, setSession] = useState<Session | null>(null);
  const [tab, setTab] = useState("Live Stream & Console");
  const [log, setLog] = useState("");
  const [error, setError] = useState("");
  function load() {
    api.session(id).then((row) => {
      setSession(row);
      if (row.status === "success" || row.status === "danger") setLog(row.events.map(formatEvent).join(""));
    }).catch((exc) => setError(String(exc)));
  }
  useEffect(load, [id]);
  useEffect(() => {
    if (!session || session.status === "success" || session.status === "danger") return;
    if (offline()) {
      return playFallbackStream(id, (event) => {
        if (event.kind === "llm_token") setLog((text) => text + (event.token || ""));
        else setLog((text) => text + `\n[${event.kind}] ${event.command || ""}\n${event.output || ""}`);
        if (event.status) setSession((current) => current ? { ...current, status: event.status || current.status, stepper: event.stepper || current.stepper } : current);
      });
    }
    const source = new EventSource(`/api/sessions/${id}/stream`);
    source.onmessage = (message) => {
      const event = JSON.parse(message.data);
      if (event.kind === "llm_token") setLog((text) => text + (event.token || ""));
      else setLog((text) => text + formatEvent(event));
      if (event.status) setSession((current) => current ? { ...current, status: event.status, stepper: event.stepper || current.stepper } : current);
      if (event.status === "success" || event.status === "danger") api.session(id).then(setSession).catch(() => undefined);
    };
    source.onerror = () => source.close();
    return () => source.close();
  }, [id, session?.status]);
  if (error) return <ErrorState detail={error} onRetry={load} />;
  if (!session) return <div className="skel" />;
  const steps = ["Stack Ingested", "SSH MCP Startup Check", "JDWP Attached", "Breakpoint & Frame Capture", "Root Cause Synthesized"];
  const tabs = ["Live Stream & Console", "Issue Stack & Breakpoints", "Variables & Thread Frames", "Startup Script & JDWP Port", "Attached Skills & Context"];
  return (
    <>
      <div className="card">
        <Badge status={session.status} />
        <p>{session.summary}</p>
        <div className="stepper">{steps.map((step) => <span key={step} className={step === session.stepper ? "on" : ""}>{step}</span>)}</div>
      </div>
      <div className="tabs">{tabs.map((item) => <button key={item} className={item === tab ? "on" : ""} onClick={() => setTab(item)}>{item}</button>)}</div>
      {tab === "Live Stream & Console" ? <div className="console">{log || session.events.map((event) => event.token || event.kind).join("") || "Waiting for SSE frames."}</div> : null}
      {tab === "Issue Stack & Breakpoints" ? <pre className="console">{session.stack}{"\n\n"}{session.frames.map((frame) => `${frame.className}.${frame.method}:${frame.line}`).join("\n")}</pre> : null}
      {tab === "Variables & Thread Frames" ? <pre className="console">{JSON.stringify(session.variables, null, 2)}{"\n"}{session.threads.join("\n")}</pre> : null}
      {tab === "Startup Script & JDWP Port" ? <pre className="console">{session.startupScript}{"\nport "}{session.jdwpPort}{"\n"}{session.startupText}</pre> : null}
      {tab === "Attached Skills & Context" ? <SkillAttach session={session} toast={toast} onSaved={load} /> : null}
    </>
  );
}

function SkillAttach({ session, toast, onSaved }: { session: Session; toast: (text: string) => void; onSaved: () => void }) {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [extra, setExtra] = useState(session.extraContext || "");
  useEffect(() => { api.skills().then(setSkills); }, []);
  return (
    <form className="card" onSubmit={(event) => { event.preventDefault(); toast("Context noted for the next run."); onSaved(); }}>
      <p>{session.skills.join(", ") || "No skill selected yet."}</p>
      <label>Extra application context<textarea value={extra} onChange={(event) => setExtra(event.target.value)} /></label>
      <p className="muted">{skills.length} skills available in the catalog.</p>
      <button className="btn primary" type="submit">Attach context</button>
    </form>
  );
}

function NewSession({ toast }: { toast: (text: string) => void }) {
  const [targets, setTargets] = useState<Target[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [targetId, setTargetId] = useState("");
  const [stack, setStack] = useState("java.lang.NullPointerException\n\tat com.ecs.oms.saga.CheckoutSagaService.capture(CheckoutSagaService.java:214)\n");
  const [extra, setExtra] = useState("");
  const [picked, setPicked] = useState<string[]>(["npe-root-cause-tracer"]);
  const navigate = useNavigate();
  useEffect(() => { Promise.all([api.targets(), api.skills()]).then(([t, s]) => { setTargets(t); setSkills(s); setTargetId(t[0]?.id || ""); }); }, []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    const session = await api.createSession({ targetId, stack, extraContext: extra, skillIds: picked });
    toast("Debug Session started");
    navigate(`/sessions/${session.id}`);
  }
  return (
    <form className="card" onSubmit={submit}>
      <label>Application Target
        <select value={targetId} onChange={(event) => setTargetId(event.target.value)}>{targets.map((target) => <option key={target.id} value={target.id}>{target.name}</option>)}</select>
      </label>
      <label>Issue stack trace<textarea value={stack} onChange={(event) => setStack(event.target.value)} /></label>
      <label>Extra application details<textarea value={extra} onChange={(event) => setExtra(event.target.value)} /></label>
      <div className="chips">{skills.map((skill) => (
        <button type="button" key={skill.id} className={picked.includes(skill.id) ? "chip on" : "chip"} onClick={() => setPicked((ids) => ids.includes(skill.id) ? ids.filter((id) => id !== skill.id) : [...ids, skill.id])}>{skill.name}</button>
      ))}</div>
      <button className="btn primary" type="submit" style={{ marginTop: 12 }}>Start Debug Session</button>
    </form>
  );
}

function QueuePage({ toast }: { toast: (text: string) => void }) {
  const [items, setItems] = useState<QueueItem[] | null>(null);
  const buckets = ["Startup Script & JDWP Port Injection", "Thread Suspension & Live Breakpoints", "Root Cause & Remediation Sign-off"];
  function load() { api.queue().then(setItems); }
  useEffect(load, []);
  if (!items) return <div className="skel" />;
  if (!items.length) return <div className="empty card"><h2>The queue is empty.</h2></div>;
  return (
    <>
      {buckets.map((bucket) => {
        const rows = items.filter((item) => item.bucket === bucket);
        if (!rows.length) return null;
        return (
          <section key={bucket}>
            <h2 className="h2">{bucket}</h2>
            {rows.map((item) => (
              <article key={item.sessionId} className="queue-card" style={{ marginBottom: 8 }}>
                <strong>{item.summary}</strong>
                <p className="muted">Since {item.waited}</p>
                <button className="btn primary" onClick={async () => { await api.approve(item.sessionId, true); toast("Human gate approved"); load(); }}>Approve</button>
              </article>
            ))}
          </section>
        );
      })}
    </>
  );
}

function Settings({ toast }: { toast: (text: string) => void }) {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [confirmId, setConfirmId] = useState("");
  const navigate = useNavigate();
  function load() { api.skills().then(setSkills); }
  useEffect(load, []);
  async function addSkill(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    await api.saveSkill({
      id: String(data.get("name")),
      name: String(data.get("name")),
      domain: String(data.get("domain")),
      triggerPatterns: String(data.get("triggers")).split(",").map((item) => item.trim()).filter(Boolean),
      systemInstructions: String(data.get("prompt")),
      customCommands: String(data.get("commands")).split("|").map((item) => item.trim()).filter(Boolean),
      description: String(data.get("name")),
    });
    toast("Skill added");
    load();
    event.currentTarget.reset();
  }
  return (
    <>
      <form className="card" onSubmit={addSkill}>
        <h2 className="h2">Add skill</h2>
        <label>Name<input name="name" required /></label>
        <label>Runtime domain<input name="domain" defaultValue="Core JVM" /></label>
        <label>Trigger exceptions<input name="triggers" placeholder="NullPointerException" /></label>
        <label>Markdown system prompt<textarea name="prompt" required /></label>
        <label>JDWP inspection commands<input name="commands" placeholder="where|locals" /></label>
        <button className="btn primary" type="submit">Save skill</button>
      </form>
      <form className="card" style={{ marginTop: 12 }} onSubmit={(event) => { event.preventDefault(); toast("SSH MCP settings stay in the backend environment"); }}>
        <h2 className="h2">Linux SSH MCP</h2>
        <label>Command<input defaultValue="uv" /></label>
        <label>Startup script patterns<input defaultValue="setenv.sh, start.sh, Dockerfile, *.service" /></label>
        <button className="btn secondary" type="submit">Save connection notes</button>
      </form>
      <h2 className="h2">Loaded skills</h2>
      {skills.map((skill) => (
        <div key={skill.id} className="card" style={{ marginBottom: 8, display: "flex", justifyContent: "space-between" }}>
          <span>{skill.name}<br /><span className="muted">{skill.domain}</span></span>
          <button className="btn danger" onClick={() => setConfirmId(skill.id)}>Delete</button>
        </div>
      ))}
      <button className="btn ghost" onClick={() => navigate("/catalog")}>Open catalog</button>
      {confirmId ? (
        <div className="modal-back">
          <div className="modal">
            <p>Delete skill {confirmId}?</p>
            <button className="btn danger" onClick={async () => { await api.deleteSkill(confirmId); toast(`Deleted ${confirmId}`); setConfirmId(""); load(); }}>Delete {confirmId}</button>
            <button className="btn ghost" onClick={() => setConfirmId("")}>Cancel</button>
          </div>
        </div>
      ) : null}
    </>
  );
}

function TargetTable({ targets }: { targets: Target[] }) {
  return (
    <table className="table">
      <thead><tr><th>Application Target</th><th>Domain</th><th>JDWP</th><th>Latest Debug Session</th></tr></thead>
      <tbody>
        {targets.map((target) => (
          <tr key={target.id}>
            <td>{target.name}</td>
            <td>{target.domain}</td>
            <td className="mono">{target.jdwpPort}</td>
            <td>{target.latestSession ? <Badge status={target.latestSession.status} /> : "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Palette({ query, setQuery, onClose }: { query: string; setQuery: (value: string) => void; onClose: () => void }) {
  const navigate = useNavigate();
  const items = useMemo(() => ["/ Dashboard", "/catalog Catalog", "/sessions Debug Sessions", "/queue Human Queue", "/settings Settings & Skills"], []);
  return (
    <div className="palette">
      <input autoFocus placeholder="Search or jump to…" value={query} onChange={(event) => setQuery(event.target.value)} />
      {items.filter((item) => item.toLowerCase().includes(query.toLowerCase())).map((item) => (
        <button key={item} className="btn ghost" style={{ display: "block", width: "100%", textAlign: "left" }} onClick={() => { navigate(item.split(" ")[0]); onClose(); }}>{item}</button>
      ))}
    </div>
  );
}

function ErrorState({ detail, onRetry }: { detail: string; onRetry: () => void }) {
  return <div className="card"><strong>Could not load this page.</strong><p className="muted">{detail}</p><button className="btn secondary" onClick={onRetry}>Retry</button></div>;
}
