import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowRight,
  BrainCircuit,
  Check,
  ChevronRight,
  CircleDot,
  Clipboard,
  Code2,
  Database,
  ExternalLink,
  FileCode2,
  Github,
  GitBranch,
  LockKeyhole,
  Menu,
  Network,
  Play,
  Search,
  ShieldCheck,
  Sparkles,
  TerminalSquare,
  X,
  Zap,
} from "lucide-react";
import "./styles.css";

const repositoryUrl = import.meta.env.VITE_REPOSITORY_URL || "https://github.com/sulabhdubey/rta-smriti-brain";

const installCommand = "pip install -e .";
const agents = ["Codex", "Claude Code", "Cursor", "Copilot", "Gemini CLI", "Aider", "Cline", "Any MCP agent"];
const pramana = {
  pratyaksha: ["Observed", "Code, tests, files, and tool output", "#5eead4"],
  sabda: ["Trusted", "Human instruction and authoritative documentation", "#38bdf8"],
  anumana: ["Inferred", "Reasoned conclusions with explicit uncertainty", "#fbbf24"],
  smriti: ["Remembered", "Prior project knowledge and session handoffs", "#a78bfa"],
  kalpana: ["Hypothesized", "Ideas and possibilities that still need proof", "#f472b6"],
};

function Brand({ compact = false }) {
  return (
    <a className="brand" href="#top" aria-label="Rta-Smriti Brain home">
      <span className="brandMark"><BrainCircuit size={compact ? 18 : 22} /></span>
      <span><strong>Rta-Smriti</strong>{!compact && <small>Local AI project brain</small>}</span>
    </a>
  );
}

function CopyButton({ value, label = "Copy install command" }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  };
  return <button className="iconButton" onClick={copy} aria-label={label} title={label}>{copied ? <Check size={17} /> : <Clipboard size={17} />}</button>;
}

function HeroGraph() {
  const nodes = useMemo(() => [
    [13, 35, "file"], [24, 22, "memory"], [34, 43, "evidence"], [48, 18, "file"],
    [57, 37, "memory"], [69, 25, "evidence"], [81, 46, "file"], [91, 30, "memory"],
  ], []);
  return (
    <svg className="heroGraph" viewBox="0 0 100 60" aria-hidden="true">
      <path d="M13 35L24 22L34 43L48 18L57 37L69 25L81 46L91 30" />
      <path d="M13 35L34 43M24 22L48 18M48 18L69 25M57 37L81 46M69 25L91 30" />
      {nodes.map(([x, y, type], index) => <circle key={index} cx={x} cy={y} r={type === "evidence" ? 1.5 : 1} data-type={type} />)}
    </svg>
  );
}

function Hero() {
  return (
    <section className="hero" id="top">
      <img className="heroImage" src="./assets/dashboard-hero.png" alt="Rta-Smriti operator console showing a project memory graph" />
      <div className="heroScrim" />
      <HeroGraph />
      <div className="heroContent shell">
        <div className="eyebrow"><LockKeyhole size={14} /> Local-first. Agent-neutral. Evidence-aware.</div>
        <h1>Rta-Smriti Brain</h1>
        <p className="heroLead">Give every software project a private memory that survives new chats, agent switches, and context compaction.</p>
        <div className="heroActions">
          <a className="primaryAction" href="#install"><TerminalSquare size={18} /> Get started <ArrowRight size={17} /></a>
          <a className="secondaryAction" href="#demo"><Play size={17} /> Watch the product</a>
        </div>
        <div className="heroProof" aria-label="Product proof points">
          <span><strong>6</strong> project brains tested</span>
          <span><strong>26,482</strong> files in largest test</span>
          <span><strong>0</strong> cloud accounts required</span>
        </div>
      </div>
      <a className="nextCue" href="#why" aria-label="Continue to product story"><span>Why it exists</span><ChevronRight size={15} /></a>
    </section>
  );
}

function Header() {
  const [open, setOpen] = useState(false);
  return (
    <header className="siteHeader">
      <div className="shell headerInner">
        <Brand />
        <nav className={open ? "siteNav open" : "siteNav"} aria-label="Main navigation">
          <a href="#product" onClick={() => setOpen(false)}>Product</a>
          <a href="#architecture" onClick={() => setOpen(false)}>Architecture</a>
          <a href="#difference" onClick={() => setOpen(false)}>Why different</a>
          <a href="#install" onClick={() => setOpen(false)}>Install</a>
          {repositoryUrl && <a className="navGithub" href={repositoryUrl} onClick={() => setOpen(false)}><Github size={16} /> Get source</a>}
        </nav>
        <button className="menuButton" onClick={() => setOpen((value) => !value)} aria-label={open ? "Close menu" : "Open menu"}>{open ? <X /> : <Menu />}</button>
      </div>
    </header>
  );
}

function ProblemBand() {
  return (
    <section className="problemBand" id="why">
      <div className="shell problemGrid">
        <div>
          <span className="sectionIndex">01 / THE PROBLEM</span>
          <h2>Every new AI chat forgets the project.</h2>
        </div>
        <div className="problemCopy">
          <p>Architecture, release rules, prior failures, and human decisions disappear across sessions. Developers pay the tax in repeated explanations, broad repo scans, and tokens spent rebuilding context.</p>
          <p className="solutionLine"><Sparkles size={19} /> Rta-Smriti moves memory out of the chat and into the project.</p>
        </div>
      </div>
    </section>
  );
}

const featureTabs = [
  ["graph", "Graph", Network, "See files, imports, symbols, memories, and evidence as one inspectable project system."],
  ["files", "Files", FileCode2, "Browse the real indexed tree, preview source, and add exact paths to the next task."],
  ["memory", "Memory", Database, "Keep durable decisions and constraints separate from transient chat history."],
  ["packs", "Context Packs", Zap, "Compile only the evidence relevant to the next agent objective."],
];

function ProductSection() {
  const [active, setActive] = useState("graph");
  const current = featureTabs.find(([id]) => id === active);
  return (
    <section className="productSection" id="product">
      <div className="shell">
        <div className="sectionHeading">
          <span className="sectionIndex">02 / THE OPERATOR CONSOLE</span>
          <h2>Memory you can inspect, not magic you have to trust.</h2>
        </div>
        <div className="featureTabs" role="tablist" aria-label="Product views">
          {featureTabs.map(([id, label, Icon]) => <button key={id} role="tab" aria-selected={active === id} onClick={() => setActive(id)}><Icon size={16} /> {label}</button>)}
        </div>
        <div className="productFrame">
          <img src={active === "files" ? "./assets/file-explorer.png" : "./assets/dashboard-hero.png"} alt={active === "files" ? "Indexed file explorer and source preview" : "Interactive project brain graph"} />
          <div className="frameCaption"><span>{current[1]}</span><p>{current[3]}</p></div>
        </div>
      </div>
    </section>
  );
}

function Architecture() {
  const stages = [
    ["Inputs", "Repositories, threads, decisions", GitBranch],
    ["Local brain", "SQLite, FTS5, graph, evidence", Database],
    ["Context compiler", "Bounded, task-specific retrieval", Sparkles],
    ["Any agent", "Paste, CLI, skill, or MCP", BrainCircuit],
  ];
  return (
    <section className="architecture" id="architecture">
      <div className="shell">
        <div className="sectionHeading rowHeading">
          <div><span className="sectionIndex">03 / ARCHITECTURE</span><h2>Small enough to understand. Strong enough to reuse.</h2></div>
          <p>Deterministic local infrastructure first. Models and embeddings remain optional layers, not runtime dependencies.</p>
        </div>
        <div className="architectureFlow">
          {stages.map(([title, copy, Icon], index) => (
            <React.Fragment key={title}>
              <article><span><Icon size={23} /></span><strong>{title}</strong><p>{copy}</p></article>
              {index < stages.length - 1 && <ArrowRight className="flowArrow" size={20} />}
            </React.Fragment>
          ))}
        </div>
        <div className="architectureFacts">
          <span><Check size={15} /> Python 3.11+</span><span><Check size={15} /> Zero runtime dependencies</span><span><Check size={15} /> Local SQLite</span><span><Check size={15} /> Stdio MCP</span><span><Check size={15} /> Packaged React console</span>
        </div>
      </div>
    </section>
  );
}

function PramanaSection() {
  const [active, setActive] = useState("pratyaksha");
  const [label, copy, color] = pramana[active];
  return (
    <section className="pramanaSection">
      <div className="shell pramanaGrid">
        <div>
          <span className="sectionIndex">04 / EVIDENCE-AWARE MEMORY</span>
          <h2>A fact, an instruction, and a hypothesis are not the same thing.</h2>
          <p>Rta-Smriti uses a Vedic-inspired pramana model to preserve how knowledge became known, not just what the text says.</p>
        </div>
        <div className="pramanaControl">
          <div className="pramanaTabs" role="tablist" aria-label="Pramana evidence classes">
            {Object.keys(pramana).map((key) => <button key={key} aria-selected={active === key} onClick={() => setActive(key)}>{key}</button>)}
          </div>
          <div className="pramanaResult" style={{ "--pramana-color": color }}>
            <CircleDot size={28} />
            <span><strong>{label}</strong><p>{copy}</p></span>
          </div>
        </div>
      </div>
    </section>
  );
}

function Difference() {
  const rows = [
    ["Plain second brain", "Notes", "Repo evidence + decisions + handoffs"],
    ["Code indexer", "File search", "Durable memory + task-specific packs"],
    ["Vector memory", "Similar text", "Evidence class + freshness + inspectability"],
    ["Agent chat memory", "One vendor", "Agent-neutral project layer"],
    ["MCP memory server", "Tools only", "CLI + MCP + console + bootstrap + checks"],
  ];
  return (
    <section className="difference" id="difference">
      <div className="shell">
        <div className="sectionHeading rowHeading">
          <div><span className="sectionIndex">05 / THE DIFFERENCE</span><h2>Not another notes app. Not another black-box memory.</h2></div>
          <p>The product combines repository structure, durable human knowledge, session handoffs, evidence strength, and agent-ready output.</p>
        </div>
        <div className="comparisonTable" role="table" aria-label="Rta-Smriti comparison">
          <div className="comparisonHead" role="row"><span>Category</span><span>Usually stops at</span><span>Rta-Smriti adds</span></div>
          {rows.map((row) => <div className="comparisonRow" role="row" key={row[0]}>{row.map((cell, i) => <span key={cell} className={i === 2 ? "highlightCell" : ""}>{i === 2 && <Check size={15} />}{cell}</span>)}</div>)}
        </div>
      </div>
    </section>
  );
}

function AgentRail() {
  return <section className="agentRail"><div className="shell"><span>ONE BRAIN</span><div>{agents.map((agent) => <strong key={agent}>{agent}</strong>)}</div><span>ANY AGENT</span></div></section>;
}

function Demo() {
  return (
    <section className="demoSection" id="demo">
      <div className="shell demoGrid">
        <div>
          <span className="sectionIndex">06 / REAL WORKFLOW</span>
          <h2>From a large repository to one focused handoff.</h2>
          <ol>
            <li><span>1</span>Select the project brain.</li>
            <li><span>2</span>Inspect files, evidence, and memory.</li>
            <li><span>3</span>Describe one concrete objective.</li>
            <li><span>4</span>Generate a pack for any agent.</li>
          </ol>
        </div>
        <div className="demoVisual">
          <video controls preload="metadata" poster="./assets/rta-smriti-launch-poster.png" aria-label="60-second Rta-Smriti Brain product tour">
            <source src="./assets/rta-smriti-launch-demo.mp4" type="video/mp4" />
            Your browser does not support embedded video. <a href="./assets/rta-smriti-launch-demo.mp4">Open the MP4 demo.</a>
          </video>
        </div>
      </div>
    </section>
  );
}

function Install() {
  return (
    <section className="installSection" id="install">
      <div className="shell installGrid">
        <div><span className="sectionIndex">07 / START LOCAL</span><h2>Your first project brain is one command away.</h2><p>Clone the repository, install locally, then bootstrap one private SQLite brain per project.</p></div>
        <div className="terminalBlock">
          <div className="terminalHeader"><span><i /> <i /> <i /></span><strong>PowerShell</strong><CopyButton value={installCommand} /></div>
          <code><span>$</span> {installCommand}</code>
          <code><span>$</span> rta-brain bootstrap-project C:\path\to\project --project my-project --write-agents</code>
          <code><span>$</span> rta-brain dashboard</code>
        </div>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer><div className="shell footerGrid"><Brand compact /><p>Project memory that stays with the project.</p><div><a href="#install">Install</a><a href="#difference">Security & privacy</a><a href="./LICENSE.txt">MIT License</a>{repositoryUrl && <a href={repositoryUrl}>Get source <ExternalLink size={13} /></a>}</div></div></footer>
  );
}

function LandingPage() {
  useEffect(() => {
    const observer = new IntersectionObserver((entries) => entries.forEach((entry) => entry.target.classList.toggle("revealed", entry.isIntersecting)), { threshold: 0.12 });
    document.querySelectorAll("section:not(.hero)").forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, []);
  return <><Header /><main><Hero /><ProblemBand /><ProductSection /><Architecture /><PramanaSection /><Difference /><AgentRail /><Demo /><Install /></main><Footer /></>;
}

const assetContent = {
  social: ["Give every project a memory.", "Private, evidence-aware project memory for any AI coding agent.", "dashboard"],
  "gallery-1": ["Your AI starts with project memory.", "Repo evidence, durable decisions, and long-session handoffs — compiled locally for the next task.", "dashboard"],
  "gallery-2": ["One brain. Any agent.", "Codex · Claude Code · Cursor · Copilot · Gemini CLI · Aider · Cline · MCP", "agents"],
  "gallery-3": ["Evidence, not vibes.", "Observed facts, trusted instructions, inferences, memories, and hypotheses stay meaningfully different.", "pramana"],
  "gallery-4": ["26,482 files. One focused pack.", "Bounded local retrieval turns a large repository into the context your next agent task actually needs.", "performance"],
};

function AssetBoard({ name }) {
  if (name === "thumbnail") return <div className="assetCanvas thumbnailAsset"><Brand compact /><BrainCircuit /><strong>Rta-Smriti</strong><span>Local AI project brain</span></div>;
  const content = assetContent[name] || assetContent["gallery-1"];
  const assetClass = name === "social" ? "galleryAsset dashboard socialAsset" : `galleryAsset ${content[2]}`;
  return (
    <div className={`assetCanvas ${assetClass}`}>
      <div className="assetTop"><Brand compact /><span>LOCAL ONLY</span></div>
      <div className="assetCopy"><small>RTA-SMRITI BRAIN</small><h1>{content[0]}</h1><p>{content[1]}</p></div>
      {content[2] === "dashboard" && <img src="./assets/dashboard-hero.png" alt="" />}
      {content[2] === "agents" && <div className="assetAgentOrbit"><BrainCircuit />{agents.slice(0, 7).map((agent, i) => <span key={agent} style={{ "--i": i }}>{agent}</span>)}</div>}
      {content[2] === "pramana" && <div className="assetPramana">{Object.entries(pramana).map(([key, value]) => <span key={key} style={{ "--color": value[2] }}><i />{key}<small>{value[0]}</small></span>)}</div>}
      {content[2] === "performance" && <div className="assetMetric"><span><strong>26,482</strong>indexed files</span><ArrowRight /><span><strong>1</strong>task-specific pack</span></div>}
      <div className="assetFooter"><span>Private SQLite · FTS5 · Graph · MCP</span><strong>rta-smriti</strong></div>
    </div>
  );
}

const asset = new URLSearchParams(window.location.search).get("asset");
createRoot(document.getElementById("root")).render(asset ? <AssetBoard name={asset} /> : <LandingPage />);
