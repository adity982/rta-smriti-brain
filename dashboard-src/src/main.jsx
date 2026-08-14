import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
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
  Files,
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
const RECEIPT_STORAGE_KEY = "rta-smriti.context-pack-receipts.v1";
const CANVAS_STORAGE_KEY = "rta-smriti.canvas-layout.v1";

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

function safeNumber(value) {
  return Number(value || 0).toLocaleString();
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const payload = await response.json();
  if (!response.ok || payload.status === "error") {
    throw new Error(payload.error?.message || `Request failed: ${path}`);
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

function sourceType(node) {
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

function buildGraph(project, graphData, memories, packText, options = {}) {
  const mode = options.mode || "global";
  const depth = Math.max(1, Math.min(4, Number(options.depth) || 2));
  const nodes = [];
  const edges = [];
  const center = {
    id: "active-task",
    label: project?.project || "Project Brain",
    type: "memory",
    meta: "Active brain",
    x: 50,
    y: 45,
    size: 74,
  };
  nodes.push(center);

  const available = graphData?.nodes || [];
  const words = taskWords(options.task);
  const taskMatches = available.filter((node) => {
    const haystack = `${node.name || ""} ${node.type || ""}`.toLowerCase();
    return [...words].some((word) => haystack.includes(word));
  });
  const candidates = mode === "task" && taskMatches.length ? taskMatches : available;
  const limit = mode === "global" ? 18 : mode === "task" ? 8 + depth * 2 : 7 + depth * 3;
  const selected = candidates.slice(0, limit);
  const sourceNodes = selected.map((node, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(1, selected.length) - Math.PI / 2;
    const ring = 1 + (index % depth);
    const radiusX = 22 + ring * 8;
    const radiusY = 18 + ring * 7;
    return {
      id: `g-${node.id}`,
      label: node.name.split(/[\\/]/).pop() || node.name,
      type: sourceType(node),
      meta: node.type,
      x: 50 + Math.cos(angle) * radiusX,
      y: 45 + Math.sin(angle) * radiusY,
      size: 44,
    };
  });
  nodes.push(...sourceNodes);
  sourceNodes.forEach((node, index) => {
    edges.push({
      id: `edge-${index}`,
      source: "active-task",
      target: node.id,
      label: index % 3 === 0 ? "uses" : index % 3 === 1 ? "mentions" : "evidence",
    });
  });

  const memoryLimit = mode === "task" ? 6 : mode === "global" ? 5 : 4;
  const memoryNodes = memories.slice(0, memoryLimit).map((memory, index) => ({
    id: `m-${memory.id}`,
    label: memory.type,
    type: "memory",
    meta: memory.pramana,
    x: 17 + index * 17,
    y: 78 + (index % 2) * 8,
    size: 38,
    text: memory.text,
  }));
  nodes.push(...memoryNodes);
  memoryNodes.forEach((node, index) => {
    edges.push({ id: `memory-edge-${index}`, source: node.id, target: "active-task", label: "memory" });
  });

  if (packText) {
    nodes.push({ id: "pack", label: "Context Pack", type: "artifact", meta: "generated", x: 80, y: 78, size: 46 });
    edges.push({ id: "pack-edge", source: "active-task", target: "pack", label: "generates" });
  }
  return { nodes, edges };
}

function deriveReferences(graph, node, memories) {
  if (!node) return [];
  const connected = graph.edges
    .filter((edge) => edge.source === node.id || edge.target === node.id)
    .map((edge) => {
      const otherId = edge.source === node.id ? edge.target : edge.source;
      const other = graph.nodes.find((candidate) => candidate.id === otherId);
      return other ? { id: edge.id, label: other.label, relation: edge.label, type: other.type } : null;
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

function filterGraph(graph, query, types) {
  const normalizedQuery = query.trim().toLowerCase();
  const activeTypes = new Set(types);
  const nodes = graph.nodes.filter((node) => {
    const matchesType = activeTypes.has(node.type);
    const haystack = `${node.label} ${node.meta} ${node.text || ""}`.toLowerCase();
    const matchesQuery = !normalizedQuery || haystack.includes(normalizedQuery);
    return matchesType && matchesQuery;
  });
  const ids = new Set(nodes.map((node) => node.id));
  return {
    nodes,
    edges: graph.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target)),
  };
}

function App() {
  const [health, setHealth] = useState(null);
  const [projects, setProjects] = useState([]);
  const [selectedProject, setSelectedProject] = useState(null);
  const [task, setTask] = useState(DEFAULT_TASK);
  const [packText, setPackText] = useState("");
  const [memories, setMemories] = useState([]);
  const [graphData, setGraphData] = useState({ nodes: [], edges: [] });
  const [publish, setPublish] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);
  const [message, setMessage] = useState("");
  const [activeDrawer, setActiveDrawer] = useState("evidence");
  const [isLoading, setIsLoading] = useState(true);
  const [searchOpen, setSearchOpen] = useState(false);
  const [nodeQuery, setNodeQuery] = useState("");
  const [typesOpen, setTypesOpen] = useState(false);
  const [activeTypes, setActiveTypes] = useState(allGraphTypes);
  const [commandOpen, setCommandOpen] = useState(false);
  const [stageExpanded, setStageExpanded] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [viewMode, setViewMode] = useState("graph");
  const [graphMode, setGraphMode] = useState("global");
  const [graphDepth, setGraphDepth] = useState(2);
  const [showLabels, setShowLabels] = useState(true);
  const [showEdges, setShowEdges] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [receipts, setReceipts] = useState(() => readLocalJson(RECEIPT_STORAGE_KEY, []));

  const selectedParams = useMemo(() => {
    if (!selectedProject) return null;
    return { db_path: selectedProject.db_path, project: selectedProject.project };
  }, [selectedProject]);

  const graphOptions = useMemo(() => ({ mode: graphMode, depth: graphDepth, task }), [graphMode, graphDepth, task]);
  const computedGraph = useMemo(
    () => buildGraph(selectedProject, graphData, memories, packText, graphOptions),
    [selectedProject, graphData, memories, packText, graphOptions],
  );
  const visibleGraph = useMemo(() => filterGraph(computedGraph, nodeQuery, activeTypes), [computedGraph, nodeQuery, activeTypes]);
  const activeNode = selectedNode || computedGraph.nodes[0];
  const references = useMemo(() => deriveReferences(computedGraph, activeNode, memories), [computedGraph, activeNode, memories]);
  const readyProjects = projects.filter((project) => project.ready).length;
  const publishReady = publish?.checks?.filter((check) => check.ok).length || 0;
  const publishTotal = publish?.checks?.length || 0;

  async function loadHealth() {
    setIsLoading(true);
    const payload = await api("/api/health");
    setHealth(payload);
    setProjects(payload.projects || []);
    setPublish(payload.publish);
    setSelectedProject((current) => current || payload.projects?.find((project) => project.status === "ok") || payload.projects?.[0] || null);
    setIsLoading(false);
  }

  async function loadProjectDetails(project = selectedProject) {
    if (!project) return;
    const params = { db_path: project.db_path, project: project.project };
    const [memoryPayload, graphPayload] = await Promise.all([
      api(`/api/memories?${qs({ ...params, limit: 40 })}`),
      api(`/api/graph?${qs({ ...params, limit: 80 })}`),
    ]);
    setMemories(memoryPayload.memories || []);
    setGraphData(graphPayload || { nodes: [], edges: [] });
    setSelectedNode(null);
  }

  useEffect(() => {
    loadHealth().catch((error) => {
      setIsLoading(false);
      setMessage(error.message);
    });
  }, []);

  useEffect(() => {
    if (selectedProject) {
      loadProjectDetails(selectedProject).catch((error) => setMessage(error.message));
    }
  }, [selectedProject?.db_path, selectedProject?.project]);

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
      const text = typeof payload.pack === "string" ? payload.pack : JSON.stringify(payload.pack, null, 2);
      setPackText(text);
      const receipt = {
        id: `pack-${Date.now()}`,
        createdAt: new Date().toISOString(),
        project: selectedProject.project,
        task: task.trim(),
        nodes: buildGraph(selectedProject, graphData, memories, text, graphOptions).nodes.length,
        bytes: new Blob([text]).size,
        pack: text,
      };
      const nextReceipts = [receipt, ...receipts].slice(0, 30);
      setReceipts(nextReceipts);
      writeLocalJson(RECEIPT_STORAGE_KEY, nextReceipts);
      setMessage("Context pack generated.");
      setActiveDrawer("receipts");
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

  const command = selectedProject
    ? `rta-brain.cmd --db ${selectedProject.db_path} context-pack "${task || "<task>"}" --project ${selectedProject.project}`
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
            <span>v0.3 Operator Console</span>
          </div>
        </div>
        <div className="topStatus">
          <span className="localBadge">
            <ShieldCheck size={15} /> Local Only
          </span>
          <span className="pathText">Brain Path {health?.brain_dir || "..."}</span>
        </div>
        <div className="topActions">
          <button className="ghostButton" onClick={() => setActiveDrawer("bootstrap")}>
            <Plus size={16} /> New Brain
          </button>
          <button className="ghostButton" onClick={() => setActiveDrawer("publish")}>
            <GitPullRequest size={16} /> Publish
          </button>
          <button className="ghostButton commandButton" onClick={() => setCommandOpen(true)}>
            <Command size={16} /> Cmd Palette
          </button>
          <span className="healthDot" />
        </div>
      </div>

      <div className="layout">
        <aside className="projectRail">
          <div className="railHeader">
            <span>Projects</span>
            <button onClick={loadHealth} aria-label="Refresh projects">
              <RefreshCw size={16} />
            </button>
          </div>
          <div className="projectList">
            {projects.map((project) => (
              <button
                key={`${project.db_path}:${project.project}`}
                className={`projectCard ${selectedProject?.db_path === project.db_path && selectedProject?.project === project.project ? "active" : ""}`}
                onClick={() => setSelectedProject(project)}
              >
                <div className="projectIcon">
                  <Network size={24} />
                </div>
                <div className="projectInfo">
                  <strong>{project.project}</strong>
                  <span>{project.root_path || project.db_file}</span>
                  <div className="progressTrack">
                    <i style={{ width: `${Math.min(100, Math.max(12, (project.sources || project.memories || 1) / Math.max(1, project.sources || project.memories || 1) * 72))}%` }} />
                  </div>
                  <div className="chipLine">
                    <em>{safeNumber(project.sources)} files</em>
                    <em>{safeNumber(project.memories)} memories</em>
                  </div>
                </div>
                <span className={`readyBadge ${project.ready ? "ok" : "warn"}`}>{project.ready ? "Ready" : "Check"}</span>
              </button>
            ))}
          </div>
          <button className="wideGhost" onClick={() => setActiveDrawer("bootstrap")}>
            Bootstrap Checklist <ChevronRight size={16} />
          </button>
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
              <button className={viewMode === "graph" ? "active" : ""} onClick={() => setViewMode("graph")}><GitBranch size={15} /> Graph</button>
              <button className={viewMode === "canvas" ? "active" : ""} onClick={() => setViewMode("canvas")}><MapIcon size={15} /> Canvas</button>
              <button className={viewMode === "bases" ? "active" : ""} onClick={() => setViewMode("bases")}><Table2 size={15} /> Bases</button>
            </div>
            <div className="modeGroup" aria-label="Graph scope">
              {graphModes.map((mode) => (
                <button key={mode} className={graphMode === mode ? "active" : ""} onClick={() => setGraphMode(mode)}>{mode}</button>
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
                    <button key={type} className={activeTypes.includes(type) ? "active" : ""} onClick={() => toggleType(type)}>
                      <i style={{ background: graphPalette[type] }} /> {type}
                    </button>
                  ))}
                </div>
              )}
              {settingsOpen && (
                <GraphSettings depth={graphDepth} setDepth={setGraphDepth} showLabels={showLabels} setShowLabels={setShowLabels} showEdges={showEdges} setShowEdges={setShowEdges} />
              )}
            </div>

          {viewMode === "graph" && <GraphCanvas graph={visibleGraph} selectedNode={activeNode} onSelect={setSelectedNode} query={nodeQuery} showLabels={showLabels} showEdges={showEdges} />}
          {viewMode === "canvas" && <CanvasBoard project={selectedProject} graph={visibleGraph} onSelect={setSelectedNode} onExport={exportView} />}
          {viewMode === "bases" && <BasesView memories={memories} graph={computedGraph} publish={publish} onSelect={setSelectedNode} />}

          <TaskComposer
            task={task}
            setTask={setTask}
            project={selectedProject}
            command={command}
            packText={packText}
            onGenerate={generatePack}
            onCopy={() => copyText(packText || command, packText ? "Context pack copied." : "Command copied.")}
            onReceipts={() => setActiveDrawer("receipts")}
            receiptCount={receipts.length}
            isGenerating={isGenerating}
          />
        </main>

        <aside className="inspector">
          <div className="inspectorTabs">
            <button className={activeDrawer === "evidence" ? "active" : ""} onClick={() => setActiveDrawer("evidence")}>
              <PanelRightOpen size={15} /> Evidence
            </button>
            <button className={activeDrawer === "references" ? "active" : ""} onClick={() => setActiveDrawer("references")}>
              <GitBranch size={15} /> Refs
            </button>
            <button className={activeDrawer === "memory" ? "active" : ""} onClick={() => setActiveDrawer("memory")}>
              <MemoryStick size={15} /> Memory
            </button>
            <button className={activeDrawer === "receipts" ? "active" : ""} onClick={() => setActiveDrawer("receipts")}>
              <Clipboard size={15} /> Packs
            </button>
            <button className={activeDrawer === "publish" ? "active" : ""} onClick={() => setActiveDrawer("publish")}>
              <Rocket size={15} /> Launch
            </button>
          </div>

          {activeDrawer === "evidence" && (
            <EvidenceInspector
              node={activeNode}
              memories={memories}
              project={selectedProject}
              packText={packText}
              publishReady={publishReady}
              publishTotal={publishTotal}
              onCopy={() => copyText(packText || command)}
              onBootstrap={() => setActiveDrawer("bootstrap")}
            />
          )}
          {activeDrawer === "references" && <ReferencesPanel node={activeNode} references={references} onSelect={(reference) => setSelectedNode(computedGraph.nodes.find((node) => node.label === reference.label) || activeNode)} />}
          {activeDrawer === "memory" && <MemoryLedger memories={memories} onReflect={reflect} />}
          {activeDrawer === "receipts" && <ReceiptsPanel receipts={receipts} onCopy={copyText} onClear={() => { setReceipts([]); writeLocalJson(RECEIPT_STORAGE_KEY, []); }} />}
          {activeDrawer === "publish" && <PublishPanel publish={publish} />}
          {activeDrawer === "bootstrap" && <BootstrapPanel health={health} onDone={loadHealth} />}
        </aside>
      </div>

      <footer className="statusBar">
        <span>
          <CheckCircle2 size={14} /> Brain Status: {isLoading ? "Scanning" : "Healthy"}
        </span>
        <span>
          <CircleDot size={14} /> Graph DB: Local SQLite
        </span>
        <span>
          <Activity size={14} /> {message || "Ready"}
        </span>
      </footer>

      {commandOpen && <CommandPalette command={command} onClose={() => setCommandOpen(false)} onCopy={copyText} />}
    </div>
  );
}

function GraphSettings({ depth, setDepth, showLabels, setShowLabels, showEdges, setShowEdges }) {
  return (
    <div className="graphSettings">
      <label>
        <span>Connection depth</span>
        <input type="range" min="1" max="4" value={depth} onChange={(event) => setDepth(Number(event.target.value))} />
        <strong>{depth}</strong>
      </label>
      <label className="toggleLabel"><input type="checkbox" checked={showLabels} onChange={(event) => setShowLabels(event.target.checked)} /> Labels</label>
      <label className="toggleLabel"><input type="checkbox" checked={showEdges} onChange={(event) => setShowEdges(event.target.checked)} /> Connections</label>
    </div>
  );
}

function GraphCanvas({ graph, selectedNode, onSelect, query, showLabels, showEdges }) {
  const nodesById = useMemo(() => new Map(graph.nodes.map((node) => [node.id, node])), [graph.nodes]);
  const canvasRef = useRef(null);
  const [zoom, setZoom] = useState(1);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas && canvas.scrollWidth > canvas.clientWidth) {
      canvas.scrollLeft = (canvas.scrollWidth - canvas.clientWidth) / 2;
    }
  }, [graph.nodes.length]);

  const focus = graph.nodes.length
    ? graph.nodes.reduce(
        (point, node) => ({
          x: point.x + node.x * 10,
          y: point.y + node.y * 6.2,
        }),
        { x: 0, y: 0 },
      )
    : { x: 500 * graph.nodes.length, y: 310 * graph.nodes.length };
  const focusX = graph.nodes.length ? focus.x / graph.nodes.length : 500;
  const focusY = graph.nodes.length ? focus.y / graph.nodes.length : 310;
  const viewWidth = 920 / zoom;
  const viewHeight = 620 / zoom;
  const viewX = focusX - viewWidth / 2;
  const viewY = focusY - viewHeight / 2;

  function centerGraph() {
    setZoom(1);
    window.requestAnimationFrame(() => {
      const canvas = canvasRef.current;
      if (canvas && canvas.scrollWidth > canvas.clientWidth) {
        canvas.scrollLeft = (canvas.scrollWidth - canvas.clientWidth) / 2;
      }
    });
  }

  return (
    <section ref={canvasRef} className="graphCanvas" aria-label="Interactive project brain graph">
      <svg className="graphSvg" viewBox={`${viewX} ${viewY} ${viewWidth} ${viewHeight}`} role="img" aria-label="Rta-Smriti graph">
        <defs>
          <radialGradient id="nodeGlow">
            <stop offset="0%" stopColor="#67e8f9" stopOpacity="0.9" />
            <stop offset="100%" stopColor="#67e8f9" stopOpacity="0" />
          </radialGradient>
          <filter id="softGlow">
            <feGaussianBlur stdDeviation="5" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        <rect width="1000" height="620" rx="16" className="gridRect" />
        {showEdges && graph.edges.map((edge) => {
          const source = nodesById.get(edge.source);
          const target = nodesById.get(edge.target);
          if (!source || !target) return null;
          const x1 = source.x * 10;
          const y1 = source.y * 6.2;
          const x2 = target.x * 10;
          const y2 = target.y * 6.2;
          const active = selectedNode?.id === source.id || selectedNode?.id === target.id;
          return (
            <g key={edge.id} className={active ? "graphEdge active" : "graphEdge"}>
              <line x1={x1} y1={y1} x2={x2} y2={y2} />
              {showLabels && <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 8}>{edge.label}</text>}
            </g>
          );
        })}
        {graph.nodes.map((node) => {
          const color = graphPalette[node.type] || graphPalette.data;
          const active = selectedNode?.id === node.id;
          return (
            <g
              key={node.id}
              className={active ? "graphNode active" : "graphNode"}
              transform={`translate(${node.x * 10}, ${node.y * 6.2})`}
              onClick={() => onSelect(node)}
              tabIndex="0"
              role="button"
            >
              <circle className="nodeAura" r={node.size * 0.8} fill="url(#nodeGlow)" />
              <rect x={-node.size} y={-24} width={node.size * 2} height="48" rx="10" stroke={color} />
              <circle cx={-node.size + 18} cy="0" r="6" fill={color} filter="url(#softGlow)" />
              {showLabels && <text className="nodeLabel" x="-2" y="-4">{node.label.slice(0, 18)}</text>}
              {showLabels && <text className="nodeMeta" x="-2" y="13">{node.meta}</text>}
            </g>
          );
        })}
      </svg>
      {!graph.nodes.length && (
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
        {Object.entries(graphPalette).map(([name, color]) => (
          <span key={name}>
            <i style={{ background: color }} /> {name}
          </span>
        ))}
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

  const cards = graph.nodes.slice(0, 16);
  return (
    <section ref={boardRef} className="canvasBoard" aria-label="Spatial project canvas">
      <div className="canvasHeader">
        <span><MapIcon size={16} /> Spatial Canvas</span>
        <button onClick={() => onExport(`${project?.project || "rta-smriti"}-canvas.json`, { project: project?.project, positions, nodes: cards })}><Download size={15} /> Export JSON</button>
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
          <button key={node.id} className="canvasCard" style={{ left: `${position.x}%`, top: `${position.y}%`, borderColor: graphPalette[node.type] }} onPointerDown={(event) => beginDrag(event, node, index)} onDoubleClick={() => onSelect(node)}>
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

function BasesView({ memories, graph, publish, onSelect }) {
  const [table, setTable] = useState("memory");
  const [query, setQuery] = useState("");
  const normalized = query.toLowerCase();
  const memoryRows = memories.filter((item) => `${item.type} ${item.pramana} ${item.text}`.toLowerCase().includes(normalized));
  const fileRows = graph.nodes.filter((item) => item.id !== "active-task" && item.id !== "pack" && `${item.label} ${item.meta}`.toLowerCase().includes(normalized));
  return (
    <section className="basesView" aria-label="Typed project data tables">
      <div className="basesToolbar">
        <div className="viewSwitch">
          <button className={table === "memory" ? "active" : ""} onClick={() => setTable("memory")}>Memories</button>
          <button className={table === "files" ? "active" : ""} onClick={() => setTable("files")}>Sources</button>
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

function TaskComposer({ task, setTask, project, command, packText, onGenerate, onCopy, onReceipts, receiptCount, isGenerating }) {
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
            <select value="codex" onChange={() => {}}>
              <option>Codex</option>
            </select>
          </label>
          <label>
            <span>Objective</span>
            <input value={task} onChange={(event) => setTask(event.target.value)} />
          </label>
          <label>
            <span>Command Bridge</span>
            <code>{command}</code>
          </label>
        </div>
        <div className="packPreview">
          <div className="freshRing">
            <strong>{project?.ready ? "95%" : "68%"}</strong>
            <span>{project?.ready ? "Fresh" : "Check"}</span>
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

function EvidenceInspector({ node, memories, project, packText, publishReady, publishTotal, onCopy, onBootstrap }) {
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
      <FreshnessBars project={project} />
      <RepoTree project={project} />
      <section className="publishMini">
        <div>
          <span>Publish Readiness</span>
          <strong>
            {publishReady}/{publishTotal || "?"}
          </strong>
        </div>
        <button onClick={onCopy}>
          <Clipboard size={16} /> {packText ? "Copy to Codex" : "Copy Command"}
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
          <button key={reference.id} onClick={() => onSelect(reference)}>
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

function FreshnessBars({ project }) {
  const bars = [
    ["Source", project?.ready ? 96 : 70],
    ["Memories", Math.min(98, 70 + (project?.memories || 0) * 4)],
    ["Graph", project?.edges ? 94 : 45],
    ["Agents", project?.ready ? 90 : 50],
  ];
  return (
    <section>
      <div className="sectionHeader">
        <span>Freshness</span>
        <em>{project?.ready ? "Fresh" : "Needs Check"}</em>
      </div>
      <div className="bars">
        {bars.map(([label, value]) => (
          <div key={label}>
            <span>{label}</span>
            <i>
              <b style={{ width: `${value}%` }} />
            </i>
            <em>{value}%</em>
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
      <p className="drawerIntro">A local history of what context was assembled, for which project, and when.</p>
      <div className="receiptList">
        {receipts.map((receipt) => (
          <article key={receipt.id}>
            <div><strong>{receipt.project}</strong><time>{new Date(receipt.createdAt).toLocaleString()}</time></div>
            <p>{receipt.task}</p>
            <span>{receipt.nodes} nodes | {(receipt.bytes / 1024).toFixed(1)} KB</span>
            <button onClick={() => onCopy(receipt.pack, "Saved context pack copied.")}><Clipboard size={14} /> Copy</button>
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

function BootstrapPanel({ health, onDone }) {
  const [path, setPath] = useState("");
  const [project, setProject] = useState("");
  const [output, setOutput] = useState("");

  async function bootstrap() {
    if (!path.trim() || !project.trim()) {
      setOutput("Enter a project folder and project name.");
      return;
    }
    try {
      setOutput("Building local brain...");
      const payload = await api("/api/bootstrap", {
        method: "POST",
        body: JSON.stringify({ path, project, brain_dir: health?.brain_dir, write_agents: true }),
      });
      setOutput(JSON.stringify(payload, null, 2));
      await onDone();
    } catch (error) {
      setOutput(`Bootstrap failed: ${error.message}`);
    }
  }

  return (
    <div className="drawerContent">
      <h2>Bootstrap Brain</h2>
        <label>
          <span>Project Folder</span>
          <input value={path} onChange={(event) => setPath(event.target.value)} placeholder="C:\\path\\to\\my-project" />
        </label>
      <label>
        <span>Project Name</span>
        <input value={project} onChange={(event) => setProject(event.target.value)} placeholder="my-project" />
      </label>
      <button className="primarySmall" onClick={bootstrap}>
        <Rocket size={16} /> Build Local Brain
      </button>
      {output && <pre className="miniOutput">{output}</pre>}
    </div>
  );
}

function CommandPalette({ command, onClose, onCopy }) {
  const defaultBrainDir = command.includes("--db ") ? ".\\.rta-smriti" : "%USERPROFILE%\\Documents\\Rta-Smriti\\brains";
  const commands = [
    ["Copy context-pack command", command],
    ["Open dashboard", `rta-brain.cmd dashboard --brain-dir ${defaultBrainDir}`],
    ["Check publish readiness", "python rta-brain.py publish-readiness --json"],
  ];
  return (
    <div className="paletteBackdrop" role="dialog" aria-modal="true" aria-label="Command palette">
      <section className="commandPalette">
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
