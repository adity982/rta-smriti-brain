import { useCurrentFrame, interpolate } from "remotion";
import { Brand, Eyebrow, Reveal, Scene, palette } from "../ui";

export const ProblemScene = () => {
  const frame = useCurrentFrame();
  const items = ["Architecture", "Agent activity", "Release rules", "Human decisions"];
  return <Scene><Brand />
    <div style={{ position: "absolute", left: 110, top: 260, width: 1080 }}>
      <Reveal><Eyebrow>New chat. Same project.</Eyebrow></Reveal>
      <Reveal from={14}><h1 style={{ margin: "20px 0 24px", fontSize: 112, lineHeight: .96, letterSpacing: 0 }}>Your AI forgot<br />the project again.</h1></Reveal>
      <Reveal from={36}><p style={{ margin: 0, width: 850, color: palette.muted, fontSize: 38, lineHeight: 1.4 }}>Context compaction should not erase what happened, what was verified, or what the next agent must not repeat.</p></Reveal>
    </div>
    <div style={{ position: "absolute", right: 110, top: 225, display: "grid", gap: 18 }}>
      {items.map((item, index) => <div key={item} style={{ width: 430, padding: "22px 26px", border: `1px solid ${palette.line}`, background: palette.panel, color: palette.muted, fontSize: 27, opacity: interpolate(frame, [55 + index * 12, 70 + index * 12, 180, 235], [0, 1, 1, .2], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }), translate: `${interpolate(frame, [55 + index * 12, 72 + index * 12], [25, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })}px 0` }}>{item}</div>)}
    </div>
  </Scene>;
};
