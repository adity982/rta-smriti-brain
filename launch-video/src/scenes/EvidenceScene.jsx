import { interpolate, useCurrentFrame } from "remotion";
import { Brand, Eyebrow, Reveal, Scene, palette } from "../ui";

const evidence = [["pratyaksha", "Observed", "#5eead4"], ["sabda", "Trusted", "#38bdf8"], ["anumana", "Inferred", "#fbbf24"], ["smriti", "Remembered", "#a78bfa"], ["kalpana", "Hypothesized", "#f472b6"]];

export const EvidenceScene = () => {
  const frame = useCurrentFrame();
  return <Scene><Brand />
    <div style={{ position: "absolute", left: 110, top: 250, width: 780 }}><Reveal><Eyebrow>Pramana + Action Gate</Eyebrow></Reveal><Reveal from={14}><h1 style={{ margin: "18px 0 24px", fontSize: 96, lineHeight: .98 }}>Evidence<br />before action.</h1></Reveal><Reveal from={34}><p style={{ margin: 0, color: palette.muted, fontSize: 33, lineHeight: 1.45 }}>Trusted constraints can warn or block. Low-trust memory can inform, but never block by itself.</p></Reveal></div>
    <div style={{ position: "absolute", right: 120, top: 225, width: 700 }}>
      {evidence.map(([name,label,color], index) => <div key={name} style={{ display: "grid", gridTemplateColumns: "26px 1fr auto", alignItems: "center", minHeight: 110, borderBottom: `1px solid ${palette.line}`, fontSize: 28, opacity: interpolate(frame, [35 + index * 13, 54 + index * 13], [0,1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }), translate: `${interpolate(frame, [35 + index * 13, 54 + index * 13], [28,0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })}px 0` }}><i style={{ width: 12, height: 12, borderRadius: "50%", background: color, boxShadow: `0 0 20px ${color}` }} /><code style={{ color: palette.text }}>{name}</code><span style={{ color: palette.muted }}>{label}</span></div>)}
    </div>
  </Scene>;
};
