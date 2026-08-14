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
  FileCode2,
  Files,
  FolderTree,
  GitBranch,
  GitPullRequest,
  HardDrive,
  Layers3,
  Maximize2,
  MemoryStick,
  Network,
  PanelRightOpen,
  Plus,
  RefreshCw,
  Rocket,
  Search,
  ShieldCheck,
  Sparkles,
  TerminalSquare,
  Zap,
} from "lucide-react";
import "./styles.css";

const DEFAULT_TASK = "Prepare this project for a focused coding task";

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

function buildGraph(project, graphData, memories, packText) {
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

  const sourceNodes = (graphData?.nodes || []).slice(0, 9).map((node, index) => {
    const angle = (Math.PI * 2 * index) / 9 - Math.PI / 2;
    const radiusX = index % 2 === 0 ? 31 : 39;
    const radiusY = index % 2 === 0 ? 27 : 33;
    const type = node.type === "file" ? "file" : node.type === "symbol" ? "docs" : node.type === "import" ? "config" : "data";
    return {
      id: `g-${node.id}`,
      label: node.name.split(/[\\/]/).pop() || node.name,
      type,
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

  const memoryNodes = memories.slice(0, 4).map((memory, index) => ({
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

  const selectedParams = useMemo(() => {
    if (!selectedProject) return null;
    return { db_path: selectedProject.db_path, project: selectedProject.project };
  }, [selectedProject]);

  const computedGraph = useMemo(() => buildGraph(selectedProject, graphData, memories, packText), [selectedProject, graphData, memories, packText]);
  const visibleGraph = useMemo(() => filterGraph(computedGraph, nodeQuery, activeTypes), [computedGraph, nodeQuery, activeTypes]);
  const activeNode = selectedNode || computedGraph.nodes[0];
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
      setMessage("Context pack generated.");
      setActiveDrawer("evidence");
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
            <span>v0.2 React Console</span>
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
            <button
              className="modeButton"
              onClick={() => {
                setNodeQuery("");
                setActiveTypes(allGraphTypes);
                setSearchOpen(false);
                setTypesOpen(false);
              }}
            >
              <GitBranch size={16} /> Brain Graph
            </button>
            <button className={searchOpen ? "toolButton active" : "toolButton"} onClick={() => setSearchOpen((value) => !value)}>
              <Search size={16} /> Search nodes
            </button>
            <button className={typesOpen ? "toolButton active" : "toolButton"} onClick={() => setTypesOpen((value) => !value)}>
              <Layers3 size={16} /> Types
            </button>
            <button className="toolButton" onClick={() => setStageExpanded((value) => !value)} aria-label={stageExpanded ? "Exit expanded graph" : "Expand graph"}>
              <Maximize2 size={16} />
            </button>
          </div>

          <div className={searchOpen || typesOpen ? "graphFilters" : "graphFilters collapsed"}>
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
            </div>

          <GraphCanvas graph={visibleGraph} selectedNode={activeNode} onSelect={setSelectedNode} query={nodeQuery} />

          <TaskComposer
            task={task}
            setTask={setTask}
            project={selectedProject}
            command={command}
            packText={packText}
            onGenerate={generatePack}
            onCopy={() => copyText(packText || command, packText ? "Context pack copied." : "Command copied.")}
            isGenerating={isGenerating}
          />
        </main>

        <aside className="inspector">
          <div className="inspectorTabs">
            <button className={activeDrawer === "evidence" ? "active" : ""} onClick={() => setActiveDrawer("evidence")}>
              <PanelRightOpen size={15} /> Evidence
            </button>
            <button className={activeDrawer === "memory" ? "active" : ""} onClick={() => setActiveDrawer("memory")}>
              <MemoryStick size={15} /> Memory
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
          {activeDrawer === "memory" && <MemoryLedger memories={memories} onReflect={reflect} />}
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

function GraphCanvas({ graph, selectedNode, onSelect, query }) {
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
        {graph.edges.map((edge) => {
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
              <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 8}>
                {edge.label}
              </text>
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
              <text className="nodeLabel" x="-2" y="-4">
                {node.label.slice(0, 18)}
              </text>
              <text className="nodeMeta" x="-2" y="13">
                {node.meta}
              </text>
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

function TaskComposer({ task, setTask, project, command, packText, onGenerate, onCopy, isGenerating }) {
  return (
    <section className="taskComposer">
      <div className="composerTitle">
        <span>
          <Sparkles size={16} /> Task Composer
        </span>
        <button onClick={onCopy}>
          <Clipboard size={15} /> {packText ? "Copy Pack" : "Copy Command"}
        </button>
      </div>
      <div className="composerGrid">
        <div className="formStack">
          <label>
            <span>Target Agent</span>
            <select value="codex" readOnly>
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
  return (
    <div className="drawerContent">
      <h2>Memory Ledger</h2>
      <button className="primarySmall" onClick={onReflect}>
        <RefreshCw size={16} /> Reflect Memories
      </button>
      <div className="ledgerList">
        {memories.map((memory) => (
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
