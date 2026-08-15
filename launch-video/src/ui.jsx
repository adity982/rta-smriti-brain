import { AbsoluteFill, Easing, interpolate, useCurrentFrame } from "remotion";

export const palette = {
  bg: "#050a10",
  panel: "#08131d",
  text: "#edf7ff",
  muted: "#8da5b7",
  teal: "#5eead4",
  cyan: "#38bdf8",
  amber: "#fbbf24",
  violet: "#a78bfa",
  line: "#17303e",
};

export const Scene = ({ children }) => (
  <AbsoluteFill style={{ backgroundColor: palette.bg, color: palette.text, fontFamily: "Inter, Segoe UI, Arial, sans-serif", overflow: "hidden" }}>
    <Grid />
    {children}
  </AbsoluteFill>
);

export const Grid = () => (
  <AbsoluteFill style={{ opacity: 0.32, backgroundImage: "linear-gradient(rgba(56,189,248,.06) 1px, transparent 1px), linear-gradient(90deg, rgba(56,189,248,.06) 1px, transparent 1px)", backgroundSize: "54px 54px" }} />
);

export const Brand = () => (
  <div style={{ position: "absolute", left: 84, top: 64, display: "flex", alignItems: "center", gap: 14, fontSize: 24, fontWeight: 800 }}>
    <span style={{ display: "grid", placeItems: "center", width: 42, height: 42, border: `1px solid ${palette.teal}`, borderRadius: 8, color: palette.teal }}>R</span>
    Rta-Smriti Brain
  </div>
);

export const Eyebrow = ({ children }) => <div style={{ color: palette.teal, fontSize: 20, fontWeight: 850, textTransform: "uppercase" }}>{children}</div>;

export const Reveal = ({ children, from = 0, y = 24, style = {} }) => {
  const frame = useCurrentFrame();
  return <div style={{ ...style, opacity: interpolate(frame, [from, from + 22], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.bezier(.16, 1, .3, 1) }), translate: `0 ${interpolate(frame, [from, from + 22], [y, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.bezier(.16, 1, .3, 1) })}px` }}>{children}</div>;
};

export const PulseLine = ({ top, left, width, color = palette.cyan, delay = 0 }) => {
  const frame = useCurrentFrame();
  return <div style={{ position: "absolute", top, left, width, height: 1, backgroundColor: palette.line, overflow: "hidden", rotate: "-8deg" }}><span style={{ display: "block", width: 90, height: 1, backgroundColor: color, boxShadow: `0 0 16px ${color}`, translate: `${interpolate(frame, [delay, delay + 100], [-120, width + 100], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })}px 0` }} /></div>;
};
