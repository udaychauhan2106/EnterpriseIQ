import { useCallback, useEffect, useMemo, useRef, useState } from "react";

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
  retrieved_at: string;
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
  hypotheses: {
    id: string;
    statement: string;
    classification: string;
    evidence_refs: { evidence_id: string }[];
    rationale: string;
  }[];
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
  approvals: Approval[];
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
type EventItem = {
  id: number;
  event_type: string;
  message: string;
  data: Record<string, unknown>;
  created_at: string;
};
type ScenarioSummary = {
  scenario_id: string;
  title: string;
  description: string;
  difficulty: string;
  severity: string;
  affected_services: string[];
  synthetic: boolean;
};
type EvidenceSource = {
  artifact_id: string;
  source: string;
  source_type: string;
  available: boolean;
};
type EvidenceManifest = {
  scenario_id: string;
  synthetic: boolean;
  available: boolean;
  sources: EvidenceSource[];
};
type ScenarioEvent = {
  event_id: string;
  timestamp: string;
  source: string;
  service_id: string;
  severity: string;
  message: string;
  correlation_id?: string | null;
};
type ScenarioHistory = {
  synthetic: boolean;
  incident: {
    scenario_id: string;
    title: string;
    started_at: string;
    window_ended_at: string;
  };
  events: ScenarioEvent[];
};
type ScenarioArtifact = {
  scenario_id: string;
  artifact_id: string;
  source: string;
  source_type: string;
  content: string;
  synthetic: boolean;
};
type DemoStreamState = "idle" | "connecting" | "connected" | "retrying" | "polling" | "closed";
type SimulatedEvent = {
  event_id: string;
  timestamp: string;
  source: string;
  service_id: string;
  severity: string;
  message: string;
  correlation_id?: string | null;
};
type SimulatedMetric = {
  sample_id: string;
  timestamp: string;
  service_id: string;
  metric_name: string;
  value: number;
  unit: string;
};
type SimulationRun = {
  run_id: string;
  scenario_id: string;
  seed: number;
  status: string;
  elapsed_seconds: number;
  duration_seconds: number;
  window_complete: boolean;
  synthetic: boolean;
  events: SimulatedEvent[];
  metrics: SimulatedMetric[];
  service_health: { service_id: string; service_name: string; observed_status: string }[];
};
type SimulationRunSummary = Pick<
  SimulationRun,
  "run_id" | "scenario_id" | "seed" | "status" | "elapsed_seconds" | "duration_seconds" | "synthetic" | "window_complete"
>;
type Tab = "Overview" | "Demo Center" | "Investigations" | "Knowledge base" | "Incident Lab" | "Approvals" | "Settings";

const API_BASE = import.meta.env.VITE_API_URL ?? "";
const TABS: Tab[] = ["Overview", "Demo Center", "Investigations", "Knowledge base", "Incident Lab", "Approvals", "Settings"];

function stored(key: string, fallback = ""): string {
  return localStorage.getItem(key) ?? fallback;
}

function demoKeyStorageKey(organization: string, scenarioId: string): string {
  return `enterpriseiq-demo-idempotency:${organization}:${scenarioId}`;
}

class ApiRequestError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "ApiRequestError";
  }
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
  const [scenarios, setScenarios] = useState<ScenarioSummary[]>([]);
  const [selectedScenarioId, setSelectedScenarioId] = useState("");
  const [simulationRuns, setSimulationRuns] = useState<SimulationRunSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [activeRun, setActiveRun] = useState<SimulationRun | null>(null);
  const [demoScenarioId, setDemoScenarioId] = useState("INC-001");
  const [demoCatalogLoading, setDemoCatalogLoading] = useState(false);
  const [demoCatalogError, setDemoCatalogError] = useState("");
  const [demoEvidenceLoading, setDemoEvidenceLoading] = useState(false);
  const [demoEvidenceError, setDemoEvidenceError] = useState("");
  const [demoManifest, setDemoManifest] = useState<EvidenceManifest | null>(null);
  const [demoHistory, setDemoHistory] = useState<ScenarioHistory | null>(null);
  const [demoInvestigationId, setDemoInvestigationId] = useState("");
  const [demoBusy, setDemoBusy] = useState(false);
  const [demoStreamState, setDemoStreamState] = useState<DemoStreamState>("idle");
  const [inspectedArtifact, setInspectedArtifact] = useState<ScenarioArtifact | null>(null);
  const [inspectingArtifactId, setInspectingArtifactId] = useState("");
  const demoRunLock = useRef(false);
  const demoIdempotencyKeys = useRef(new Map<string, string>());
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
        throw new ApiRequestError(detail?.detail ?? `Request failed (${response.status})`, response.status);
      }
      return response.json() as Promise<T>;
    },
    [headers],
  );

  const requestDemo = useCallback(
    async <T,>(path: string, init: RequestInit = {}): Promise<T> => {
      for (let attempt = 0; attempt < 3; attempt += 1) {
        const controller = new AbortController();
        const timeout = window.setTimeout(() => controller.abort(), 20_000);
        try {
          return await request<T>(path, { ...init, signal: controller.signal });
        } catch (reason) {
          const retryable = controller.signal.aborted
            || reason instanceof TypeError
            || (reason instanceof ApiRequestError && reason.status >= 500);
          if (!retryable || attempt === 2) {
            if (controller.signal.aborted) {
              throw new Error("Demo API request timed out after 20 seconds.");
            }
            throw reason;
          }
          await new Promise((resolve) => window.setTimeout(resolve, 500 * 2 ** attempt));
        } finally {
          window.clearTimeout(timeout);
        }
      }
      throw new Error("Demo API request could not be completed.");
    },
    [request],
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
    const timer = window.setInterval(() => void refresh(), 15000);
    return () => window.clearInterval(timer);
  }, [apiKey, organization, refresh]);

  useEffect(() => {
    const shouldLoadInvestigation =
      tab === "Investigations" ||
      (tab === "Demo Center" && Boolean(demoInvestigationId) && selectedId === demoInvestigationId);
    if (!shouldLoadInvestigation || !selectedId) {
      if (!selectedId) {
        setSelected(null);
        setEvents([]);
      }
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
    const timer = window.setInterval(() => void load(), tab === "Demo Center" ? 2500 : 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [demoInvestigationId, request, selectedId, tab]);

  useEffect(() => {
    if (tab !== "Incident Lab" && tab !== "Demo Center") return;
    let active = true;
    const loadScenarios = async () => {
      if (tab === "Demo Center") {
        setDemoCatalogLoading(true);
        setDemoCatalogError("");
      }
      try {
        const scenarioItems = await requestDemo<ScenarioSummary[]>("/api/v1/lab/scenarios");
        if (!active) return;
        setScenarios(scenarioItems);
        setSelectedScenarioId((current) => current || scenarioItems[0]?.scenario_id || "");
      } catch (reason) {
        if (active) {
          const message = reason instanceof Error ? reason.message : "Could not load synthetic scenarios.";
          setError(message);
          if (tab === "Demo Center") setDemoCatalogError(message);
        }
      } finally {
        if (active && tab === "Demo Center") setDemoCatalogLoading(false);
      }
    };
    const loadRuns = async () => {
      try {
        const runItems = await request<SimulationRunSummary[]>("/api/v1/lab/runs");
        if (!active) return;
        setSimulationRuns(runItems);
        setSelectedRunId((current) => current || runItems[0]?.run_id || "");
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "Could not load simulation history.");
      }
    };
    void loadScenarios();
    if (tab === "Incident Lab") {
      void loadRuns();
    }
    const timer = tab === "Incident Lab"
      ? window.setInterval(() => void loadRuns(), 10000)
      : undefined;
    return () => {
      active = false;
      if (timer !== undefined) window.clearInterval(timer);
    };
  }, [request, requestDemo, tab]);

  useEffect(() => {
    if (tab !== "Demo Center" || !demoScenarioId) return;
    let active = true;
    setDemoManifest(null);
    setDemoHistory(null);
    setDemoEvidenceLoading(true);
    setDemoEvidenceError("");
    const loadScenarioEvidence = async () => {
      try {
        const [manifest, history] = await Promise.all([
          requestDemo<EvidenceManifest>(`/api/v1/lab/scenarios/${demoScenarioId}/evidence`),
          requestDemo<ScenarioHistory>(`/api/v1/lab/scenarios/${demoScenarioId}/history`),
        ]);
        if (active) {
          setDemoManifest(manifest);
          setDemoHistory(history);
        }
      } catch (reason) {
        if (active) {
          const message = reason instanceof Error ? reason.message : "Could not load scenario evidence.";
          setError(message);
          setDemoEvidenceError(message);
        }
      } finally {
        if (active) setDemoEvidenceLoading(false);
      }
    };
    void loadScenarioEvidence();
    return () => {
      active = false;
    };
  }, [demoScenarioId, requestDemo, tab]);

  useEffect(() => {
    if (tab !== "Demo Center" || !demoInvestigationId) return;
    let active = true;
    let controller: AbortController | null = null;
    let retryTimer: number | undefined;
    let retryCount = 0;
    const connect = async () => {
      controller = new AbortController();
      const timeout = window.setTimeout(() => controller?.abort(), 125_000);
      try {
        setDemoStreamState(retryCount > 0 ? "retrying" : "connecting");
        const streamHeaders = new Headers(headers);
        const response = await fetch(
          `${API_BASE}/api/v1/investigations/${demoInvestigationId}/events/stream`,
          { headers: streamHeaders, signal: controller.signal },
        );
        if (!response.ok) throw new Error(`Event stream failed (${response.status}).`);
        if (!response.body) throw new Error("Event streaming is not supported by this response.");
        setDemoStreamState("connected");
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let terminalEvent = false;
        while (active && !terminalEvent) {
          const result = await reader.read();
          if (result.done) break;
          buffer += decoder.decode(result.value, { stream: true });
          const blocks = buffer.split(/\r?\n\r?\n/);
          buffer = blocks.pop() ?? "";
          for (const block of blocks) {
            const eventName = block.match(/^event:\s*(.+)$/m)?.[1]?.trim();
            const data = block
              .split(/\r?\n/)
              .filter((line) => line.startsWith("data:"))
              .map((line) => line.slice(5).trim())
              .join("\n");
            if (eventName === "update" && data) {
              const incoming = JSON.parse(data) as EventItem;
              setEvents((current) => current.some((item) => item.id === incoming.id)
                ? current
                : [...current, incoming].sort((left, right) => left.id - right.id));
            } else if (eventName === "close") {
              setDemoStreamState("closed");
              terminalEvent = true;
              break;
            } else if (eventName === "timeout") {
              setDemoStreamState("polling");
              terminalEvent = true;
              break;
            }
          }
        }
        if (!terminalEvent && active) throw new Error("Event stream ended unexpectedly.");
      } catch {
        if (!active) return;
        if (retryCount < 3) {
          retryCount += 1;
          setDemoStreamState("retrying");
          retryTimer = window.setTimeout(() => void connect(), Math.min(1000 * 2 ** retryCount, 5000));
        } else {
          setDemoStreamState("polling");
        }
      } finally {
        window.clearTimeout(timeout);
      }
    };
    void connect();
    return () => {
      active = false;
      controller?.abort();
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
    };
  }, [demoInvestigationId, headers, tab]);

  useEffect(() => {
    if (tab !== "Incident Lab" || !selectedRunId) {
      if (!selectedRunId) setActiveRun(null);
      return;
    }
    let active = true;
    const loadRun = async () => {
      try {
        const current = await request<SimulationRun>(`/api/v1/lab/runs/${selectedRunId}`);
        if (active) setActiveRun(current);
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "Could not load simulation run.");
      }
    };
    void loadRun();
    const timer = window.setInterval(() => void loadRun(), 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [request, selectedRunId, tab]);

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

  async function startSimulation() {
    if (!selectedScenarioId) return;
    setBusy(true);
    setError("");
    try {
      const run = await request<SimulationRun>("/api/v1/lab/runs", {
        method: "POST",
        body: JSON.stringify({ scenario_id: selectedScenarioId }),
      });
      setSelectedRunId(run.run_id);
      setActiveRun(run);
      setSimulationRuns((current) => [{
        run_id: run.run_id,
        scenario_id: run.scenario_id,
        seed: run.seed,
        status: run.status,
        elapsed_seconds: run.elapsed_seconds,
        duration_seconds: run.duration_seconds,
        synthetic: run.synthetic,
        window_complete: run.window_complete,
      }, ...current]);
      setNotice(`${run.scenario_id} synthetic simulation started with seed ${run.seed}.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not start the simulation.");
    } finally {
      setBusy(false);
    }
  }

  async function stopSimulation() {
    if (!activeRun) return;
    try {
      const stopped = await request<SimulationRun>(`/api/v1/lab/runs/${activeRun.run_id}/stop`, { method: "POST" });
      setActiveRun(stopped);
      setSimulationRuns((current) => current.map((item) => item.run_id === stopped.run_id ? { ...item, status: stopped.status, elapsed_seconds: stopped.elapsed_seconds } : item));
      setNotice("Synthetic simulation stopped.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not stop the simulation.");
    }
  }

  async function replaySimulation() {
    if (!activeRun) return;
    try {
      const replay = await request<SimulationRun>(`/api/v1/lab/runs/${activeRun.run_id}/replay`, { method: "POST" });
      setSelectedRunId(replay.run_id);
      setActiveRun(replay);
      setSimulationRuns((current) => [{
        run_id: replay.run_id,
        scenario_id: replay.scenario_id,
        seed: replay.seed,
        status: replay.status,
        elapsed_seconds: replay.elapsed_seconds,
        duration_seconds: replay.duration_seconds,
        synthetic: replay.synthetic,
        window_complete: replay.window_complete,
      }, ...current]);
      setNotice(`Replaying ${replay.scenario_id} with the same deterministic seed.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not replay the simulation.");
    }
  }

  async function resetSimulation() {
    if (!activeRun) return;
    try {
      await request(`/api/v1/lab/runs/${activeRun.run_id}/reset`, { method: "POST" });
      setSimulationRuns((current) => current.filter((item) => item.run_id !== activeRun.run_id));
      setSelectedRunId("");
      setActiveRun(null);
      setNotice("Synthetic simulation state reset.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not reset the simulation.");
    }
  }

  async function investigateSimulation() {
    if (!activeRun) return;
    setBusy(true);
    try {
      const created = await request<Investigation>("/api/v1/investigations", {
        method: "POST",
        body: JSON.stringify({
          request: `Investigate synthetic Nexora incident ${activeRun.scenario_id}: correlate the generated logs, metrics, deployments, and service observations. Cite evidence and report uncertainty.`,
          simulation_scenario_id: activeRun.scenario_id,
        }),
      });
      setSelectedId(created.id);
      setTab("Investigations");
      setNotice(`Investigation started for synthetic ${activeRun.scenario_id}.`);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not launch the investigation.");
    } finally {
      setBusy(false);
    }
  }

  function selectDemoScenario(scenarioId: string) {
    setDemoScenarioId(scenarioId);
    setDemoManifest(null);
    setDemoHistory(null);
    setDemoInvestigationId("");
    setEvents([]);
    setDemoStreamState("idle");
    setInspectedArtifact(null);
    setInspectingArtifactId("");
  }

  async function runDemoInvestigation() {
    if (demoRunLock.current) return;
    const scenario = scenarios.find((item) => item.scenario_id === demoScenarioId);
    if (!scenario) {
      setError("The selected synthetic scenario is not available.");
      return;
    }

    demoRunLock.current = true;
    setDemoBusy(true);
    setError("");
    const storageKey = demoKeyStorageKey(organization, demoScenarioId);
    let idempotencyKey = demoIdempotencyKeys.current.get(storageKey)
      ?? localStorage.getItem(storageKey)
      ?? undefined;
    if (!idempotencyKey) {
      idempotencyKey = crypto.randomUUID();
      localStorage.setItem(storageKey, idempotencyKey);
    }
    demoIdempotencyKeys.current.set(storageKey, idempotencyKey);
    try {
      const manifest = await requestDemo<EvidenceManifest>(
        `/api/v1/lab/scenarios/${demoScenarioId}/evidence`,
      );
      setDemoManifest(manifest);
      if (!manifest.available || !manifest.sources.some((source) => source.available)) {
        throw new Error("Synthetic evidence is unavailable for this scenario; investigation was not started.");
      }

      const published = await requestDemo<{ document_count: number; chunk_count: number }>(
        `/api/v1/lab/scenarios/${demoScenarioId}/publish`,
        { method: "POST" },
      );
      if (published.document_count < 1 || published.chunk_count < 1) {
        throw new Error("No indexed evidence is available for this scenario; investigation was not started.");
      }

      const created = await requestDemo<Investigation>("/api/v1/investigations", {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: JSON.stringify({
          request: (
            `Investigate synthetic Nexora incident ${scenario.scenario_id}: ${scenario.title}. ` +
            "Correlate available logs, metrics, deployment records, and service observations; cite evidence and state uncertainty."
          ),
          simulation_scenario_id: scenario.scenario_id,
        }),
      });
      setDemoInvestigationId(created.id);
      setSelectedId(created.id);
      setSelected(created);
      setEvents([]);
      setDemoStreamState("connecting");
      setNotice(`Demo investigation loaded for synthetic ${scenario.scenario_id}.`);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not start the demo investigation.");
    } finally {
      demoRunLock.current = false;
      setDemoBusy(false);
    }
  }

  function resetDemoView() {
    const storageKey = demoKeyStorageKey(organization, demoScenarioId);
    demoIdempotencyKeys.current.delete(storageKey);
    localStorage.removeItem(storageKey);
    setDemoInvestigationId("");
    setEvents([]);
    setSelected(null);
    setDemoStreamState("idle");
    setInspectedArtifact(null);
    setInspectingArtifactId("");
    setNotice("Demo view reset. Investigation history and indexed evidence are preserved.");
  }

  async function inspectDemoArtifact(artifactId: string) {
    if (inspectedArtifact?.artifact_id === artifactId) {
      setInspectedArtifact(null);
      return;
    }
    setInspectingArtifactId(artifactId);
    setError("");
    try {
      const artifact = await request<ScenarioArtifact>(
        `/api/v1/lab/scenarios/${demoScenarioId}/artifacts/${encodeURIComponent(artifactId)}`,
      );
      setInspectedArtifact(artifact);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not inspect the original source.");
    } finally {
      setInspectingArtifactId("");
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
  const activeDemoInvestigation =
    selected?.id === demoInvestigationId ? selected : null;

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
              <span className="nav-icon">{["⌂", "▶", "◎", "▤", "◉", "◇", "⚙"][index]}</span>
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

          {tab === "Demo Center" && (
            <DemoCenter
              scenarios={scenarios.filter((item) => ["INC-001", "INC-007", "INC-003"].includes(item.scenario_id))}
              scenarioId={demoScenarioId}
              catalogLoading={demoCatalogLoading}
              catalogError={demoCatalogError}
              evidenceLoading={demoEvidenceLoading}
              evidenceError={demoEvidenceError}
              manifest={demoManifest}
              history={demoHistory}
              investigation={activeDemoInvestigation}
              events={events}
              busy={demoBusy}
              streamState={demoStreamState}
              inspectedArtifact={inspectedArtifact}
              inspectingArtifactId={inspectingArtifactId}
              onSelectScenario={selectDemoScenario}
              onRun={() => void runDemoInvestigation()}
              onReset={resetDemoView}
              onInspect={(artifactId) => void inspectDemoArtifact(artifactId)}
            />
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

          {tab === "Incident Lab" && (
            <IncidentLab
              scenarios={scenarios}
              selectedScenarioId={selectedScenarioId}
              onSelectScenario={setSelectedScenarioId}
              onStart={() => void startSimulation()}
              runs={simulationRuns}
              selectedRunId={selectedRunId}
              onSelectRun={setSelectedRunId}
              run={activeRun}
              busy={busy}
              onStop={() => void stopSimulation()}
              onReplay={() => void replaySimulation()}
              onReset={() => void resetSimulation()}
              onInvestigate={() => void investigateSimulation()}
            />
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
              <div className="panel settings-panel"><label>API base URL<input value={API_BASE || window.location.origin} readOnly /></label><label>Organization ID<input value={organization} onChange={(event) => setOrganization(event.target.value)} /></label><label>API key<input type="password" autoComplete="new-password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="Required only when server authentication is enabled" /></label><div className="settings-note"><strong>Local demo safeguards</strong><p>External vector retrieval is disabled by default. Scenario investigations use synthetic fixtures; unconfigured live integrations remain disabled. No remediation is performed from this interface.</p></div><button className="button primary" onClick={() => setNotice("Settings saved in this browser.")}>Save settings</button></div>
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

function DemoCenter({
  scenarios,
  scenarioId,
  catalogLoading,
  catalogError,
  evidenceLoading,
  evidenceError,
  manifest,
  history,
  investigation,
  events,
  busy,
  streamState,
  inspectedArtifact,
  inspectingArtifactId,
  onSelectScenario,
  onRun,
  onReset,
  onInspect,
}: {
  scenarios: ScenarioSummary[];
  scenarioId: string;
  catalogLoading: boolean;
  catalogError: string;
  evidenceLoading: boolean;
  evidenceError: string;
  manifest: EvidenceManifest | null;
  history: ScenarioHistory | null;
  investigation: Investigation | null;
  events: EventItem[];
  busy: boolean;
  streamState: DemoStreamState;
  inspectedArtifact: ScenarioArtifact | null;
  inspectingArtifactId: string;
  onSelectScenario: (scenarioId: string) => void;
  onRun: () => void;
  onReset: () => void;
  onInspect: (artifactId: string) => void;
}) {
  const scenario = scenarios.find((item) => item.scenario_id === scenarioId);
  const eventTypes = new Set(events.map((item) => item.event_type));
  const stageDefinitions = [
    {
      title: "Request understanding",
      complete: eventTypes.has("started"),
      detail: "Workflow start persisted; there is no separate request-parsing node.",
    },
    { title: "Investigation planning", complete: eventTypes.has("intake"), detail: "Plan persisted by the intake node." },
    { title: "Evidence retrieval", complete: eventTypes.has("tools"), detail: "Retrieval and read-only source checks completed." },
    { title: "Hypothesis generation", complete: eventTypes.has("analysis"), detail: "Analysis node generated evidence-linked hypotheses." },
    { title: "Evidence verification", complete: eventTypes.has("verification"), detail: "Finding citations checked against retrieved evidence." },
    { title: "Report generation", complete: eventTypes.has("report"), detail: "Report persisted by the report node." },
  ];
  let activeStage = 0;
  if (eventTypes.has("started") && !eventTypes.has("intake")) activeStage = 1;
  else if (eventTypes.has("intake") && !eventTypes.has("tools")) activeStage = 2;
  else if (eventTypes.has("tools") && !eventTypes.has("analysis")) activeStage = 3;
  else if (eventTypes.has("analysis") && !eventTypes.has("verification")) activeStage = 4;
  else if (eventTypes.has("verification") && !eventTypes.has("report")) activeStage = 5;
  const failedEvent = events.find((item) => item.event_type === "failed");
  const failedNode = failedEvent?.data.failed_stage;
  const failedStage = failedNode === "intake" ? 1
    : failedNode === "retrieval" || failedNode === "tools" ? 2
      : failedNode === "analysis" ? 3
        : failedNode === "verification" ? 4
          : failedNode === "report" ? 5
            : -1;
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">GUIDED TECHNICAL WALKTHROUGH · SYNTHETIC DATA</p>
          <h1>Demo Center</h1>
          <p className="subheading">Run a traceable investigation against a deterministic incident in under five minutes.</p>
        </div>
        <span className="tag amber">SYNTHETIC ONLY</span>
      </div>
      <div className="demo-scenario-grid">
        {scenarios.length === 0 ? (
          <div className="panel demo-empty">
            {catalogLoading ? <><span className="spinner" /> Loading demo scenarios…</> : catalogError || "No curated demo scenarios are available."}
          </div>
        ) : scenarios.map((item) => (
          <button
            className={`panel demo-scenario-card ${item.scenario_id === scenarioId ? "selected" : ""}`}
            key={item.scenario_id}
            onClick={() => onSelectScenario(item.scenario_id)}
            aria-pressed={item.scenario_id === scenarioId}
          >
            <div className="demo-card-meta">
              <span className="tag blue">{item.scenario_id}</span>
              <span className={`tag ${item.severity === "critical" || item.severity === "error" ? "amber" : "muted"}`}>
                {item.severity} max signal
              </span>
            </div>
            <strong>{item.title}</strong>
            <span className="demo-card-description">{item.description}</span>
            <span className="demo-card-services">{item.affected_services.join(" · ")}</span>
          </button>
        ))}
      </div>

      <div className="demo-workspace">
        <section className="panel demo-brief">
          <div className="panel-heading">
            <div><h2>{scenario?.title ?? "Scenario details"}</h2><p className="muted-copy">{scenario?.scenario_id} · {scenario?.difficulty} · Synthetic fixture</p></div>
            <span className={`tag ${scenario?.severity === "critical" || scenario?.severity === "error" ? "amber" : "blue"}`}>
              {scenario?.severity ?? "—"}
            </span>
          </div>
          <div className="demo-brief-body">
            {!scenario ? <div className="loading-state"><span className="spinner" /> Loading scenario definition…</div> : <>
              <p>{scenario.description}</p>
              <h3>Affected services</h3>
              <div className="lab-tags">{scenario.affected_services.map((service) => <span className="tag muted" key={service}>{service}</span>)}</div>
            </>}
            <h3>Available evidence</h3>
            {!manifest && evidenceLoading ? <div className="loading-state"><span className="spinner" /> Checking fixture availability…</div>
              : !manifest ? <div className="empty-inline">{evidenceError || "Evidence availability has not been checked."}</div> : (
              <div className="demo-source-list">
                {manifest.sources.map((source) => (
                  <span className={`demo-source ${source.available ? "available" : "unavailable"}`} key={source.artifact_id}>
                    <i />{source.artifact_id.replaceAll("-", " ")} <small>{source.source_type}</small>
                  </span>
                ))}
              </div>
            )}
            {manifest && !manifest.available && <div className="alert error">One or more fixture sources are unavailable.</div>}
            <div className="demo-actions">
              <button className="button primary" onClick={onRun} disabled={busy || !scenario || evidenceLoading || !manifest?.available}>
                {busy ? "Preparing evidence…" : "▶ Run Investigation"}
              </button>
              <button className="button" onClick={onReset} disabled={busy}>Reset demo</button>
            </div>
            <p className="fine-print">Reset clears this view and permits a fresh run; it does not delete investigation history or indexed evidence.</p>
          </div>
        </section>

        <div className="demo-results">
          <section className="panel demo-progress">
            <div className="panel-heading">
              <div><h2>Investigation progress</h2><p className="muted-copy">
                {investigation ? `ID ${investigation.id.slice(0, 8).toUpperCase()}` : "Start an investigation to see backend execution events."}
              </p></div>
              {investigation && <StatusPill status={investigation.status} />}
            </div>
            {investigation && (
              <div className={`demo-stream-status ${streamState}`}>
                <i /> {streamState === "connected" ? "Live event stream connected" : streamState === "retrying" ? "Reconnecting to event stream" : streamState === "polling" ? "Live stream unavailable; polling persisted events" : streamState === "closed" ? "Workflow event stream closed" : "Connecting to persisted workflow events"}
              </div>
            )}
            <ol className="demo-stage-list">
              {stageDefinitions.map((stage, index) => {
                const state = stage.complete ? "completed"
                  : failedEvent && failedStage === index ? "failed"
                    : investigation?.status === "running" && activeStage === index ? "running"
                      : "waiting";
                return (
                  <li className={`demo-stage ${state}`} key={stage.title}>
                    <span className="demo-stage-marker">{state === "completed" ? "✓" : state === "failed" ? "!" : index + 1}</span>
                    <div><strong>{stage.title}</strong><small>{state === "completed" ? stage.detail : state === "failed" ? "Failed in the backend node; see event details" : state === "running" ? "In progress" : "Waiting"}</small></div>
                    <span className="tag muted">{state}</span>
                  </li>
                );
              })}
            </ol>
            {failedEvent && <div className="alert error demo-failure"><strong>Workflow failed</strong><span>{failedEvent.message}</span></div>}
            {!investigation && <div className="empty-inline">No demo investigation is running. Select a scenario and run it to start the real workflow.</div>}
            {investigation && events.length > 0 && (
              <div className="demo-event-feed">
                <h3>Backend event log</h3>
                {events.map((item) => (
                  <article className={`demo-event ${item.event_type === "failed" ? "failed" : ""}`} key={item.id}>
                    <span className="tag blue">{item.event_type.replaceAll("_", " ")}</span>
                    <time>{new Date(item.created_at).toLocaleTimeString()}</time>
                    <p>{item.message}</p>
                  </article>
                ))}
              </div>
            )}
            {investigation && !investigation.report && investigation.status !== "failed" && (
              <div className="loading-state"><span className="spinner" /> Workflow is running; the report will appear when the backend finishes.</div>
            )}
          </section>

          {investigation?.report && scenario && (
            <DemoReport
              scenario={scenario}
              manifest={manifest}
              history={history}
              investigation={investigation}
              inspectedArtifact={inspectedArtifact}
              inspectingArtifactId={inspectingArtifactId}
              onInspect={onInspect}
            />
          )}
        </div>
      </div>
    </>
  );
}

function DemoReport({
  scenario,
  manifest,
  history,
  investigation,
  inspectedArtifact,
  inspectingArtifactId,
  onInspect,
}: {
  scenario: ScenarioSummary;
  manifest: EvidenceManifest | null;
  history: ScenarioHistory | null;
  investigation: Investigation;
  inspectedArtifact: ScenarioArtifact | null;
  inspectingArtifactId: string;
  onInspect: (artifactId: string) => void;
}) {
  const report = investigation.report;
  if (!report) return null;
  const events = history?.events.slice().sort(
    (left, right) => left.timestamp.localeCompare(right.timestamp),
  ) ?? [];
  const evidenceById = new Map(report.evidence.map((item) => [item.evidence_id, item]));
  const approvalStatus = investigation.approvals.length === 0
    ? "No approval request recorded"
    : investigation.approvals.map((approval) => approval.status.replaceAll("_", " ")).join(", ");

  return (
    <section className="panel demo-report">
      <div className="panel-heading">
        <div><p className="eyebrow">EVIDENCE-BACKED OUTPUT</p><h2>Investigation report</h2></div>
        <span className="tag green">WORKFLOW {investigation.status}</span>
      </div>
      <div className="demo-report-body">
        <section className="demo-report-section">
          <h3>Executive summary</h3>
          <p className="report-summary">{report.summary}</p>
          <div className="demo-report-facts">
            <div><small>INCIDENT SEVERITY</small><strong>{scenario.severity} <span>(maximum configured signal)</span></strong></div>
            <div><small>APPROVAL STATUS</small><strong>{approvalStatus}</strong></div>
            <div><small>CONFIDENCE</small><strong>Not numerically quantified by the workflow</strong></div>
          </div>
          <h4>Affected services</h4>
          <div className="lab-tags">{scenario.affected_services.map((service) => <span className="tag muted" key={service}>{service}</span>)}</div>
        </section>

        <section className="demo-report-section">
          <h3>Evidence timeline</h3>
          <p className="muted-copy">Ordered synthetic source events for {scenario.scenario_id}; each row cites its source event identifier.</p>
          {events.length === 0 ? <div className="empty-inline">No source timeline is available.</div> : (
            <ol className="demo-timeline">
              {events.map((item) => (
                <li key={item.event_id}>
                  <time>{new Date(item.timestamp).toLocaleString()}</time>
                  <span className={`tag ${item.severity === "critical" || item.severity === "error" ? "amber" : "muted"}`}>{item.severity}</span>
                  <strong>{item.service_id}</strong>
                  <p>{item.message}</p>
                  <div className="citation-row"><code>{item.event_id}</code>{item.correlation_id && <code>{item.correlation_id}</code>}</div>
                </li>
              ))}
            </ol>
          )}
        </section>

        <section className="demo-report-section">
          <h3>Root-cause hypothesis</h3>
          {report.hypotheses.length === 0 ? <p className="muted-copy">The workflow returned no root-cause hypothesis.</p> : (
            <div className="hypothesis-card">
              <span className="tag amber">UNCONFIRMED · {report.hypotheses[0].classification}</span>
              <p>{report.hypotheses[0].statement}</p>
              <small>{report.hypotheses[0].rationale}</small>
              <CitationEvidence references={report.hypotheses[0].evidence_refs.map((reference) => reference.evidence_id)} evidenceById={evidenceById} />
            </div>
          )}
          <h4>Alternative hypotheses</h4>
          {report.hypotheses.length > 1 ? report.hypotheses.slice(1).map((hypothesis) => (
            <div className="hypothesis-card" key={hypothesis.id}>
              <span className="tag amber">{hypothesis.classification}</span><p>{hypothesis.statement}</p><small>{hypothesis.rationale}</small>
              <CitationEvidence references={hypothesis.evidence_refs.map((reference) => reference.evidence_id)} evidenceById={evidenceById} />
            </div>
          )) : <p className="muted-copy">The workflow did not produce separate alternative hypotheses.</p>}
        </section>

        <section className="demo-report-section">
          <h3>Findings and supporting evidence</h3>
          {report.findings.length === 0 ? <p className="muted-copy">No findings were produced.</p> : report.findings.map((finding) => (
            <article className="finding-card" key={finding.id}>
              <span className={`tag ${finding.classification === "confirmed" ? "green" : "amber"}`}>{finding.classification}</span>
              <p>{finding.statement}</p>
              <CitationEvidence references={finding.evidence_refs.map((reference) => reference.evidence_id)} evidenceById={evidenceById} />
            </article>
          ))}
          <h4>Contradictory evidence</h4>
          {report.conflicts.length === 0 ? <p className="muted-copy">No explicit contradiction was identified in retrieved evidence.</p> : report.conflicts.map((conflict, index) => (
            <article className="finding-card conflict-card" key={`${index}-${conflict.evidence_refs.map((reference) => reference.evidence_id).join(":")}`}>
              <span className="tag amber">CONTRADICTORY</span><p>{conflict.description}</p>
              <CitationEvidence references={conflict.evidence_refs.map((reference) => reference.evidence_id)} evidenceById={evidenceById} />
            </article>
          ))}
        </section>

        <section className="demo-report-section">
          <h3>Evidence explorer</h3>
          <DemoEvidenceList
            evidence={report.evidence}
            manifest={manifest}
            scenarioId={scenario.scenario_id}
            inspectedArtifact={inspectedArtifact}
            inspectingArtifactId={inspectingArtifactId}
            onInspect={onInspect}
          />
        </section>

        <section className="demo-report-section">
          <h3>Corrective recommendations</h3>
          {report.recommended_actions.length === 0 ? <p className="muted-copy">No recommendations were returned.</p> : (
            <ul className="action-list">{report.recommended_actions.map((item) => <li key={item}>{item}</li>)}</ul>
          )}
          <h4>Confidence and uncertainty</h4>
          <p className="muted-copy">No numeric confidence score is produced. Review the classifications, cited evidence, limitations, and unresolved questions before drawing conclusions.</p>
          <ul className="limitation-list">
            {report.unresolved_questions.map((item) => <li key={item.question}><strong>{item.question}</strong> — {item.reason}</li>)}
            {report.limitations.map((item) => <li key={item}>{item}</li>)}
          </ul>
        </section>
      </div>
    </section>
  );
}

function CitationEvidence({
  references,
  evidenceById,
}: {
  references: string[];
  evidenceById: Map<string, Evidence>;
}) {
  return (
    <div className="citation-row">
      {references.length === 0 ? <span className="muted-copy">No evidence citation supplied.</span> : references.map((id) => (
        <code key={id} title={evidenceById.has(id) ? "Citation exists in this report's evidence set" : "Citation is not present in the report evidence set"}>
          {id}{evidenceById.has(id) ? "" : " · unverified"}
        </code>
      ))}
    </div>
  );
}

function DemoEvidenceList({
  evidence,
  manifest,
  scenarioId,
  inspectedArtifact,
  inspectingArtifactId,
  onInspect,
}: {
  evidence: Evidence[];
  manifest: EvidenceManifest | null;
  scenarioId: string;
  inspectedArtifact: ScenarioArtifact | null;
  inspectingArtifactId: string;
  onInspect: (artifactId: string) => void;
}) {
  if (evidence.length === 0) {
    return <div className="empty-inline">The workflow returned no retrieved evidence. The report remains limited and no cause is inferred.</div>;
  }
  return (
    <div className="evidence-list">
      {evidence.map((item) => {
        const source = String(item.metadata.source ?? item.source_id);
        const sourceEntry = manifest?.sources.find((entry) => entry.source === source);
        const scenarioCorrelation = item.metadata.scenario_id;
        const eventCorrelation = typeof item.metadata.correlation_id === "string"
          ? item.metadata.correlation_id
          : item.excerpt.match(/correlation_id\s*[=:]\s*["']?([^"'\s,|}]+)/i)?.[1];
        const sourceTimestamp = item.excerpt.match(
          /\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?/,
        )?.[0];
        const isInspected = inspectedArtifact?.artifact_id === sourceEntry?.artifact_id;
        return (
          <article className="evidence-card demo-evidence-card" key={item.evidence_id}>
            <div className="evidence-meta">
              <span className="source-glyph">▤</span>
              <strong>{source}</strong>
              <span className="tag blue">{String(item.metadata.source_type ?? item.source_id)}</span>
              <code>{item.evidence_id}</code>
            </div>
            <blockquote>{item.excerpt}</blockquote>
            <div className="demo-evidence-details">
              <span>{sourceTimestamp ? `Source time ${new Date(sourceTimestamp).toLocaleString()}` : `Retrieved ${new Date(item.retrieved_at).toLocaleString()}`}</span>
              <span>Incident {String(scenarioCorrelation ?? scenarioId)}</span>
              {eventCorrelation
                ? <span>Correlation {eventCorrelation}</span>
                : <span>Event correlation not present in excerpt</span>}
              <code>doc {item.document_id} · chunk {item.chunk_id}</code>
            </div>
            {sourceEntry && (
              <button className="text-button demo-inspect-button" onClick={() => onInspect(sourceEntry.artifact_id)} disabled={inspectingArtifactId === sourceEntry.artifact_id}>
                {inspectingArtifactId === sourceEntry.artifact_id ? "Loading source…" : isInspected ? "Hide original source ↑" : "Inspect original source →"}
              </button>
            )}
            {isInspected && inspectedArtifact && (
              <div className="demo-source-inspector">
                <div><strong>{inspectedArtifact.source}</strong><span className="tag green">SYNTHETIC SOURCE</span></div>
                <pre>{inspectedArtifact.content}</pre>
              </div>
            )}
          </article>
        );
      })}
    </div>
  );
}

function IncidentLab({
  scenarios,
  selectedScenarioId,
  onSelectScenario,
  onStart,
  runs,
  selectedRunId,
  onSelectRun,
  run,
  busy,
  onStop,
  onReplay,
  onReset,
  onInvestigate,
}: {
  scenarios: ScenarioSummary[];
  selectedScenarioId: string;
  onSelectScenario: (scenarioId: string) => void;
  onStart: () => void;
  runs: SimulationRunSummary[];
  selectedRunId: string;
  onSelectRun: (runId: string) => void;
  run: SimulationRun | null;
  busy: boolean;
  onStop: () => void;
  onReplay: () => void;
  onReset: () => void;
  onInvestigate: () => void;
}) {
  const scenario = scenarios.find((item) => item.scenario_id === selectedScenarioId);
  return (
    <>
      <div className="page-heading">
        <div><p className="eyebrow">NEXORA SYSTEMS · LOCAL MOCK ENVIRONMENT</p><h1>Incident Lab</h1><p className="subheading">Replay deterministic synthetic incidents and investigate generated operational evidence.</p></div>
        <span className="tag amber">SYNTHETIC ONLY</span>
      </div>
      <div className="lab-layout">
        <div className="panel lab-scenario-panel">
          <div className="panel-heading"><h2>Scenario catalog</h2><span>{scenarios.length} scenarios</span></div>
          <label className="lab-field">Select a scenario
            <select value={selectedScenarioId} onChange={(event) => onSelectScenario(event.target.value)} disabled={scenarios.length === 0}>
              {scenarios.map((item) => <option value={item.scenario_id} key={item.scenario_id}>{item.scenario_id} · {item.title}</option>)}
            </select>
          </label>
          {scenario ? <div className="lab-scenario-detail">
            <div className="lab-tags"><span className={`tag ${scenario.difficulty === "hard" ? "amber" : "blue"}`}>{scenario.difficulty}</span><span className="tag green">SYNTHETIC</span></div>
            <h3>{scenario.title}</h3>
            <p>{scenario.description}</p>
            <strong>AFFECTED SERVICES</strong>
            <div className="lab-tags">{scenario.affected_services.map((service) => <span className="tag muted" key={service}>{service}</span>)}</div>
          </div> : <div className="empty-inline">Loading synthetic scenarios…</div>}
          <button className="button primary lab-start" onClick={onStart} disabled={busy || !scenario}>▶ Start simulation</button>
          <div className="lab-history">
            <strong>RUN HISTORY</strong>
            {runs.length === 0 ? <p className="muted-copy">No simulation runs in this session.</p> : runs.map((item) =>
              <button className={`lab-run-option ${selectedRunId === item.run_id ? "selected" : ""}`} key={item.run_id} onClick={() => onSelectRun(item.run_id)}>
                <span>{item.scenario_id} · seed {item.seed}</span><span className={`tag ${item.status === "running" ? "blue" : "muted"}`}>{item.status}</span>
              </button>,
            )}
          </div>
        </div>
        <div className="lab-console">
          {!run ? <div className="panel"><EmptyState title="Choose a scenario to begin" body="Start a local synthetic run to reveal its timeline, metrics, and service observations." /></div> : <>
            <div className="panel lab-run-panel">
              <div className="panel-heading"><div><h2>{run.scenario_id} simulation</h2><p className="muted-copy">Seed {run.seed} · {run.elapsed_seconds}s elapsed of {run.duration_seconds}s</p></div><span className={`status-pill ${run.status}`}><i />{run.status}</span></div>
              <div className="lab-controls">
                <button className="button quiet" onClick={onStop} disabled={run.status === "stopped" || run.window_complete}>■ Stop</button>
                <button className="button" onClick={onReplay}>↻ Replay same seed</button>
                <button className="button" onClick={onReset}>Reset</button>
                <button className="button primary" onClick={onInvestigate} disabled={busy}>Investigate in EnterpriseIQ →</button>
              </div>
            </div>
            <div className="panel lab-health-panel">
              <div className="panel-heading"><h2>Service observations</h2><span className="tag muted">SIMULATED SIGNALS</span></div>
              <div className="lab-health-grid">{run.service_health.map((service) =>
                <div className="lab-health-card" key={service.service_id}><span>{service.service_name}</span><strong>{service.observed_status.replaceAll("_", " ")}</strong></div>,
              )}</div>
              <p className="fine-print">Derived from generated event severity; these are not live service health checks.</p>
            </div>
            <div className="lab-data-grid">
              <div className="panel lab-timeline-panel">
                <div className="panel-heading"><h2>Live generated events</h2><span>{run.events.length}</span></div>
                <div className="lab-event-list">{run.events.length === 0 ? <div className="empty-inline">Events appear as the simulation advances.</div> : run.events.slice().reverse().map((item) =>
                  <article className="lab-event" key={item.event_id}>
                    <div className="lab-event-meta"><span className={`tag ${item.severity === "error" || item.severity === "critical" ? "amber" : "muted"}`}>{item.severity}</span><span className="tag blue">{item.service_id}</span><time>{new Date(item.timestamp).toLocaleTimeString()}</time></div>
                    <p>{item.message}</p>
                    {item.correlation_id && <code>{item.correlation_id}</code>}
                  </article>,
                )}</div>
              </div>
              <div className="panel lab-metric-panel">
                <div className="panel-heading"><h2>Monitoring metrics</h2><span>{run.metrics.length} samples</span></div>
                <div className="lab-metric-list">{run.metrics.slice(-18).map((metric) =>
                  <div className="lab-metric" key={metric.sample_id}><div><strong>{metric.metric_name}</strong><small>{metric.service_id} · {new Date(metric.timestamp).toLocaleTimeString()}</small></div><span>{Number(metric.value.toFixed(2))} {metric.unit}</span></div>,
                )}</div>
              </div>
            </div>
          </>}
        </div>
      </div>
    </>
  );
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
