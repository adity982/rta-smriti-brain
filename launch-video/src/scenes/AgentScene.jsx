import { interpolate, useCurrentFrame } from "remotion";
import { Brand, Eyebrow, Reveal, Scene, palette } from "../ui";

const agents = ["Codex", "Claude Code", "Cursor", "Copilot", "Gemini CLI", "Aider", "Cline", "Any MCP agent"];

export const AgentScene = () => {
  const frame = useCurrentFrame();
  return <Scene><Brand />
    <div style={{ position: "absolute", left: 110, top: 260, width: 740 }}><Reveal><Eyebrow>Agent-neutral by design</Eyebrow></Reveal><Reveal from={14}><h1 style={{ margin: "18px 0 24px", fontSize: 100, lineHeight: .98 }}>One brain.<br />Any agent.</h1></Reveal><Reveal from={34}><p style={{ margin: 0, color: palette.muted, fontSize: 34, lineHeight: 1.45 }}>Paste a pack, call the CLI, use a skill, or connect through MCP.</p></Reveal></div>
    <div style={{ position: "absolute", right: 150, top: 190, width: 700, height: 700, border: `1px solid ${palette.line}`, borderRadius: "50%" }}>
      <div style={{ position: "absolute", left: 275, top: 275, display: "grid", placeItems: "center", width: 150, height: 150, borderRadius: "50%", border: `1px solid ${palette.teal}`, background: palette.panel, color: palette.teal, fontSize: 48, fontWeight: 900 }}>R</div>
      {agents.map((agent,index) => { const angle = index * Math.PI / 4; const x = 305 + Math.cos(angle) * 290; const y = 305 + Math.sin(angle) * 290; return <div key={agent} style={{ position: "absolute", left: x, top: y, width: 150, padding: "15px 8px", border: `1px solid ${palette.line}`, borderRadius: 6, background: palette.panel, textAlign: "center", fontSize: 20, opacity: interpolate(frame,[35+index*7,52+index*7],[0,1],{extrapolateLeft:"clamp",extrapolateRight:"clamp"}), scale: interpolate(frame,[35+index*7,52+index*7],[.8,1],{extrapolateLeft:"clamp",extrapolateRight:"clamp"}) }}>{agent}</div>; })}
    </div>
  </Scene>;
};
