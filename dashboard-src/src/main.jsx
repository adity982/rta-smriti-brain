import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowLeft,
  BrainCircuit,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Clipboard,
  Code2,
  Command,
  Crosshair,
  Database,
  Download,
  Eye,
  FileCode2,
  FileText,
  Files,
  Folder,
  FolderTree,
  GitBranch,
  GitPullRequest,
  HardDrive,
  Layers3,
  Map as MapIcon,
  Maximize2,
  MemoryStick,
  Network,
  PanelRightOpen,
  Plus,
  RefreshCw,
  RotateCcw,
  Rocket,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Table2,
  Zap,
} from "lucide-react";
import "./styles.css";

const DEFAULT_TASK = "Prepare this project for a focused coding task";
const LEGACY_RECEIPT_STORAGE_KEY = "rta-smriti.context-pack-receipts.v1";
const CANVAS_STORAGE_KEY = "rta-smriti.canvas-layout.v1";
const AGENT_STORAGE_KEY = "rta-smriti.target-agent.v1";
const API_TOKEN_SESSION_KEY = "rta-smriti.api-token.v1";

const targetAgents = [
  { value: "universal", label: "Universal / Any Agent" },
  { value: "codex", label: "OpenAI Codex" },
  { value: "claude-code", label: "Claude Code" },
  { value: "cursor", label: "Cursor" },
  { value: "github-copilot", label: "GitHub Copilot" },
  { value: "gemini-cli", label: "Gemini CLI" },
  { value: "windsurf", label: "Windsurf" },
  { value: "cline", label: "Cline" },
  { value: "aider", label: "Aider" },
  { value: "opencode", label: "OpenCode" },
  { value: "continue", label: "Continue" },
  { value: "custom", label: "Custom Agent" },
];

const graphPalette = {
  file: "#38bdf8",
  memory: "#5eead4",
  docs: "#86efac",
  config: "#fbbf24",
  test: "#a78bfa",
  data: "#94a3b8",
  artifact: "#f472b6",
};

const allGraphTypes = Object.keys(graphPalette);
const graphModes = ["global", "local", "task"];
const graphHubs = [
  { id: "hub-files", key: "files", label: "Files", x: 50, y: 18, angle: -Math.PI / 2, color: "#38bdf8", icon: FileCode2 },
  { id: "hub-imports", key: "imports", label: "Imports", x: 69, y: 42, angle: -0.1, color: "#fbbf24", icon: GitBranch },
  { id: "hub-evidence", key: "evidence", label: "Evidence", x: 64, y: 73, angle: 0.9, color: "#60a5fa", icon: ShieldCheck },
  { id: "hub-memories", key: "memories", label: "Memories", x: 36, y: 73, angle: 2.25, color: "#a78bfa", icon: MemoryStick },
  { id: "hub-symbols", key: "symbols", label: "Symbols", x: 31, y: 42, angle: Math.PI + 0.1, color: "#86efac", icon: Code2 },
];

function safeNumber(value) {
  return Number(value || 0).toLocaleString();
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function displayPath(value) {
  return String(value || "...")
    .replace(/^[A-Za-z]:[\\/]Users[\\/][^\\/]+/i, "%USERPROFILE%")
    .replace(/^\/(?:Users|home)\/[^/]+/i, "$HOME")
    .replace(/^[/\\]{2}[^/\\]+[/\\][^/\\]+/, "<network-share>");
}

function shellQuote(value, shellKind) {
  const text = String(value ?? "");
  if (shellKind === "powershell") return `'${text.replaceAll("'", "''")}'`;
  return `'${text.replaceAll("'", `'"'"'`)}'`;
}

function shellPathArg(value, shellKind) {
  const text = String(value || "");
  if (shellKind === "powershell") {
    const portable = text.replace(/^[A-Za-z]:[\\/]Users[\\/][^\\/]+/i, "$env:USERPROFILE");
    if (portable.startsWith("$env:USERPROFILE")) return `"${portable.replaceAll('"', '`"')}"`;
    return shellQuote(portable, shellKind);
  }
  const portable = text.replace(/^\/(?:Users|home)\/[^/]+/i, "$HOME");
  if (portable.startsWith("$HOME")) return `"${portable.replaceAll('"', '\\"')}"`;
  return shellQuote(portable, shellKind);
}

function readApiToken() {
  try {
    const fragment = new URLSearchParams(window.location.hash.slice(1));
    const supplied = fragment.get("token");
    if (supplied) {
      sessionStorage.setItem(API_TOKEN_SESSION_KEY, supplied);
      window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
      return supplied;
    }
    return sessionStorage.getItem(API_TOKEN_SESSION_KEY) || "";
  } catch {
    return "";
  }
}

const API_TOKEN = readApiToken();

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", "X-Rta-Smriti-Token": API_TOKEN, ...(options.headers || {}) },
  });
  const payload = await response.json();
  if (!response.ok || payload.status === "error") {
    throw new Error(displayPath(payload.error?.message || `Request failed: ${path}`));
  }
  return payload;
}

function qs(params) {
  return new URLSearchParams(params).toString();
}

function readLocalJson(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key)) || fallback;
  } catch {
    return fallback;
  }
}

function writeLocalJson(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // The console remains fully usable when browser storage is unavailable.
  }
}

function readLocalString(key, fallback) {
  try {
    return localStorage.getItem(key) || fallback;
  } catch {
    return fallback;
  }
}

function writeLocalString(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // The selected handoff target remains available for the current session.
  }
}

function sourceType(node) {
  if (node.type === "memory") return "memory";
  if (node.type === "file") {
    const name = String(node.name || "").toLowerCase();
    if (/test|spec/.test(name)) return "test";
    if (/readme|\.md$|docs?[\\/]/.test(name)) return "docs";
    if (/json|ya?ml|toml|ini|config|env/.test(name)) return "config";
    return "file";
  }
  if (node.type === "symbol") return "docs";
  if (node.type === "import") return "config";
  return "data";
}

function taskWords(task) {
  return new Set(String(task || "").toLowerCase().match(/[a-z0-9_-]{3,}/g) || []);
}

function semanticHubKey(node) {
  if (node.type === "memory") return "memories";
  if (node.type === "symbol") return "symbols";
  if (node.type === "import") return "imports";
  return sourceType(node) === "file" ? "files" : "evidence";
}

function selectBalancedNodes(candidates, limit) {
  const caps = { files: 8, symbols: 8, imports: 8, memories: 6, evidence: 6 };
  const grouped = Object.fromEntries(graphHubs.map((hub) => [hub.key, []]));
  candidates.forEach((node) => grouped[semanticHubKey(node)]?.push(node));
  return graphHubs.flatMap((hub) => grouped[hub.key].slice(0, caps[hub.key])).slice(0, limit);
}

function buildGraph(project, graphData, memories, packText, options = {}) {
  const mode = options.mode || "global";
  const depth = Math.max(1, Math.min(4, Number(options.depth) || 2));
  const available = graphData?.nodes || [];
  const rawEdges = graphData?.edges || [];
  const byId = new Map(available.map((node) => [Number(node.id), node]));
  const adjacency = new Map(available.map((node) => [Number(node.id), new Set()]));
  rawEdges.forEach((edge) => {
    adjacency.get(Number(edge.from_id))?.add(Number(edge.to_id));
    adjacency.get(Number(edge.to_id))?.add(Number(edge.from_id));
  });
  const words = taskWords(options.task);
  const pack = String(packText || "").toLowerCase();
  const taskMatches = available.filter((node) => {
    const haystack = `${node.name || ""} ${node.type || ""}`.toLowerCase();
    return [...words].some((word) => haystack.includes(word)) || (node.name && pack.includes(String(node.name).toLowerCase()));
  });
  let candidates = available;
  if (mode === "task" && taskMatches.length) candidates = taskMatches;
  if (mode === "local" && available.length) {
    const start = Number(options.focalSourceId) || Number(rawEdges[0]?.from_id) || Number(available[0].id);
    const visited = new Set([start]);
    let frontier = [start];
    for (let level = 0; level < depth; level += 1) {
      const next = frontier.flatMap((id) => [...(adjacency.get(id) || [])]).filter((id) => !visited.has(id));
      next.forEach((id) => visited.add(id));
      frontier = next;
    }
    candidates = [...visited].map((id) => byId.get(id)).filter(Boolean);
  }
  const limit = mode === "global" ? 40 : mode === "task" ? 12 + depth * 4 : 10 + depth * 6;
  let orderedCandidates = candidates;
  if (mode === "global" && rawEdges.length) {
    const candidateIds = new Set(candidates.map((node) => Number(node.id)));
    const connectedIds = [];
    const seen = new Set();
    rawEdges.forEach((edge) => {
      [Number(edge.from_id), Number(edge.to_id)].forEach((id) => {
        if (candidateIds.has(id) && !seen.has(id)) {
          seen.add(id);
          connectedIds.push(id);
        }
      });
    });
    orderedCandidates = [
      ...connectedIds.map((id) => byId.get(id)).filter(Boolean),
      ...candidates.filter((node) => !seen.has(Number(node.id))),
    ];
  }
  const selected = selectBalancedNodes(orderedCandidates, limit);
  const selectedIds = new Set(selected.map((node) => Number(node.id)));
  const grouped = Object.fromEntries(graphHubs.map((hub) => [hub.key, []]));
  selected.forEach((node) => grouped[semanticHubKey(node)]?.push(node));
  const hubs = graphHubs
    .filter((hub) => grouped[hub.key].length)
    .map((hub) => ({ ...hub, count: grouped[hub.key].length }));
  const nodes = hubs.flatMap((hub) => grouped[hub.key].map((node, index, group) => {
    const slots = group.length;
    const angle = hub.angle + (index / Math.max(1, slots)) * Math.PI * 2;
    const radiusX = slots === 1 ? 6.2 : 6.7;
    const radiusY = slots === 1 ? 10 : 10.8;
    return {
      id: `g-${node.id}`,
      sourceId: Number(node.id),
      label: node.name.split(/[\\/]/).pop() || node.name,
      type: sourceType(node),
      meta: node.type,
      hubId: hub.id,
      color: hub.color,
      x: Math.max(2.2, Math.min(97.8, hub.x + Math.cos(angle) * radiusX)),
      y: Math.max(3.5, Math.min(96, hub.y + Math.sin(angle) * radiusY)),
      size: node.type === "file" ? 13 : 11,
    };
  }));
  const edges = rawEdges
    .filter((edge) => selectedIds.has(Number(edge.from_id)) && selectedIds.has(Number(edge.to_id)))
    .map((edge) => ({ id: `edge-${edge.id}`, source: `g-${edge.from_id}`, target: `g-${edge.to_id}`, label: edge.relation }));
  return {
    nodes,
    edges,
    hubs,
    core: {
      id: `project-${project?.project || "brain"}`,
      label: project?.project || "Project Brain",
      meta: `${selected.length} visible nodes`,
      x: 50,
      y: 49,
    },
  };
}

function deriveReferences(graph, node, memories) {
  if (!node) return [];
  const connected = graph.edges
    .filter((edge) => edge.source === node.id || edge.target === node.id)
    .map((edge) => {
      const otherId = edge.source === node.id ? edge.target : edge.source;
      const other = graph.nodes.find((candidate) => candidate.id === otherId);
      return other ? { id: edge.id, label: other.label, relation: edge.label, type: other.type, node: other } : null;
    })
    .filter(Boolean);
  const mentions = memories
    .filter((memory) => String(memory.text || "").toLowerCase().includes(String(node.label || "").toLowerCase()))
    .slice(0, 5)
    .map((memory) => ({ id: `memory-${memory.id}`, label: memory.type, relation: "mentions", type: "memory" }));
  return [...connected, ...mentions];
}

function downloadJson(filename, payload) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  window.setTimeout(() => {
    anchor.remove();
    URL.revokeObjectURL(url);
  }, 250);
}

function filterGraph(graph, query, types, semanticFocus = null) {
  const normalizedQuery = query.trim().toLowerCase();
  const activeTypes = new Set(types);
  const nodes = graph.nodes.filter((node) => {
    const matchesType = activeTypes.has(node.type);
    const matchesFocus = !semanticFocus || node.hubId === `hub-${semanticFocus}`;
    const haystack = `${node.label} ${node.meta} ${node.text || ""}`.toLowerCase();
    const matchesQuery = !normalizedQuery || haystack.includes(normalizedQuery);
    return matchesType && matchesFocus && matchesQuery;
  });
  const ids = new Set(nodes.map((node) => node.id));
  return {
    nodes,
    edges: graph.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target)),
    hubs: (graph.hubs || []).map((hub) => ({
      ...hub,
      count: nodes.filter((node) => node.hubId === hub.id).length,
    })).filter((hub) => hub.count),
    core: graph.core,
  };
}

function App() {
  const presentationMode = new URLSearchParams(window.location.search).get("presentation") === "1";
  const [health, setHealth] = useState(null);
  const [projects, setProjects] = useState([]);
  const [selectedProject, setSelectedProject] = useState(null);
  const [task, setTask] = useState(DEFAULT_TASK);
  const [packText, setPackText] = useState("");
  const [memories, setMemories] = useState([]);
  const [graphData, setGraphData] = useState({ nodes: [], edges: [] });
  const [freshness, setFreshness] = useState(null);
  const projectRequestRef = useRef(0);
  const fileRequestRef = useRef(0);
  const [publish, setPublish] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);
  const [message, setMessage] = useState("");
  const [loadError, setLoadError] = useState("");
  const [activeDrawer, setActiveDrawer] = useState("evidence");
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [searchOpen, setSearchOpen] = useState(false);
  const [projectsOpen, setProjectsOpen] = useState(false);
  const [nodeQuery, setNodeQuery] = useState("");
  const [typesOpen, setTypesOpen] = useState(false);
  const [activeTypes, setActiveTypes] = useState(allGraphTypes);
  const [commandOpen, setCommandOpen] = useState(false);
  const [stageExpanded, setStageExpanded] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isRefreshingIndex, setIsRefreshingIndex] = useState(false);
  const [viewMode, setViewMode] = useState("graph");
  const [semanticFocus, setSemanticFocus] = useState(null);
  const [navContext, setNavContext] = useState("graph");
  const [baseScope, setBaseScope] = useState({ table: "memory", kind: "" });
  const [fileTree, setFileTree] = useState({ entries: [], prefix: "", query: "", total_files: 0 });
  const [filePreview, setFilePreview] = useState(null);
  const [filesLoading, setFilesLoading] = useState(false);
  const [targetAgent, setTargetAgent] = useState(() => readLocalString(AGENT_STORAGE_KEY, "universal"));
  const [customAgent, setCustomAgent] = useState("");
  const [graphMode, setGraphMode] = useState("global");
  const [graphDepth, setGraphDepth] = useState(2);
  const [showLabels, setShowLabels] = useState(false);
  const [showEdges, setShowEdges] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [projectSettings, setProjectSettings] = useState(null);
  const [parserCapabilities, setParserCapabilities] = useState({});
  const [isSavingSettings, setIsSavingSettings] = useState(false);
  const [receipts, setReceipts] = useState([]);

  const selectedParams = useMemo(() => {
    if (!selectedProject) return null;
    return { db_path: selectedProject.db_path, project: selectedProject.project };
  }, [selectedProject]);

  const graphOptions = useMemo(() => ({ mode: graphMode, depth: graphDepth, task, focalSourceId: selectedNode?.sourceId }), [graphMode, graphDepth, task, selectedNode?.sourceId]);
  const computedGraph = useMemo(
    () => buildGraph(selectedProject, graphData, memories, packText, graphOptions),
    [selectedProject, graphData, memories, packText, graphOptions],
  );
  const visibleGraph = useMemo(
    () => filterGraph(computedGraph, nodeQuery, activeTypes, semanticFocus),
    [computedGraph, nodeQuery, activeTypes, semanticFocus],
  );
  const activeNode = computedGraph.nodes.find((node) => node.id === selectedNode?.id) || computedGraph.nodes[0];
  const references = useMemo(() => deriveReferences(computedGraph, activeNode, memories), [computedGraph, activeNode, memories]);
  const readyProjects = projects.filter((project) => project.ready).length;
  const publishReady = publish?.checks?.filter((check) => check.ok).length || 0;
  const publishTotal = publish?.checks?.length || 0;
  const targetAgentLabel = targetAgent === "custom"
    ? customAgent.trim() || "Custom Agent"
    : targetAgents.find((agent) => agent.value === targetAgent)?.label || "Universal / Any Agent";

  async function loadHealth() {
    setIsLoading(true);
    try {
      const payload = await api("/api/health");
      setLoadError("");
      setHealth(payload);
      setProjects(payload.projects || []);
      setPublish(payload.publish);
      setSelectedProject((current) => current || payload.projects?.find((project) => project.status === "ok") || payload.projects?.[0] || null);
    } catch (error) {
      setLoadError(error.message);
      setMessage(`Dashboard refresh failed: ${error.message}`);
    } finally {
      setIsLoading(false);
    }
  }

  async function loadProjectDetails(project = selectedProject) {
    if (!project) return;
    const requestId = projectRequestRef.current + 1;
    projectRequestRef.current = requestId;
    const params = { db_path: project.db_path, project: project.project };
    const [memoryPayload, graphPayload, stalePayload, settingsPayload] = await Promise.all([
      api(`/api/memories?${qs({ ...params, limit: 40 })}`),
      api(`/api/graph?${qs({ ...params, limit: 120 })}`),
      api(`/api/stale-check?${qs(params)}`),
      api(`/api/settings?${qs(params)}`),
    ]);
    if (requestId !== projectRequestRef.current) return;
    setMemories(memoryPayload.memories || []);
    setGraphData(graphPayload || { nodes: [], edges: [] });
    setFreshness(stalePayload);
    setProjectSettings(settingsPayload.settings);
    setParserCapabilities(settingsPayload.parser_capabilities || {});
    setSelectedNode(null);
  }

  async function loadFiles(prefix = "", query = "", project = selectedProject) {
    if (!project) return;
    const requestId = fileRequestRef.current + 1;
    fileRequestRef.current = requestId;
    setFilesLoading(true);
    try {
      const payload = await api(`/api/files?${qs({ db_path: project.db_path, project: project.project, prefix, query, limit: 500 })}`);
      if (requestId !== fileRequestRef.current) return;
      setFileTree(payload);
      setFilePreview(null);
    } catch (error) {
      if (requestId === fileRequestRef.current) setMessage(`File explorer failed: ${error.message}`);
    } finally {
      if (requestId === fileRequestRef.current) setFilesLoading(false);
    }
  }

  async function loadFilePreview(entry) {
    if (!selectedProject || entry.kind !== "file") return;
    setFilePreview({ loading: true, relative_path: entry.relative_path, name: entry.name });
    try {
      const payload = await api(`/api/file-preview?${qs({ db_path: selectedProject.db_path, project: selectedProject.project, path: entry.relative_path })}`);
      setFilePreview(payload.file || { ...entry, missing: true });
    } catch (error) {
      setFilePreview({ ...entry, error: error.message });
    }
  }

  useEffect(() => {
    loadHealth();
  }, []);

  useEffect(() => {
    try {
      localStorage.removeItem(LEGACY_RECEIPT_STORAGE_KEY);
    } catch {
      // Old receipt metadata is best-effort cleanup only.
    }
  }, []);

  useEffect(() => {
    writeLocalString(AGENT_STORAGE_KEY, targetAgent);
  }, [targetAgent]);

  useEffect(() => {
    if (selectedProject) {
      setFileTree({ entries: [], prefix: "", query: "", total_files: 0 });
      setFilePreview(null);
      setMessage(`Loading ${selectedProject.project}...`);
      loadProjectDetails(selectedProject)
        .then(async () => {
          if (viewMode === "files") await loadFiles("", "", selectedProject);
          setMessage(`${selectedProject.project} ready.`);
        })
        .catch((error) => setMessage(`Could not load ${selectedProject.project}: ${error.message}`));
    }
  }, [selectedProject?.db_path, selectedProject?.project]);

  useEffect(() => {
    const onKeyDown = (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandOpen(true);
      }
      if (event.key === "Escape") {
        setCommandOpen(false);
        setStageExpanded(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  async function generatePack() {
    if (!selectedParams) return setMessage("Select a project first.");
    if (!task.trim()) return setMessage("Enter a task first.");
    setIsGenerating(true);
    try {
      setMessage("Generating context pack...");
      const payload = await api("/api/context-pack", {
        method: "POST",
        body: JSON.stringify({ ...selectedParams, task: task.trim(), limit: 8 }),
      });
      const rawText = typeof payload.pack === "string" ? payload.pack : JSON.stringify(payload.pack, null, 2);
      const text = targetAgent === "universal" ? rawText : `Target agent: ${targetAgentLabel}\n\n${rawText}`;
      setPackText(text);
      const receipt = {
        id: `pack-${Date.now()}`,
        createdAt: new Date().toISOString(),
        project: selectedProject.project,
        task: task.trim(),
        agent: targetAgentLabel,
        nodes: buildGraph(selectedProject, graphData, memories, text, graphOptions).nodes.length,
        bytes: new Blob([text]).size,
        pack: text,
      };
      const nextReceipts = [receipt, ...receipts].slice(0, 30);
      setReceipts(nextReceipts);
      setMessage("Context pack generated.");
      showDrawer("receipts");
      setViewMode("graph");
      setGraphMode("task");
    } catch (error) {
      setMessage(error.message);
    } finally {
      setIsGenerating(false);
    }
  }

  async function copyText(text, success = "Copied.") {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const element = document.createElement("textarea");
        element.value = text;
        element.setAttribute("readonly", "");
        element.style.position = "fixed";
        element.style.opacity = "0";
        document.body.appendChild(element);
        element.select();
        document.execCommand("copy");
        document.body.removeChild(element);
      }
      setMessage(success);
    } catch (error) {
      setMessage(`Copy failed: ${error.message}`);
    }
  }

  async function reflect() {
    if (!selectedParams) return;
    try {
      const payload = await api("/api/reflect", { method: "POST", body: JSON.stringify(selectedParams) });
      setMessage(`Reflection complete: ${payload.duplicates_superseded} duplicates, ${payload.contradictions_flagged} contradictions.`);
      await loadProjectDetails();
    } catch (error) {
      setMessage(error.message);
    }
  }

  async function refreshIndex() {
    if (!selectedParams || isRefreshingIndex) return;
    setIsRefreshingIndex(true);
    setMessage(`Refreshing ${selectedProject.project} index...`);
    try {
      const payload = await api("/api/ingest-repo", { method: "POST", body: JSON.stringify(selectedParams) });
      await Promise.all([loadProjectDetails(selectedProject), loadHealth()]);
      const warnings = [
        payload.blocked_files ? `${payload.blocked_files} blocked` : "",
        payload.parser_warnings?.length ? `${payload.parser_warnings.length} parser fallback warnings` : "",
      ].filter(Boolean).join(", ");
      setMessage(`${selectedProject.project}: ${payload.updated_files} updated, ${payload.removed_files} removed, ${payload.unchanged_files} unchanged${warnings ? `, ${warnings}` : ""}.`);
    } catch (error) {
      setMessage(`Index refresh failed: ${error.message}`);
    } finally {
      setIsRefreshingIndex(false);
    }
  }

  async function saveProjectSettings() {
    if (!selectedParams || !projectSettings || isSavingSettings) return;
    setIsSavingSettings(true);
    setMessage(`Saving ${selectedProject.project} indexing policy...`);
    try {
      const payload = await api("/api/settings", {
        method: "POST",
        body: JSON.stringify({ ...selectedParams, settings: projectSettings }),
      });
      setProjectSettings(payload.settings);
      setParserCapabilities(payload.parser_capabilities || {});
      setMessage("Indexing policy saved. Refresh the index to apply it to existing files.");
    } catch (error) {
      setMessage(`Settings could not be saved: ${error.message}`);
    } finally {
      setIsSavingSettings(false);
    }
  }

  function toggleType(type) {
    setActiveTypes((current) => {
      if (current.includes(type) && current.length === 1) return allGraphTypes;
      if (current.includes(type)) return current.filter((item) => item !== type);
      return [...current, type];
    });
  }

  function exportView(filename, payload) {
    downloadJson(filename, payload);
    setMessage(`${filename} export started.`);
  }

  function showDrawer(name) {
    setActiveDrawer(name);
    setInspectorOpen(true);
  }

  function showWorkspace(view) {
    setViewMode(view);
    setSemanticFocus(null);
    setNavContext(view);
  }

  function focusSemanticHub(hub) {
    setViewMode("graph");
    setSemanticFocus((current) => (current === hub ? null : hub));
    setNavContext(hub);
  }

  function showFiles() {
    setViewMode("files");
    setSemanticFocus(null);
    setNavContext("files");
    loadFiles(fileTree.prefix || "", fileTree.query || "");
  }

  function showBase(table, kind = "", context = "bases") {
    setViewMode("bases");
    setSemanticFocus(null);
    setBaseScope({ table, kind });
    setNavContext(context);
  }

  const shellKind = health?.shell || "powershell";
  const commandDbPath = presentationMode
    ? shellKind === "powershell"
      ? `$env:USERPROFILE\\Documents\\Rta-Smriti\\brains\\${selectedProject?.project || "project"}.sqlite`
      : `$HOME/.local/share/rta-smriti/brains/${selectedProject?.project || "project"}.sqlite`
    : selectedProject?.db_path;
  const cliCommand = health?.cli_command || "rta-brain";
  const command = selectedProject
    ? `${cliCommand} --db ${shellPathArg(commandDbPath, shellKind)} context-pack ${shellQuote(task || "<task>", shellKind)} --project ${shellQuote(selectedProject.project, shellKind)}`
    : "Select a project";

  return (
    <div className="app">
      <div className="topbar">
        <div className="brand">
          <div className="brandMark">
            <BrainCircuit size={25} />
          </div>
          <div>
            <strong>Rta-Smriti Brain</strong>
            <span>v0.4 Alpha Operator Console</span>
          </div>
        </div>
        <div className="topStatus">
          <span className="localBadge">
            <ShieldCheck size={15} /> Local Only
          </span>
          <span className="pathText">Brain Path {presentationMode ? "%USERPROFILE%\\Documents\\Rta-Smriti\\brains" : displayPath(health?.brain_dir)}</span>
        </div>
        <div className="topActions">
          <button className="ghostButton" onClick={() => showDrawer("bootstrap")}>
            <Plus size={16} /> New Brain
          </button>
          <button className="ghostButton" onClick={() => showDrawer("publish")}>
            <GitPullRequest size={16} /> Publish
          </button>
          <button className="ghostButton commandButton" onClick={() => setCommandOpen(true)}>
            <Command size={16} /> Cmd Palette
          </button>
          <span className="healthDot" />
        </div>
      </div>

      <div className={inspectorOpen ? "layout" : "layout inspectorClosed"}>
        <aside className="projectRail">
          <div className="projectSwitcher">
            <div className="railHeader">
              <span>Workspace</span>
              <button onClick={loadHealth} aria-label="Refresh projects" title="Refresh projects">
                <RefreshCw size={15} />
              </button>
            </div>
            <button
              className={projectsOpen ? "activeProjectButton open" : "activeProjectButton"}
              onClick={() => setProjectsOpen((value) => !value)}
              aria-expanded={projectsOpen}
              aria-controls="project-switcher-list"
            >
              <span className="activeProjectIcon"><Network size={18} /></span>
              <span className="activeProjectCopy">
                <small>Projects</small>
                <strong>{selectedProject?.project || "Choose a brain"}</strong>
              </span>
              <span className={`projectStateDot ${selectedProject?.ready ? "ok" : "warn"}`} />
              <ChevronRight className="projectChevron" size={16} />
            </button>
            {projectsOpen && (
              <div className="compactProjectList" id="project-switcher-list">
                {projects.map((project) => (
                  <button
                    key={`${project.db_path}:${project.project}`}
                    className={selectedProject?.db_path === project.db_path && selectedProject?.project === project.project ? "compactProject active" : "compactProject"}
                    onClick={() => {
                      setSelectedProject(project);
                      setProjectsOpen(false);
                    }}
                    aria-label={`${project.project}, ${safeNumber(project.sources)} files, ${project.ready ? "ready" : "needs attention"}`}
                  >
                    <Network size={15} />
                    <span><strong>{project.project}</strong><small>{safeNumber(project.sources)} files / {safeNumber(project.memories)} memories</small></span>
                    <i className={project.ready ? "ok" : "warn"} />
                  </button>
                ))}
                {isLoading && !projects.length && <div className="railEmpty">Scanning local brains...</div>}
                {!isLoading && !projects.length && <button className="railEmpty actionable" onClick={() => showDrawer("bootstrap")}>Bootstrap the first project</button>}
                <button className="addProjectButton" onClick={() => showDrawer("bootstrap")}><Plus size={14} /> Add project brain</button>
              </div>
            )}
          </div>

          <nav className="sideNavigation" aria-label="Operator console navigation">
            <div className="navGroup">
              <span className="navGroupLabel">Overview</span>
              <button title="Explore project relationships" className={navContext === "graph" ? "active" : ""} onClick={() => showWorkspace("graph")}><GitBranch size={17} /><span>Graph</span></button>
              <button title="Arrange a temporary working set" className={navContext === "canvas" ? "active" : ""} onClick={() => showWorkspace("canvas")}><MapIcon size={17} /><span>Canvas</span></button>
              <button title="Scan structured project records" className={navContext === "bases" ? "active" : ""} onClick={() => showBase("memory", "", "bases")}><Table2 size={17} /><span>Bases</span></button>
            </div>
            <div className="navGroup">
              <span className="navGroupLabel">Project</span>
              <button title="Browse and preview indexed source" className={navContext === "files" ? "active" : ""} onClick={showFiles}><Files size={17} /><span>Files</span></button>
              <button title="Scan indexed code symbols" className={navContext === "symbols" ? "active" : ""} onClick={() => showBase("files", "symbol", "symbols")}><Code2 size={17} /><span>Symbols</span></button>
              <button title="Scan indexed dependencies" className={navContext === "imports" ? "active" : ""} onClick={() => showBase("files", "import", "imports")}><GitBranch size={17} /><span>Imports</span></button>
              <button title="Review durable project knowledge" className={navContext === "memories" ? "active" : ""} onClick={() => showBase("memory", "", "memories")}><MemoryStick size={17} /><span>Memories</span></button>
              <button title="Inspect evidence and freshness" className={navContext === "evidence" ? "active" : ""} onClick={() => { focusSemanticHub("evidence"); showDrawer("evidence"); }}><ShieldCheck size={17} /><span>Evidence</span></button>
            </div>
            <div className="navGroup">
              <span className="navGroupLabel">Tools</span>
              <button className={searchOpen ? "active" : ""} onClick={() => { setViewMode("graph"); setNavContext("search"); setSearchOpen(true); }}><Search size={17} /><span>Search</span></button>
              <button className={inspectorOpen && activeDrawer === "memory" ? "active" : ""} onClick={() => showDrawer("memory")}><Database size={17} /><span>Memory Ledger</span></button>
              <button className={inspectorOpen && activeDrawer === "receipts" ? "active" : ""} onClick={() => showDrawer("receipts")}><Sparkles size={17} /><span>Context Packs</span><em>{receipts.length}</em></button>
              <button className={inspectorOpen && activeDrawer === "publish" ? "active" : ""} onClick={() => showDrawer("publish")}><Rocket size={17} /><span>Launch Readiness</span><em>{publishReady}/{publishTotal}</em></button>
              <button className={settingsOpen ? "active" : ""} onClick={() => { setViewMode("graph"); setSettingsOpen(true); }}><SlidersHorizontal size={17} /><span>Settings</span></button>
            </div>
          </nav>
          <div className="railFooter">
            <span>
              <Database size={15} /> {readyProjects}/{projects.length} ready
            </span>
            <span>
              <HardDrive size={15} /> SQLite
            </span>
          </div>
        </aside>

        <main className={stageExpanded ? "brainStage expanded" : "brainStage"}>
          <div className="stageToolbar">
            <div className="viewSwitch" aria-label="Workspace view">
              <button className={viewMode === "graph" ? "active" : ""} onClick={() => showWorkspace("graph")}><GitBranch size={15} /> Graph</button>
              <button className={viewMode === "canvas" ? "active" : ""} onClick={() => showWorkspace("canvas")}><MapIcon size={15} /> Canvas</button>
              <button className={viewMode === "bases" ? "active" : ""} onClick={() => showBase("memory", "", "bases")}><Table2 size={15} /> Bases</button>
            </div>
            <div className="modeGroup" aria-label="Graph scope">
              {graphModes.map((mode) => (
                <button key={mode} aria-pressed={graphMode === mode} className={graphMode === mode ? "active" : ""} onClick={() => setGraphMode(mode)}>{mode}</button>
              ))}
            </div>
            <button className={searchOpen ? "toolButton active" : "toolButton"} onClick={() => setSearchOpen((value) => !value)} aria-label="Search" title="Search">
              <Search size={16} /> <span className="toolText">Search</span>
            </button>
            <button className={typesOpen ? "toolButton active" : "toolButton"} onClick={() => setTypesOpen((value) => !value)} aria-label="Types" title="Types">
              <Layers3 size={16} /> <span className="toolText">Types</span>
            </button>
            <button className={settingsOpen ? "toolButton active" : "toolButton"} onClick={() => setSettingsOpen((value) => !value)} aria-label="Settings" title="Graph settings">
              <SlidersHorizontal size={16} /> <span className="toolText">Settings</span>
            </button>
            <button className="toolButton iconOnly" onClick={() => exportView(`${selectedProject?.project || "rta-smriti"}-${viewMode}.json`, { project: selectedProject?.project, task, view: viewMode, graph: visibleGraph })} aria-label="Export current view" title="Export current view">
              <Download size={16} />
            </button>
            <button className={inspectorOpen ? "toolButton active" : "toolButton"} onClick={() => setInspectorOpen((value) => !value)} aria-label={inspectorOpen ? "Close detail panel" : "Open detail panel"} title={inspectorOpen ? "Close detail panel" : "Open detail panel"}>
              <PanelRightOpen size={16} />
            </button>
            <button className="toolButton" onClick={() => setStageExpanded((value) => !value)} aria-label={stageExpanded ? "Exit expanded graph" : "Expand graph"}>
              <Maximize2 size={16} />
            </button>
          </div>

          <div className={searchOpen || typesOpen || settingsOpen ? "graphFilters" : "graphFilters collapsed"}>
              {searchOpen && (
                <label className="nodeSearch">
                  <Search size={15} />
                  <input value={nodeQuery} onChange={(event) => setNodeQuery(event.target.value)} placeholder="Search files, symbols, memories..." autoFocus />
                </label>
              )}
              {typesOpen && (
                <div className="typeFilters" aria-label="Graph type filters">
                  {allGraphTypes.map((type) => (
                    <button key={type} aria-pressed={activeTypes.includes(type)} className={activeTypes.includes(type) ? "active" : ""} onClick={() => toggleType(type)}>
                      <i style={{ background: graphPalette[type] }} /> {type}
                    </button>
                  ))}
                </div>
              )}
              {settingsOpen && (
                <GraphSettings
                  depth={graphDepth}
                  setDepth={setGraphDepth}
                  showLabels={showLabels}
                  setShowLabels={setShowLabels}
                  showEdges={showEdges}
                  setShowEdges={setShowEdges}
                  projectSettings={projectSettings}
                  setProjectSettings={setProjectSettings}
                  parserCapabilities={parserCapabilities}
                  onSave={saveProjectSettings}
                  isSaving={isSavingSettings}
                />
              )}
            </div>

          {viewMode === "graph" && <GraphCanvas graph={visibleGraph} selectedNode={selectedNode} onSelect={setSelectedNode} query={nodeQuery} showLabels={showLabels} showEdges={showEdges} />}
          {viewMode === "files" && (
            <FileExplorer
              tree={fileTree}
              preview={filePreview}
              loading={filesLoading}
              freshness={freshness}
              onOpen={(entry) => entry.kind === "directory" ? loadFiles(entry.relative_path, "") : loadFilePreview(entry)}
              onNavigate={(prefix) => loadFiles(prefix, "")}
              onSearch={(query) => loadFiles("", query)}
              onRefresh={() => loadFiles(fileTree.prefix || "", fileTree.query || "")}
              onCopy={(path) => copyText(path, "Relative path copied.")}
              onUse={(path) => setTask((current) => current.includes(path) ? current : `${current.trim()}\nRelevant file: ${path}`.trim())}
            />
          )}
          {viewMode === "canvas" && <CanvasBoard project={selectedProject} graph={visibleGraph} onSelect={(node) => { setSelectedNode(node); showDrawer("evidence"); }} onExport={exportView} />}
          {viewMode === "bases" && <BasesView memories={memories} graph={computedGraph} publish={publish} onSelect={(node) => { setSelectedNode(node); showDrawer("evidence"); }} initialTable={baseScope.table} kindFilter={baseScope.kind} />}

          <TaskComposer
            task={task}
            setTask={setTask}
            project={selectedProject}
            freshness={freshness}
            command={command}
            packText={packText}
            onGenerate={generatePack}
            onCopy={() => copyText(packText || command, packText ? "Context pack copied." : "Command copied.")}
            onReceipts={() => showDrawer("receipts")}
            receiptCount={receipts.length}
            isGenerating={isGenerating}
            targetAgent={targetAgent}
            setTargetAgent={setTargetAgent}
            customAgent={customAgent}
            setCustomAgent={setCustomAgent}
          />
        </main>

        <aside className={inspectorOpen ? "inspector" : "inspector hidden"}>
          <div className="inspectorTabs">
            <button className={activeDrawer === "evidence" ? "active" : ""} onClick={() => showDrawer("evidence")}>
              <PanelRightOpen size={15} /> Evidence
            </button>
            <button className={activeDrawer === "references" ? "active" : ""} onClick={() => showDrawer("references")}>
              <GitBranch size={15} /> Refs
            </button>
            <button className={activeDrawer === "memory" ? "active" : ""} onClick={() => showDrawer("memory")}>
              <MemoryStick size={15} /> Memory
            </button>
            <button className={activeDrawer === "receipts" ? "active" : ""} onClick={() => showDrawer("receipts")}>
              <Clipboard size={15} /> Packs
            </button>
            <button className={activeDrawer === "publish" ? "active" : ""} onClick={() => showDrawer("publish")}>
              <Rocket size={15} /> Launch
            </button>
          </div>

          {activeDrawer === "evidence" && (
            <EvidenceInspector
              node={activeNode}
              memories={memories}
              project={selectedProject}
              freshness={freshness}
              packText={packText}
              publishReady={publishReady}
              publishTotal={publishTotal}
              onCopy={() => copyText(packText || command)}
              onBootstrap={() => showDrawer("bootstrap")}
              onRefresh={refreshIndex}
              isRefreshing={isRefreshingIndex}
            />
          )}
          {activeDrawer === "references" && <ReferencesPanel node={activeNode} references={references} onSelect={(reference) => setSelectedNode(reference.node || activeNode)} />}
          {activeDrawer === "memory" && <MemoryLedger memories={memories} onReflect={reflect} />}
          {activeDrawer === "receipts" && <ReceiptsPanel receipts={receipts} onCopy={copyText} onClear={() => setReceipts([])} />}
          {activeDrawer === "publish" && <PublishPanel publish={publish} />}
          {activeDrawer === "bootstrap" && <BootstrapPanel onDone={loadHealth} shellKind={shellKind} />}
        </aside>
      </div>

      <footer className="statusBar">
        <span>
          <CheckCircle2 size={14} /> Brain Status: {isLoading ? "Scanning" : loadError ? "Needs attention" : "Healthy"}
        </span>
        <span>
          <CircleDot size={14} /> Graph DB: Local SQLite
        </span>
        <span>
          <Activity size={14} /> {message || "Ready"}
        </span>
      </footer>

      {commandOpen && (
        <CommandPalette
          command={command}
          cliCommand={cliCommand}
          shellKind={shellKind}
          brainDir={health?.brain_dir}
          onClose={() => setCommandOpen(false)}
          onCopy={copyText}
        />
      )}
    </div>
  );
}

function GraphSettings({
  depth, setDepth, showLabels, setShowLabels, showEdges, setShowEdges,
  projectSettings, setProjectSettings, parserCapabilities, onSave, isSaving,
}) {
  const settings = projectSettings || {};
  const updateSetting = (key, value) => setProjectSettings((current) => ({ ...(current || {}), [key]: value }));
  const parserStatus = parserCapabilities[settings.parser_adapter];
  return (
    <div className="graphSettings">
      <div className="settingsGroup graphDisplaySettings">
        <strong>Graph display</strong>
        <label>
          <span>Connection depth</span>
          <input type="range" min="1" max="4" value={depth} onChange={(event) => setDepth(Number(event.target.value))} />
          <strong>{depth}</strong>
        </label>
        <label className="toggleLabel"><input type="checkbox" checked={showLabels} onChange={(event) => setShowLabels(event.target.checked)} /> Persistent labels</label>
        <label className="toggleLabel"><input type="checkbox" checked={showEdges} onChange={(event) => setShowEdges(event.target.checked)} /> Connections</label>
      </div>
      <div className="settingsGroup indexPolicySettings">
        <strong>Project indexing policy</strong>
        <label>
          <span>Maximum source file size</span>
          <div className="numberUnit">
            <input
              type="number"
              min="0.01"
              max="16"
              step="0.1"
              value={settings.max_file_bytes ? Number(settings.max_file_bytes / 1_000_000).toFixed(2) : ""}
              onChange={(event) => updateSetting("max_file_bytes", Math.round(Number(event.target.value) * 1_000_000))}
            />
            <span>MB</span>
          </div>
        </label>
        <label>
          <span>Parser adapter</span>
          <select value={settings.parser_adapter || "regex"} onChange={(event) => updateSetting("parser_adapter", event.target.value)}>
            <option value="regex">Regex (built in)</option>
            <option value="tree-sitter">Tree-sitter (optional)</option>
            <option value="lsp">LSP command (optional)</option>
          </select>
          {parserStatus && <em className={parserStatus.available ? "available" : "optional"}>{parserStatus.available ? "Ready" : "Optional dependency"}</em>}
        </label>
        {settings.parser_adapter === "lsp" && (
          <label className="lspCommand">
            <span>LSP adapter command</span>
            <input value={settings.lsp_command || ""} onChange={(event) => updateSetting("lsp_command", event.target.value)} placeholder="Command that accepts and returns JSON" />
          </label>
        )}
        <label>
          <span>Hybrid retrieval</span>
          <select value={settings.embedding_provider || "none"} onChange={(event) => updateSetting("embedding_provider", event.target.value)}>
            <option value="none">Off (FTS only)</option>
            <option value="hash">Local feature hash</option>
            <option value="sentence-transformers">Sentence Transformers (optional)</option>
          </select>
        </label>
        <button className="savePolicyButton" onClick={onSave} disabled={!projectSettings || isSaving}>
          <ShieldCheck size={15} /> {isSaving ? "Saving..." : "Save Policy"}
        </button>
        <p className="blockedPolicyWarning"><ShieldCheck size={14} /> Blocked files stay excluded and freshness remains fail-closed until this policy changes.</p>
      </div>
    </div>
  );
}

function GraphCanvas({ graph, selectedNode, onSelect, query, showLabels, showEdges }) {
  const canvasRef = useRef(null);
  const panRef = useRef(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [hoveredNodeId, setHoveredNodeId] = useState(null);
  const [hoveredHubId, setHoveredHubId] = useState(null);
  const [collapsedHubs, setCollapsedHubs] = useState([]);
  const displayedNodes = graph.nodes.filter((node) => !collapsedHubs.includes(node.hubId));
  const nodesById = useMemo(() => new Map(displayedNodes.map((node) => [node.id, node])), [displayedNodes]);

  useEffect(() => {
    setCollapsedHubs([]);
  }, [graph.core?.id]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas && canvas.scrollWidth > canvas.clientWidth) {
      canvas.scrollLeft = (canvas.scrollWidth - canvas.clientWidth) / 2;
    }
  }, [graph.nodes.length]);

  const focusX = 500;
  const focusY = 304;
  const viewWidth = 1000 / zoom;
  const viewHeight = 620 / zoom;
  const viewX = Math.max(0, Math.min(1000 - viewWidth, focusX - viewWidth / 2 + pan.x));
  const viewY = Math.max(0, Math.min(620 - viewHeight, focusY - viewHeight / 2 + pan.y));

  function centerGraph() {
    setZoom(1);
    setPan({ x: 0, y: 0 });
    window.requestAnimationFrame(() => {
      const canvas = canvasRef.current;
      if (canvas && canvas.scrollWidth > canvas.clientWidth) {
        canvas.scrollLeft = (canvas.scrollWidth - canvas.clientWidth) / 2;
      }
    });
  }

  function beginPan(event) {
    if (event.button !== 0) return;
    const bounds = event.currentTarget.ownerSVGElement?.getBoundingClientRect();
    if (!bounds) return;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    panRef.current = { x: event.clientX, y: event.clientY, pan, bounds };
    setIsPanning(true);
  }

  function movePan(event) {
    const start = panRef.current;
    if (!start) return;
    setPan({
      x: start.pan.x - ((event.clientX - start.x) / start.bounds.width) * viewWidth,
      y: start.pan.y - ((event.clientY - start.y) / start.bounds.height) * viewHeight,
    });
  }

  function endPan() {
    panRef.current = null;
    setIsPanning(false);
  }

  function toggleHub(hubId) {
    setCollapsedHubs((current) => current.includes(hubId) ? current.filter((id) => id !== hubId) : [...current, hubId]);
  }

  return (
    <section ref={canvasRef} className={`graphCanvas ${isPanning ? "panning" : ""}`} aria-label="Interactive project brain graph">
      <svg className="graphSvg" viewBox={`${viewX} ${viewY} ${viewWidth} ${viewHeight}`} role="img" aria-label="Rta-Smriti graph">
        <defs>
          <filter id="softGlow">
            <feGaussianBlur stdDeviation="5" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        <rect width="1000" height="620" className="gridRect" onPointerDown={beginPan} onPointerMove={movePan} onPointerUp={endPan} onPointerCancel={endPan} />
        {showEdges && (graph.hubs || []).length > 1 && (graph.hubs || []).map((hub, index, hubs) => {
          const next = hubs[(index + 1) % hubs.length];
          const x1 = hub.x * 10;
          const y1 = hub.y * 6.2;
          const x2 = next.x * 10;
          const y2 = next.y * 6.2;
          return (
            <g key={`web-${hub.id}-${next.id}`} className="semanticWebEdge">
              <line x1={x1} y1={y1} x2={x2} y2={y2} />
              <circle cx={(x1 + x2) / 2} cy={(y1 + y2) / 2} r="4" />
            </g>
          );
        })}
        {showEdges && (graph.hubs || []).map((hub) => {
          const collapsed = collapsedHubs.includes(hub.id);
          const x1 = graph.core.x * 10;
          const y1 = graph.core.y * 6.2;
          const x2 = hub.x * 10;
          const y2 = hub.y * 6.2;
          return (
            <g key={`core-${hub.id}`} className={`structureEdge ${hoveredHubId === hub.id ? "active" : ""} ${collapsed ? "collapsed" : ""}`}>
              <line x1={x1} y1={y1} x2={x2} y2={y2} />
              <circle className="relayNode" cx={x1 + (x2 - x1) * 0.56} cy={y1 + (y2 - y1) * 0.56} r="4.5" />
            </g>
          );
        })}
        {showEdges && displayedNodes.map((node) => {
          const hub = graph.hubs?.find((candidate) => candidate.id === node.hubId);
          if (!hub) return null;
          return (
            <g key={`structure-${node.id}`} className={`structureEdge leaf ${hoveredHubId === hub.id ? "active" : ""}`}>
              <line style={{ stroke: hub.color }} x1={hub.x * 10} y1={hub.y * 6.2} x2={node.x * 10} y2={node.y * 6.2} />
            </g>
          );
        })}
        {showEdges && graph.edges.map((edge) => {
          const source = nodesById.get(edge.source);
          const target = nodesById.get(edge.target);
          if (!source || !target) return null;
          const x1 = source.x * 10;
          const y1 = source.y * 6.2;
          const x2 = target.x * 10;
          const y2 = target.y * 6.2;
          const active = selectedNode?.id === source.id || selectedNode?.id === target.id || hoveredNodeId === source.id || hoveredNodeId === target.id;
          return (
            <g key={edge.id} className={active ? "graphEdge active" : "graphEdge"}>
              <line x1={x1} y1={y1} x2={x2} y2={y2} />
              {showLabels && <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 8}>{edge.label}</text>}
            </g>
          );
        })}
        {graph.core && (
          <g className="projectCore" transform={`translate(${graph.core.x * 10}, ${graph.core.y * 6.2})`} aria-label={`${graph.core.label} project brain`} role="img">
            <circle className="projectOrbit outer" r="78" />
            <circle className="projectOrbit" r="64" />
            <circle className="coreAura" r="55" />
            <circle className="coreBody" r="45" />
            <foreignObject x="-17" y="-29" width="34" height="34" pointerEvents="none">
              <span className="projectCoreIcon"><BrainCircuit size={33} /></span>
            </foreignObject>
            <text className="coreLabel" y="25">{graph.core.label.length > 18 ? `${graph.core.label.slice(0, 16)}...` : graph.core.label}</text>
            <text className="coreMeta" y="42">{graph.core.meta}</text>
          </g>
        )}
        {(graph.hubs || []).map((hub) => {
          const HubIcon = hub.icon;
          const collapsed = collapsedHubs.includes(hub.id);
          return (
            <g
              key={hub.id}
              className={`semanticHub ${collapsed ? "collapsed" : ""}`}
              transform={`translate(${hub.x * 10}, ${hub.y * 6.2})`}
              onClick={() => toggleHub(hub.id)}
              onMouseEnter={() => setHoveredHubId(hub.id)}
              onMouseLeave={() => setHoveredHubId(null)}
              onFocus={() => setHoveredHubId(hub.id)}
              onBlur={() => setHoveredHubId(null)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  toggleHub(hub.id);
                }
              }}
              tabIndex={0}
              role="button"
              aria-pressed={collapsed}
              aria-label={`${hub.label}, ${hub.count} nodes. ${collapsed ? "Expand" : "Collapse"} group.`}
            >
              <title>{collapsed ? "Expand" : "Collapse"} {hub.label}</title>
              <circle className="hubAura" r="40" fill={hub.color} />
              <circle className="hubBody" r="32" stroke={hub.color} />
              <foreignObject x="-12" y="-21" width="24" height="24" pointerEvents="none">
                <span className="hubIcon" style={{ color: hub.color }}><HubIcon size={23} /></span>
              </foreignObject>
              <text className="hubLabel" y="21">{hub.label}</text>
              <text className="hubCount" y="39">{hub.count}</text>
            </g>
          );
        })}
        {displayedNodes.map((node, index) => {
          const color = node.color || graphPalette[node.type] || graphPalette.data;
          const active = selectedNode?.id === node.id;
          const NodeIcon = {
            file: FileCode2,
            memory: MemoryStick,
            docs: Files,
            config: SlidersHorizontal,
            test: ShieldCheck,
            data: Database,
            artifact: Layers3,
          }[node.type] || CircleDot;
          const reveal = showLabels || hoveredNodeId === node.id || active;
          const shortLabel = node.label.length > 32 ? `${node.label.slice(0, 29)}...` : node.label;
          const tooltipWidth = Math.min(230, Math.max(112, shortLabel.length * 7.2));
          const absoluteX = node.x * 10;
          const absoluteY = node.y * 6.2;
          const tooltipX = Math.max(8 - absoluteX, Math.min(-tooltipWidth / 2, 992 - absoluteX - tooltipWidth));
          const tooltipY = absoluteY < 70 ? node.size + 12 : -(node.size + 48);
          const related = hoveredHubId === node.hubId;
          return (
            <g
              key={node.id}
              className={`graphNode ${active ? "active" : ""} ${related ? "related" : ""}`}
              transform={`translate(${node.x * 10}, ${node.y * 6.2})`}
              style={{ animationDelay: `${Math.min(index, 20) * 18}ms` }}
              onClick={() => onSelect(node)}
              onMouseEnter={() => setHoveredNodeId(node.id)}
              onMouseLeave={() => setHoveredNodeId(null)}
              onFocus={() => setHoveredNodeId(node.id)}
              onBlur={() => setHoveredNodeId(null)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelect(node);
                }
              }}
              tabIndex={0}
              role="button"
              aria-label={`${node.label}, ${node.meta}`}
            >
              <circle className="nodeAura" r={node.size + 8} fill={color} />
              <circle className="nodeCore" r={node.size} stroke={color} />
              <foreignObject x="-7" y="-7" width="14" height="14" pointerEvents="none">
                <span className="graphNodeIcon" style={{ color }}><NodeIcon size={14} /></span>
              </foreignObject>
              {reveal && (
                <g className="nodeTooltip" transform={`translate(${tooltipX}, ${tooltipY})`}>
                  <rect width={tooltipWidth} height="38" rx="6" />
                  <text className="nodeLabel" x={tooltipWidth / 2} y="16">{shortLabel}</text>
                  <text className="nodeMeta" x={tooltipWidth / 2} y="30">{node.meta}</text>
                </g>
              )}
            </g>
          );
        })}
      </svg>
      {!displayedNodes.length && (
        <div className="emptyGraph">
          <Search size={24} />
          <strong>No matching nodes</strong>
          <span>{query ? `No graph evidence matched "${query}".` : "Enable at least one graph type."}</span>
        </div>
      )}
      <div className="graphControls">
        <button aria-label="Center graph" onClick={centerGraph}>
          <Crosshair size={14} />
        </button>
        <button aria-label="Zoom in" onClick={() => setZoom((value) => Math.min(1.7, Number((value + 0.1).toFixed(2))))}>
          +
        </button>
        <button aria-label="Zoom out" onClick={() => setZoom((value) => Math.max(0.7, Number((value - 0.1).toFixed(2))))}>
          -
        </button>
        <span>{Math.round(zoom * 100)}%</span>
      </div>
      <div className="legend">
        <span><i className="structureLegend" /> semantic group</span>
        <span><i className="evidenceLegend" /> evidence link</span>
        <span>Hover nodes for detail</span>
      </div>
      {!!displayedNodes.length && (
        <div className="graphMinimap">
          <svg viewBox="0 0 1000 620" role="img" aria-label="Minimap showing the current graph viewport">
            {(graph.hubs || []).map((hub) => <line key={`mini-core-${hub.id}`} x1={graph.core.x * 10} y1={graph.core.y * 6.2} x2={hub.x * 10} y2={hub.y * 6.2} />)}
            {displayedNodes.map((node) => {
              const hub = graph.hubs?.find((candidate) => candidate.id === node.hubId);
              return hub ? <line key={`mini-${node.id}`} x1={hub.x * 10} y1={hub.y * 6.2} x2={node.x * 10} y2={node.y * 6.2} /> : null;
            })}
            <circle className="miniCore" cx={graph.core.x * 10} cy={graph.core.y * 6.2} r="18" />
            {(graph.hubs || []).map((hub) => <circle key={`mini-hub-${hub.id}`} className="miniHub" cx={hub.x * 10} cy={hub.y * 6.2} r="11" />)}
            {displayedNodes.map((node) => <circle key={`mini-node-${node.id}`} className="miniNode" cx={node.x * 10} cy={node.y * 6.2} r="4" />)}
            <rect className="miniViewport" x={viewX} y={viewY} width={viewWidth} height={viewHeight} />
          </svg>
        </div>
      )}
    </section>
  );
}

function FileExplorer({ tree, preview, loading, freshness, onOpen, onNavigate, onSearch, onRefresh, onCopy, onUse }) {
  const [draft, setDraft] = useState(tree.query || "");
  const parts = String(tree.prefix || "").split("/").filter(Boolean);

  useEffect(() => {
    setDraft(tree.query || "");
  }, [tree.query]);

  function submitSearch(event) {
    event.preventDefault();
    onSearch(draft.trim());
  }

  return (
    <section className="fileExplorer" aria-label="Indexed project file explorer">
      <div className="fileExplorerToolbar">
        <div className="fileExplorerTitle">
          <FolderTree size={17} />
          <strong>Files</strong>
          <span>{safeNumber(tree.total_files)} indexed</span>
          <em className={freshness?.state === "fresh" ? "fresh" : "attention"}>{freshness?.state || "checking"}</em>
        </div>
        <form className="fileSearch" onSubmit={submitSearch}>
          <Search size={15} />
          <input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Find indexed files..." aria-label="Find indexed files" />
          {tree.query && <button type="button" onClick={() => { setDraft(""); onSearch(""); }}>Clear</button>}
        </form>
        <button className="fileToolbarButton" onClick={onRefresh} title="Refresh file view" aria-label="Refresh file view"><RefreshCw size={15} /></button>
      </div>

      <div className="fileExplorerBody">
        <div className="fileTreePane">
          <div className="fileBreadcrumbs" aria-label="File path">
            <button onClick={() => onNavigate("")} title="Project root"><FolderTree size={14} /></button>
            {parts.map((part, index) => (
              <React.Fragment key={`${part}-${index}`}>
                <ChevronRight size={13} />
                <button onClick={() => onNavigate(parts.slice(0, index + 1).join("/"))}>{part}</button>
              </React.Fragment>
            ))}
            {tree.query && <><ChevronRight size={13} /><span>Search: {tree.query}</span></>}
          </div>
          {parts.length > 0 && !tree.query && (
            <button className="fileTreeRow parent" onClick={() => onNavigate(parts.slice(0, -1).join("/"))}>
              <ArrowLeft size={15} /><span><strong>Parent folder</strong></span>
            </button>
          )}
          <div className="fileTreeList">
            {loading && <div className="fileTreeState"><RefreshCw className="spin" size={20} /><span>Loading index...</span></div>}
            {!loading && (tree.entries || []).map((entry) => (
              <button
                key={`${entry.kind}:${entry.relative_path}`}
                className={preview?.relative_path === entry.relative_path ? "fileTreeRow active" : "fileTreeRow"}
                onClick={() => onOpen(entry)}
                title={entry.relative_path}
              >
                {entry.kind === "directory" ? <Folder size={16} /> : <FileText size={16} />}
                <span><strong>{entry.name}</strong><small>{entry.kind === "directory" ? `${safeNumber(entry.count)} files` : formatBytes(entry.size)}</small></span>
                {entry.kind === "directory" && <ChevronRight size={14} />}
              </button>
            ))}
            {!loading && !(tree.entries || []).length && <div className="fileTreeState"><Files size={20} /><span>No indexed files found</span></div>}
          </div>
          {tree.truncated && <div className="fileTreeNotice">Showing the first 500 results</div>}
        </div>

        <div className="filePreviewPane">
          {!preview && <div className="filePreviewEmpty"><FileCode2 size={28} /><strong>Indexed file preview</strong><span>{safeNumber(tree.descendant_files || tree.matched_files || tree.total_files)} files in this view</span></div>}
          {preview?.loading && <div className="filePreviewEmpty"><RefreshCw className="spin" size={24} /><strong>Loading preview</strong></div>}
          {preview && !preview.loading && (
            <>
              <div className="filePreviewHeader">
                <div><FileCode2 size={18} /><span><strong>{preview.name}</strong><small>{preview.relative_path}</small></span></div>
                <div>
                  <button onClick={() => onUse(preview.relative_path)}><Plus size={14} /> Add to Task</button>
                  <button onClick={() => onCopy(preview.relative_path)} title="Copy relative path" aria-label="Copy relative path"><Clipboard size={14} /></button>
                </div>
              </div>
              <div className="filePreviewMeta">
                <span>{formatBytes(preview.size)}</span>
                <span>Indexed snapshot</span>
                {preview.preview_truncated && <span>Preview limited</span>}
              </div>
              {preview.error && <div className="filePreviewError">{preview.error}</div>}
              {preview.missing && <div className="filePreviewError">This file is not available in the current index.</div>}
              {!preview.error && !preview.missing && <pre className="filePreviewCode">{preview.content || "No text preview is available for this file."}</pre>}
            </>
          )}
        </div>
      </div>
    </section>
  );
}

function CanvasBoard({ project, graph, onSelect, onExport }) {
  const storageKey = `${CANVAS_STORAGE_KEY}:${project?.project || "default"}`;
  const [positions, setPositions] = useState(() => readLocalJson(storageKey, {}));
  const boardRef = useRef(null);

  useEffect(() => {
    setPositions(readLocalJson(storageKey, {}));
  }, [storageKey]);

  function positionFor(node, index) {
    return positions[node.id] || { x: 7 + (index % 4) * 23, y: 10 + Math.floor(index / 4) * 23 };
  }

  function beginDrag(event, node, index) {
    const board = boardRef.current;
    if (!board) return;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    const start = positionFor(node, index);
    const rect = board.getBoundingClientRect();
    const origin = { x: event.clientX, y: event.clientY };
    const move = (moveEvent) => {
      const next = {
        x: Math.max(1, Math.min(82, start.x + ((moveEvent.clientX - origin.x) / rect.width) * 100)),
        y: Math.max(2, Math.min(84, start.y + ((moveEvent.clientY - origin.y) / rect.height) * 100)),
      };
      setPositions((current) => ({ ...current, [node.id]: next }));
    };
    const end = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      setPositions((current) => {
        writeLocalJson(storageKey, current);
        return current;
      });
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", end, { once: true });
  }

  function resetLayout() {
    setPositions({});
    try {
      localStorage.removeItem(storageKey);
    } catch {
      // Reset still applies for the current session when storage is unavailable.
    }
  }

  const cards = graph.nodes.slice(0, 16);
  return (
    <section ref={boardRef} className="canvasBoard" aria-label="Spatial project canvas">
      <div className="canvasHeader">
        <span><MapIcon size={16} /> Spatial Canvas</span>
        <div className="canvasActions">
          <button onClick={resetLayout}><RotateCcw size={15} /> Reset Layout</button>
          <button onClick={() => onExport(`${project?.project || "rta-smriti"}-canvas.json`, { project: project?.project, positions, nodes: cards })}><Download size={15} /> Export JSON</button>
        </div>
      </div>
      <svg className="canvasThread" aria-hidden="true">
        {graph.edges.map((edge) => {
          const sourceIndex = cards.findIndex((node) => node.id === edge.source);
          const targetIndex = cards.findIndex((node) => node.id === edge.target);
          if (sourceIndex < 0 || targetIndex < 0) return null;
          const source = positionFor(cards[sourceIndex], sourceIndex);
          const target = positionFor(cards[targetIndex], targetIndex);
          return <line key={edge.id} x1={`${source.x + 8}%`} y1={`${source.y + 6}%`} x2={`${target.x + 8}%`} y2={`${target.y + 6}%`} />;
        })}
      </svg>
      {cards.map((node, index) => {
        const position = positionFor(node, index);
        return (
          <button key={node.id} className="canvasCard" style={{ left: `${position.x}%`, top: `${position.y}%`, borderColor: node.color || graphPalette[node.type] }} onPointerDown={(event) => beginDrag(event, node, index)} onDoubleClick={() => onSelect(node)} title="Drag to arrange. Double-click to inspect.">
            <i style={{ background: graphPalette[node.type] }} />
            <strong>{node.label}</strong>
            <span>{node.meta}</span>
          </button>
        );
      })}
      {!cards.length && <div className="emptyGraph"><MapIcon size={24} /><strong>No nodes to arrange</strong></div>}
    </section>
  );
}

function BasesView({ memories, graph, publish, onSelect, initialTable = "memory", kindFilter = "" }) {
  const [table, setTable] = useState(initialTable);
  const [query, setQuery] = useState("");
  useEffect(() => {
    setTable(initialTable);
    setQuery("");
  }, [initialTable, kindFilter]);
  const normalized = query.toLowerCase();
  const memoryRows = memories.filter((item) => `${item.type} ${item.pramana} ${item.text}`.toLowerCase().includes(normalized));
  const fileRows = graph.nodes.filter((item) => (!kindFilter || item.meta === kindFilter) && `${item.label} ${item.meta}`.toLowerCase().includes(normalized));
  return (
    <section className="basesView" aria-label="Typed project data tables">
      <div className="basesToolbar">
        <div className="viewSwitch">
          <button className={table === "memory" ? "active" : ""} onClick={() => setTable("memory")}>Memories</button>
          <button className={table === "files" ? "active" : ""} onClick={() => setTable("files")}>{kindFilter === "symbol" ? "Symbols" : kindFilter === "import" ? "Imports" : "Sources"}</button>
          <button className={table === "readiness" ? "active" : ""} onClick={() => setTable("readiness")}>Readiness</button>
        </div>
        <label className="nodeSearch"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter this base..." /></label>
      </div>
      {table === "memory" && <div className="baseTable"><div className="baseRow head"><span>Type</span><span>Evidence</span><span>Confidence</span><span>Memory</span></div>{memoryRows.map((item) => <button className="baseRow" key={item.id}><span>{item.type}</span><span>{item.pramana}</span><span>{Math.round(item.confidence * 100)}%</span><span>{item.text}</span></button>)}</div>}
      {table === "files" && <div className="baseTable"><div className="baseRow head"><span>Name</span><span>Kind</span><span>Layer</span><span>Action</span></div>{fileRows.map((item) => <button className="baseRow" key={item.id} onClick={() => onSelect(item)}><span>{item.label}</span><span>{item.type}</span><span>{item.meta}</span><span>Inspect</span></button>)}</div>}
      {table === "readiness" && <div className="readinessGrid">{(publish?.checks || []).map((check) => <article key={check.name} className={check.ok ? "ready" : "open"}>{check.ok ? <CheckCircle2 size={18} /> : <CircleDot size={18} />}<strong>{check.name}</strong><span>{check.note || (check.ok ? "Ready" : "Open")}</span></article>)}</div>}
    </section>
  );
}

function TaskComposer({ task, setTask, project, freshness, command, packText, onGenerate, onCopy, onReceipts, receiptCount, isGenerating, targetAgent, setTargetAgent, customAgent, setCustomAgent }) {
  return (
    <section className="taskComposer">
      <div className="composerTitle">
        <span>
          <Sparkles size={16} /> Context-Pack Studio
        </span>
        <div className="composerActions">
          <button onClick={onReceipts}><Eye size={15} /> {receiptCount} receipts</button>
          <button onClick={onCopy}><Clipboard size={15} /> {packText ? "Copy Pack" : "Copy Command"}</button>
        </div>
      </div>
      <div className="composerGrid">
        <div className="formStack">
          <label>
            <span>Target Agent</span>
            <select value={targetAgent} onChange={(event) => setTargetAgent(event.target.value)}>
              {targetAgents.map((agent) => <option key={agent.value} value={agent.value}>{agent.label}</option>)}
            </select>
          </label>
          {targetAgent === "custom" && (
            <label>
              <span>Agent Name</span>
              <input value={customAgent} onChange={(event) => setCustomAgent(event.target.value)} placeholder="Your agent or workflow" />
            </label>
          )}
          <label>
            <span>Objective</span>
            <textarea rows="3" value={task} onChange={(event) => setTask(event.target.value)} />
          </label>
          <label>
            <span>Command Bridge</span>
            <code>{command}</code>
          </label>
        </div>
        <div className="packPreview">
          <div className="freshRing">
            <strong>{freshness?.state === "fresh" ? "OK" : freshness?.state === "stale" ? "!" : "?"}</strong>
            <span>{freshness?.state || "Checking"}</span>
          </div>
          <div>
            <p>Files</p>
            <strong>{safeNumber(project?.sources)}</strong>
          </div>
          <div>
            <p>Memories</p>
            <strong>{safeNumber(project?.memories)}</strong>
          </div>
          <button className="generateButton" onClick={onGenerate} disabled={isGenerating}>
            <Zap size={18} /> {isGenerating ? "Generating..." : "Generate Context Pack"}
          </button>
        </div>
      </div>
    </section>
  );
}

function EvidenceInspector({ node, memories, project, freshness, packText, publishReady, publishTotal, onCopy, onBootstrap, onRefresh, isRefreshing }) {
  return (
    <div className="drawerContent">
      <h2>Evidence Inspector</h2>
      <section className="selectedNode">
        <BrainCircuit size={36} />
        <div>
          <p>Selected Node</p>
          <strong>{node?.label || "Project Brain"}</strong>
          <span>{node?.meta || project?.project}</span>
        </div>
      </section>
      <section>
        <div className="sectionHeader">
          <span>Must-Know Memories</span>
          <em>{memories.length}</em>
        </div>
        <div className="memoryList">
          {memories.slice(0, 5).map((memory) => (
            <article key={memory.id}>
              <CheckCircle2 size={15} />
              <p>{memory.text}</p>
              <strong>{Math.round(memory.confidence * 100)}%</strong>
            </article>
          ))}
        </div>
      </section>
      <FreshnessBars freshness={freshness} onRefresh={onRefresh} isRefreshing={isRefreshing} />
      <RepoTree project={project} />
      <section className="publishMini">
        <div>
          <span>Publish Readiness</span>
          <strong>
            {publishReady}/{publishTotal || "?"}
          </strong>
        </div>
        <button onClick={onCopy}>
          <Clipboard size={16} /> {packText ? "Copy Context" : "Copy Command"}
        </button>
        <button className="amberButton" onClick={onBootstrap}>
          <Rocket size={16} /> Bootstrap Checklist
        </button>
      </section>
    </div>
  );
}

function ReferencesPanel({ node, references, onSelect }) {
  return (
    <div className="drawerContent">
      <h2>References & Backlinks</h2>
      <section className="selectedNode compact">
        <GitBranch size={28} />
        <div><p>Connected to</p><strong>{node?.label || "Project Brain"}</strong><span>{references.length} references</span></div>
      </section>
      <div className="referenceList">
        {references.map((reference) => (
          <button
            key={reference.id}
            onClick={() => onSelect(reference)}
            aria-label={`${reference.label}, ${reference.relation}`}
          >
            <i style={{ background: graphPalette[reference.type] || graphPalette.data }} />
            <span><strong>{reference.label}</strong><em>{reference.relation}</em></span>
            <ChevronRight size={15} />
          </button>
        ))}
        {!references.length && <p className="emptyText">No visible backlinks for this node. Increase graph depth or switch to Global.</p>}
      </div>
    </div>
  );
}

function FreshnessBars({ freshness, onRefresh, isRefreshing }) {
  const total = Math.max(1, (freshness?.fresh || 0) + (freshness?.changed || 0) + (freshness?.missing || 0) + (freshness?.added || 0) + (freshness?.uninspectable || 0));
  const bars = [
    ["Fresh", freshness?.fresh || 0],
    ["Changed", freshness?.changed || 0],
    ["Missing", freshness?.missing || 0],
    ["Added", freshness?.added || 0],
    ["Blocked", freshness?.uninspectable || 0],
  ];
  return (
    <section>
      <div className="sectionHeader">
        <span>Freshness</span>
        <button className="freshnessAction" onClick={onRefresh} disabled={isRefreshing} title="Refresh repository index">
          <RefreshCw size={13} /> {isRefreshing ? "Indexing" : freshness?.state || "Checking"}
        </button>
      </div>
      <div className="bars">
        {bars.map(([label, count]) => (
          <div key={label}>
            <span>{label}</span>
            <i>
              <b style={{ width: `${Math.round((count / total) * 100)}%` }} />
            </i>
            <em>{count}</em>
          </div>
        ))}
      </div>
    </section>
  );
}

function RepoTree({ project }) {
  const root = project?.root_path || "memory-only";
  return (
    <section>
      <div className="sectionHeader">
        <span>Repo Tree</span>
        <em>{project?.project}</em>
      </div>
      <div className="repoTree">
        <p>
          <FolderTree size={15} /> {root.split(/[\\/]/).pop() || root}
        </p>
        <p>
          <Files size={15} /> source files
        </p>
        <p>
          <FileCode2 size={15} /> symbols and imports
        </p>
        <p>
          <Code2 size={15} /> AGENTS.md bridge
        </p>
      </div>
    </section>
  );
}

function MemoryLedger({ memories, onReflect }) {
  const [filter, setFilter] = useState("all");
  const types = ["all", ...new Set(memories.map((memory) => memory.type).filter(Boolean))];
  const visible = filter === "all" ? memories : memories.filter((memory) => memory.type === filter);
  return (
    <div className="drawerContent">
      <h2>Memory Ledger</h2>
      <button className="primarySmall" onClick={onReflect}>
        <RefreshCw size={16} /> Reflect Memories
      </button>
      <div className="ledgerFilters">
        {types.slice(0, 6).map((type) => <button key={type} className={filter === type ? "active" : ""} onClick={() => setFilter(type)}>{type}</button>)}
      </div>
      <div className="ledgerList">
        {visible.map((memory) => (
          <article key={memory.id}>
            <span>{memory.pramana}</span>
            <strong>{memory.type}</strong>
            <p>{memory.text}</p>
          </article>
        ))}
      </div>
    </div>
  );
}

function ReceiptsPanel({ receipts, onCopy, onClear }) {
  return (
    <div className="drawerContent">
      <div className="sectionHeader"><h2>Context-Pack Receipts</h2>{receipts.length > 0 && <button onClick={onClear}>Clear</button>}</div>
      <p className="drawerIntro">Session-only history of what context was assembled. Closing this tab clears it.</p>
      <div className="receiptList">
        {receipts.map((receipt) => (
          <article key={receipt.id}>
            <div><strong>{receipt.project}</strong><time>{new Date(receipt.createdAt).toLocaleString()}</time></div>
            <p>{receipt.task}</p>
            <span>{receipt.agent || "Universal"} | {receipt.nodes} nodes | {(receipt.bytes / 1024).toFixed(1)} KB</span>
            {receipt.pack ? <button onClick={() => onCopy(receipt.pack, "Saved context pack copied.")}><Clipboard size={14} /> Copy</button> : <span className="receiptPrivate">Metadata only</span>}
          </article>
        ))}
        {!receipts.length && <p className="emptyText">Generate a context pack to create the first receipt.</p>}
      </div>
    </div>
  );
}

function PublishPanel({ publish }) {
  return (
    <div className="drawerContent">
      <h2>Launch Readiness</h2>
      <div className="launchChecks">
        {(publish?.checks || []).map((check) => (
          <article key={check.name}>
            {check.ok ? <CheckCircle2 size={16} /> : <CircleDot size={16} />}
            <div>
              <strong>{check.name}</strong>
              <span>{check.note || (check.ok ? "Ready" : "Open")}</span>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

function BootstrapPanel({ onDone, shellKind }) {
  const [path, setPath] = useState("");
  const [project, setProject] = useState("");
  const [output, setOutput] = useState("");
  const [writeAgents, setWriteAgents] = useState(false);
  const [isBootstrapping, setIsBootstrapping] = useState(false);

  async function bootstrap() {
    if (!path.trim() || !project.trim()) {
      setOutput("Enter a project folder and project name.");
      return;
    }
    try {
      setIsBootstrapping(true);
      setOutput("Building local brain...");
      const payload = await api("/api/bootstrap", {
        method: "POST",
        body: JSON.stringify({ path, project, write_agents: writeAgents }),
      });
      setOutput(`Brain ready: ${payload.project}\nIndexed files: ${payload.ingest.indexed_files}\nDatabase: ${displayPath(payload.db_path)}${payload.agent_index_file ? `\nAgent bridge: ${displayPath(payload.agent_index_file)}` : ""}`);
      await onDone();
    } catch (error) {
      setOutput(`Bootstrap failed: ${error.message}`);
    } finally {
      setIsBootstrapping(false);
    }
  }

  return (
    <div className="drawerContent">
      <h2>Bootstrap Brain</h2>
        <label>
          <span>Project Folder</span>
          <input
            value={path}
            onChange={(event) => setPath(event.target.value)}
            placeholder={shellKind === "powershell" ? "C:\\path\\to\\my-project" : "/path/to/my-project"}
          />
        </label>
      <label>
        <span>Project Name</span>
        <input value={project} onChange={(event) => setProject(event.target.value)} placeholder="my-project" />
      </label>
      <label className="checkLabel">
        <input type="checkbox" checked={writeAgents} onChange={(event) => setWriteAgents(event.target.checked)} />
        <span>Write the optional AGENTS.md bridge into this project</span>
      </label>
      <button className="primarySmall" onClick={bootstrap} disabled={isBootstrapping}>
        <Rocket size={16} /> {isBootstrapping ? "Building..." : "Build Local Brain"}
      </button>
      {output && <pre className="miniOutput">{output}</pre>}
    </div>
  );
}

function CommandPalette({ command, cliCommand, shellKind, brainDir, onClose, onCopy }) {
  const paletteRef = useRef(null);
  useEffect(() => {
    paletteRef.current?.querySelector("button")?.focus();
  }, []);
  const defaultBrainDir = shellPathArg(
    brainDir || (shellKind === "powershell" ? "$env:USERPROFILE\\Documents\\Rta-Smriti\\brains" : "$HOME/.local/share/rta-smriti/brains"),
    shellKind,
  );
  const commands = [
    ["Copy context-pack command", command],
    ["Open dashboard", `${cliCommand} dashboard --brain-dir ${defaultBrainDir}`],
    ["Check publish readiness", `${cliCommand} publish-readiness --json`],
  ];
  return (
    <div className="paletteBackdrop" role="dialog" aria-modal="true" aria-label="Command palette" onMouseDown={onClose}>
      <section ref={paletteRef} className="commandPalette" onMouseDown={(event) => event.stopPropagation()}>
        <div className="paletteHeader">
          <span>
            <Command size={17} /> Command Palette
          </span>
          <button onClick={onClose}>Close</button>
        </div>
        <div className="paletteList">
          {commands.map(([label, value]) => (
            <button
              key={label}
              aria-label={label}
              onClick={() => {
                onCopy(value, `${label} copied.`);
                onClose();
              }}
            >
              <strong>{label}</strong>
              <code>{value}</code>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
