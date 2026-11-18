import { useCallback, useEffect, useMemo, useState } from "react";

type Status = "queued" | "running" | "awaiting_approval" | "completed" | "failed";
type Evidence = {
  evidence_id: string;
  source_id: string;
  document_id: string;
  chunk_id: string;
  excerpt: string;
  metadata: Record<string, unknown>;
  retrieval_score: number;
  sparse_score: number;
  dense_score?: number | null;
};
type Finding = {
  id: string;
  statement: string;
  classification: string;
  evidence_refs: { evidence_id: string }[];
};
type Report = {
  summary: string;
  findings: Finding[];
  hypotheses: { id: string; statement: string; classification: string; rationale: string }[];
  unresolved_questions: { question: string; reason: string }[];
  evidence: Evidence[];
  conflicts: { description: string; evidence_refs: { evidence_id: string }[] }[];
  recommended_actions: string[];
  limitations: string[];
};
type Investigation = {
  id: string;
  request: string;
  status: Status;
  plan?: { tasks: { id: string; title: string; status: string }[] } | null;
  evidence: Evidence[];
  tool_executions: { id: string; tool_name: string; status: string; simulated: boolean }[];
  report?: Report | null;
  created_at: string;
};
type Approval = {
  id: string;
  investigation_id: string;
  action: string;
  rationale: string;
  status: string;
};
type EventItem = { id: number; event_type: string; message: string; created_at: string };
type Tab = "Overview" | "Investigations" | "Knowledge base" | "Approvals" | "Settings";

const API_BASE = import.meta.env.VITE_API_URL ?? "";
const TABS: Tab[] = ["Overview", "Investigations", "Knowledge base", "Approvals", "Settings"];

function stored(key: string, fallback = ""): string {
  return localStorage.getItem(key) ?? fallback;
}

export default function App() {
  const [tab, setTab] = useState<Tab>("Overview");
  const [apiKey, setApiKey] = useState(() => stored("enterpriseiq-api-key"));
  const [organization, setOrganization] = useState(() => stored("enterpriseiq-organization", "local"));
  const [investigations, setInvestigations] = useState<Investigation[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [selected, setSelected] = useState<Investigation | null>(null);
  const [events, setEvents] = useState<EventItem[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [query, setQuery] = useState("");
  const [searchText, setSearchText] = useState("");
  const [searchResults, setSearchResults] = useState<Evidence[]>([]);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [health, setHealth] = useState("checking");

  const headers = useMemo(() => {
    const result = new Headers();
    if (apiKey) result.set("X-API-Key", apiKey);
    if (organization) result.set("X-Organization-Id", organization);
    return result;
  }, [apiKey, organization]);

  const request = useCallback(
    async <T,>(path: string, init: RequestInit = {}): Promise<T> => {
      const requestHeaders = new Headers(headers);
      new Headers(init.headers).forEach((value, key) => requestHeaders.set(key, value));
      if (init.body && !(init.body instanceof FormData) && !requestHeaders.has("Content-Type")) {
        requestHeaders.set("Content-Type", "application/json");
      }
      const response = await fetch(`${API_BASE}${path}`, { ...init, headers: requestHeaders });
      if (!response.ok) {
        const detail = await response.json().catch(() => null);
        throw new Error(detail?.detail ?? `Request failed (${response.status})`);
      }
      return response.json() as Promise<T>;
    },
    [headers],
  );

  const refresh = useCallback(async () => {
    try {
      const [items, pending, status] = await Promise.all([
        request<Investigation[]>("/api/v1/investigations"),
        request<Approval[]>("/api/v1/approvals"),
        request<{ status: string }>("/health"),
      ]);
      setInvestigations(items);
      setApprovals(pending);
      setHealth(status.status);
      if (!selectedId && items[0]) setSelectedId(items[0].id);
      setError("");
    } catch (reason) {
      setHealth("offline");
      setError(reason instanceof Error ? reason.message : "Could not reach the API.");
    }
  }, [request, selectedId]);

  useEffect(() => {
    localStorage.setItem("enterpriseiq-api-key", apiKey);
    localStorage.setItem("enterpriseiq-organization", organization);
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [apiKey, organization, refresh]);

  useEffect(() => {
    if (!selectedId) {
      setSelected(null);
      setEvents([]);
      return;
    }
    let active = true;
    const load = async () => {
      try {
        const [item, activity] = await Promise.all([
          request<Investigation>(`/api/v1/investigations/${selectedId}`),
          request<EventItem[]>(`/api/v1/investigations/${selectedId}/events`),
        ]);
        if (active) {
          setSelected(item);
          setEvents(activity);
        }
      } catch {
        if (active) setSelected(null);
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 1800);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [request, selectedId]);

  async function startInvestigation(event: React.FormEvent) {
    event.preventDefault();
    if (query.trim().length < 8) return;
    setBusy(true);
    setError("");
    try {
      const created = await request<Investigation>("/api/v1/investigations", {
        method: "POST",
        body: JSON.stringify({ request: query.trim() }),
      });
      setQuery("");
      setSelectedId(created.id);
      setTab("Investigations");
      setNotice("Investigation started. Progress and evidence will appear here.");
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not start investigation.");
    } finally {
      setBusy(false);
    }
  }

  async function searchKnowledge(event: React.FormEvent) {
    event.preventDefault();
    if (!searchText.trim()) return;
    setBusy(true);
    try {
      const result = await request<{ evidence: Evidence[]; warnings: string[] }>(
        `/api/v1/knowledge/search?q=${encodeURIComponent(searchText.trim())}`,
      );
      setSearchResults(result.evidence);
      setNotice(result.warnings.join(" "));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Search failed.");
    } finally {
      setBusy(false);
    }
  }

  async function uploadDocument(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const data = new FormData();
    data.set("file", file);
    setBusy(true);
    try {
      const result = await request<{ source: string; chunk_count: number }>(
        "/api/v1/knowledge/documents",
        { method: "POST", body: data },
      );
      setNotice(`Indexed ${result.source}: ${result.chunk_count} chunk(s).`);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Upload failed.");
    } finally {
      setBusy(false);
      event.target.value = "";
    }
  }

  async function decide(id: string, decision: "approved" | "rejected") {
    try {
      await request(`/api/v1/approvals/${id}/decision`, {
        method: "POST",
        body: JSON.stringify({ decision, note: "Decision recorded in Approval Center." }),
      });
      setNotice(`Approval ${decision}. No live operational change was executed.`);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not record decision.");
    }
  }

  async function requestApproval(action: string) {
    if (!selectedId) return;
    try {
      await request(`/api/v1/investigations/${selectedId}/approvals`, {
        method: "POST",
        body: JSON.stringify({
          action,
          rationale: "Approval is required before any operational change. This demo records decisions only and does not execute changes.",
        }),
      });
      setNotice("Approval request created. No operational change was executed.");
      setTab("Approvals");
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not request approval.");
    }
  }

  const count = (status: Status) => investigations.filter((item) => item.status === status).length;

  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="#" onClick={() => setTab("Overview")}>
          <span className="brand-mark">E</span>
          <span><strong>EnterpriseIQ</strong><small>INCIDENT INTELLIGENCE</small></span>
        </a>
        <div className="workspace-label">WORKSPACE</div>
        <nav>
          {TABS.map((item, index) => (
            <button className={`nav-item ${tab === item ? "active" : ""}`} key={item} onClick={() => setTab(item)}>
              <span className="nav-icon">{["⌂", "◎", "▤", "◇", "⚙"][index]}</span>
              {item}
              {item === "Approvals" && approvals.length > 0 && <span className="badge">{approvals.length}</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <span className={`health-dot ${health}`} />
          <span>API {health}</span>
          <span className="sidebar-version">v1.0</span>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="breadcrumb">EnterpriseIQ <span>/</span> {tab}</div>
          <div className="topbar-right">
            <span className="environment"><i /> LOCAL WORKSPACE</span>
            <div className="avatar">I</div>
          </div>
        </header>

        <section className="content">
          {error && <div className="alert error"><strong>Request failed</strong><span>{error}</span><button onClick={() => setError("")}>×</button></div>}
          {notice && <div className="alert notice"><span>{notice}</span><button onClick={() => setNotice("")}>×</button></div>}

          {tab === "Overview" && (
            <>
              <div className="page-heading">
                <div><p className="eyebrow">OPERATIONS INTELLIGENCE</p><h1>Incident command</h1><p className="subheading">Investigate incidents with traceable evidence and explicit uncertainty.</p></div>
                <button className="button primary" onClick={() => setTab("Investigations")}>＋ New investigation</button>
              </div>
              <form className="investigate-card" onSubmit={startInvestigation}>
                <div className="card-kicker"><span className="pulse" /> START AN INVESTIGATION</div>
                <label htmlFor="incident-query">Describe the incident</label>
                <textarea id="incident-query" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="e.g. Our payment API had intermittent 500 errors after yesterday's deployment. Find relevant evidence and identify what remains unknown." rows={3} />
                <div className="card-footer"><span>Sources are treated as evidence, not instructions. Retrieval alone never confirms a cause.</span><button className="button primary" disabled={busy || query.trim().length < 8}>{busy ? "Working…" : "Investigate"} <span>→</span></button></div>
              </form>
              <div className="stats-grid">
                <Stat label="Total investigations" value={investigations.length} detail="Across this workspace" />
                <Stat label="In progress" value={count("running") + count("queued")} detail="Workflow tasks active" accent="blue" />
                <Stat label="Awaiting review" value={approvals.length} detail="Human decisions required" accent="amber" />
                <Stat label="Completed" value={count("completed")} detail="Reports available" accent="green" />
              </div>
              <div className="section-title"><div><h2>Recent investigations</h2><p>Latest activity in this workspace</p></div><button className="text-button" onClick={() => setTab("Investigations")}>View all →</button></div>
              <InvestigationTable items={investigations.slice(0, 5)} onSelect={(id) => { setSelectedId(id); setTab("Investigations"); }} />
            </>
          )}

          {tab === "Investigations" && (
            <>
              <div className="page-heading"><div><p className="eyebrow">INVESTIGATION WORKSPACE</p><h1>Investigations</h1><p className="subheading">Review workflow status, evidence, findings, and unresolved questions.</p></div></div>
              <form className="compact-form" onSubmit={startInvestigation}>
                <textarea value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Describe a new incident to investigate…" rows={2} />
                <button className="button primary" disabled={busy || query.trim().length < 8}>＋ Start</button>
              </form>
              <div className="investigation-layout">
                <div className="panel list-panel"><div className="panel-heading"><h2>All investigations</h2><span>{investigations.length}</span></div><InvestigationTable items={investigations} selectedId={selectedId} onSelect={setSelectedId} /></div>
                <div className="panel detail-panel">
                  {!selected ? <EmptyState title="Select an investigation" body="Choose an investigation to see its plan, evidence, and report." /> : (
                    <>
                      <div className="detail-title"><div><p className="eyebrow">INVESTIGATION {selected.id.slice(0, 8).toUpperCase()}</p><h2>{selected.request}</h2></div><StatusPill status={selected.status} /></div>
                      <div className="activity-strip"><strong>WORKFLOW ACTIVITY</strong>{events.map((item) => <div className="event-row" key={item.id}><span className="event-check">✓</span><span>{item.message}</span><time>{new Date(item.created_at).toLocaleTimeString()}</time></div>)}</div>
                      {selected.plan && <div className="detail-section"><h3>Investigation plan</h3>{selected.plan.tasks.map((task) => <div className="task-row" key={task.id}><span className={task.status === "completed" ? "task-done" : "task-pending"}>{task.status === "completed" ? "✓" : "·"}</span><span>{task.title}</span><small>{task.status}</small></div>)}</div>}
                      {selected.report ? <ReportView report={selected.report} onRequestApproval={requestApproval} /> : <div className="loading-state"><span className="spinner" /> Investigation is running. New steps will appear automatically.</div>}
                      {selected.tool_executions.length > 0 && <div className="detail-section"><h3>Tool execution history</h3>{selected.tool_executions.map((tool) => <div className="tool-row" key={tool.id}><span className="tool-icon">⌘</span><strong>{tool.tool_name.replaceAll("_", " ")}</strong><span className="tag muted">{tool.status.replaceAll("_", " ")}</span>{tool.simulated && <span className="tag amber">SIMULATED</span>}</div>)}</div>}
                    </>
                  )}
                </div>
              </div>
            </>
          )}

          {tab === "Knowledge base" && (
            <>
              <div className="page-heading"><div><p className="eyebrow">EVIDENCE SOURCES</p><h1>Knowledge base</h1><p className="subheading">Upload source material and search it with lexical retrieval and optional vector fusion.</p></div></div>
              <div className="knowledge-grid">
                <div className="panel upload-panel"><div className="panel-heading"><h2>Add documents</h2><span className="tag blue">10 MB MAX</span></div><p>PDF, DOCX, PPTX, TXT, Markdown, HTML, CSV, JSON, or log files.</p><label className="upload-zone"><span className="upload-symbol">↑</span><strong>Choose a document</strong><small>Text is extracted and indexed locally.</small><input type="file" accept=".pdf,.docx,.pptx,.txt,.md,.html,.htm,.csv,.json,.log" onChange={uploadDocument} disabled={busy} /></label><p className="fine-print">Duplicate content is detected by SHA-256. Uploaded sources are scoped to this organization.</p></div>
                <div className="panel search-panel"><div className="panel-heading"><h2>Search evidence</h2><span className="tag green">BM25 + OPTIONAL DENSE</span></div><form className="search-form" onSubmit={searchKnowledge}><input value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder="Search incident notes, runbooks, or documents…" /><button className="button primary" disabled={busy}>Search</button></form><EvidenceList evidence={searchResults} /></div>
              </div>
            </>
          )}

          {tab === "Approvals" && (
            <>
              <div className="page-heading"><div><p className="eyebrow">HUMAN-IN-THE-LOOP</p><h1>Approval center</h1><p className="subheading">Review proposed operational actions. Decisions are recorded; no live change is executed.</p></div><span className="tag amber">{approvals.length} PENDING</span></div>
              {approvals.length === 0 ? <EmptyState title="You're all caught up" body="No approval requests are waiting for review." /> : <div className="approval-list">{approvals.map((approval) => <div className="panel approval-card" key={approval.id}><div className="approval-icon">!</div><div className="approval-content"><span className="eyebrow">INVESTIGATION {approval.investigation_id.slice(0, 8).toUpperCase()}</span><h2>{approval.action}</h2><p>{approval.rationale}</p><div className="approval-actions"><button className="button quiet" onClick={() => void decide(approval.id, "rejected")}>Reject</button><button className="button primary" onClick={() => void decide(approval.id, "approved")}>Approve request</button></div></div></div>)}</div>}
            </>
          )}

          {tab === "Settings" && (
            <>
              <div className="page-heading"><div><p className="eyebrow">WORKSPACE CONFIGURATION</p><h1>Settings</h1><p className="subheading">Configure this browser's API connection. Keys are kept in local storage only.</p></div></div>
              <div className="panel settings-panel"><label>API base URL<input value={API_BASE || window.location.origin} readOnly /></label><label>Organization ID<input value={organization} onChange={(event) => setOrganization(event.target.value)} /></label><label>API key<input type="password" autoComplete="new-password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="Required only when server authentication is enabled" /></label><div className="settings-note"><strong>Local demo safeguards</strong><p>External vector retrieval is disabled by default. Tool integrations return explicit simulated “not configured” results. No remediation is performed from this interface.</p></div><button className="button primary" onClick={() => setNotice("Settings saved in this browser.")}>Save settings</button></div>
            </>
          )}
        </section>
      </main>
    </div>
  );
}

function Stat({ label, value, detail, accent = "slate" }: { label: string; value: number; detail: string; accent?: string }) {
  return <div className="panel stat-card"><div className={`stat-icon ${accent}`}>◈</div><div><span>{label}</span><strong>{value}</strong><small>{detail}</small></div></div>;
}

function StatusPill({ status }: { status: Status }) {
  return <span className={`status-pill ${status}`}><i />{status.replaceAll("_", " ")}</span>;
}

function InvestigationTable({ items, selectedId, onSelect }: { items: Investigation[]; selectedId?: string; onSelect: (id: string) => void }) {
  if (items.length === 0) return <EmptyState title="No investigations yet" body="Start an investigation to begin collecting evidence." />;
  return <div className="table-wrap"><table><thead><tr><th>INCIDENT</th><th>STATUS</th><th>EVIDENCE</th><th>STARTED</th></tr></thead><tbody>{items.map((item) => <tr className={selectedId === item.id ? "selected-row" : ""} key={item.id} onClick={() => onSelect(item.id)}><td><strong>{item.request}</strong><small>#{item.id.slice(0, 8)}</small></td><td><StatusPill status={item.status} /></td><td><span className="evidence-count">{item.evidence?.length ?? 0} sources</span></td><td>{new Date(item.created_at).toLocaleString()}</td></tr>)}</tbody></table></div>;
}

function EvidenceList({ evidence }: { evidence: Evidence[] }) {
  if (evidence.length === 0) return <div className="empty-inline">Search results will include source excerpts and traceable evidence IDs.</div>;
  return <div className="evidence-list">{evidence.map((item) => <EvidenceCard evidence={item} key={item.evidence_id} />)}</div>;
}

function EvidenceCard({ evidence }: { evidence: Evidence }) {
  return <article className="evidence-card"><div className="evidence-meta"><span className="source-glyph">▤</span><strong>{String(evidence.metadata.source ?? evidence.source_id)}</strong><span className="tag blue">{evidence.source_id}</span><code>{evidence.evidence_id}</code></div><blockquote>{evidence.excerpt}</blockquote><div className="evidence-scores"><span>BM25 {evidence.sparse_score.toFixed(3)}</span><span>Fusion {evidence.retrieval_score.toFixed(4)}</span>{evidence.dense_score != null && <span>Dense {evidence.dense_score.toFixed(3)}</span>}</div></article>;
}

function ReportView({ report, onRequestApproval }: { report: Report; onRequestApproval: (action: string) => void }) {
  return <div className="detail-section report-section"><div className="section-title"><div><h3>Investigation report</h3><p>Generated from retrieved evidence. No cause was silently promoted to confirmed.</p></div><span className="tag green">EVIDENCE GROUNDED</span></div><div className="report-summary">{report.summary}</div>{report.conflicts.length > 0 && <><h4>Conflicting evidence</h4>{report.conflicts.map((conflict) => <div className="finding-card conflict-card" key={conflict.evidence_refs.map((item) => item.evidence_id).join(":")}><span className="tag amber">CONTRADICTED</span><p>{conflict.description}</p><div className="citation-row">{conflict.evidence_refs.map((item) => <code key={item.evidence_id}>{item.evidence_id}</code>)}</div></div>)}</>}<h4>Findings</h4>{report.findings.length === 0 ? <p className="muted-copy">No relevant document evidence was retrieved. Findings remain unresolved.</p> : report.findings.map((finding) => <div className="finding-card" key={finding.id}><span className={`tag ${finding.classification === "confirmed" ? "green" : "amber"}`}>{finding.classification}</span><p>{finding.statement}</p><div className="citation-row">{finding.evidence_refs.map((reference) => <code key={reference.evidence_id}>{reference.evidence_id}</code>)}</div></div>)}<h4>Evidence</h4><EvidenceList evidence={report.evidence} /><h4>Hypotheses</h4>{report.hypotheses.length === 0 ? <p className="muted-copy">No hypothesis is supported by current evidence.</p> : report.hypotheses.map((item) => <div className="hypothesis-card" key={item.id}><span className="tag amber">{item.classification}</span><p>{item.statement}</p><small>{item.rationale}</small></div>)}<h4>Unresolved questions</h4><ul className="question-list">{report.unresolved_questions.map((item) => <li key={item.question}><strong>{item.question}</strong><small>{item.reason}</small></li>)}</ul><h4>Recommended next steps</h4><div className="recommended-list">{report.recommended_actions.map((item) => <div className="recommended-action" key={item}><span>{item}</span><button className="text-button" onClick={() => onRequestApproval(item)}>Request approval →</button></div>)}</div><h4>Limitations</h4><ul className="limitation-list">{report.limitations.map((item) => <li key={item}>{item}</li>)}</ul></div>;
}

function EmptyState({ title, body }: { title: string; body: string }) {
  return <div className="empty-state"><div className="empty-icon">⌕</div><strong>{title}</strong><p>{body}</p></div>;
}
