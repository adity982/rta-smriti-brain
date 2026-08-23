import { TransitionSeries, linearTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { ProblemScene } from "./scenes/ProblemScene";
import { BrainScene } from "./scenes/BrainScene";
import { CaptureScene } from "./scenes/CaptureScene";
import { EvidenceScene } from "./scenes/EvidenceScene";
import { AgentScene } from "./scenes/AgentScene";
import { ContextScene } from "./scenes/ContextScene";
import { FinaleScene } from "./scenes/FinaleScene";

export const LaunchVideo = () => (
  <TransitionSeries>
    <TransitionSeries.Sequence durationInFrames={230} name="The context problem"><ProblemScene /></TransitionSeries.Sequence>
    <TransitionSeries.Transition presentation={fade()} timing={linearTiming({ durationInFrames: 20 })} />
    <TransitionSeries.Sequence durationInFrames={280} name="The local continuity system"><BrainScene /></TransitionSeries.Sequence>
    <TransitionSeries.Transition presentation={fade()} timing={linearTiming({ durationInFrames: 20 })} />
    <TransitionSeries.Sequence durationInFrames={300} name="Universal Capture"><CaptureScene /></TransitionSeries.Sequence>
    <TransitionSeries.Transition presentation={fade()} timing={linearTiming({ durationInFrames: 20 })} />
    <TransitionSeries.Sequence durationInFrames={250} name="Bitemporal evidence"><EvidenceScene /></TransitionSeries.Sequence>
    <TransitionSeries.Transition presentation={fade()} timing={linearTiming({ durationInFrames: 20 })} />
    <TransitionSeries.Sequence durationInFrames={240} name="Any agent"><AgentScene /></TransitionSeries.Sequence>
    <TransitionSeries.Transition presentation={fade()} timing={linearTiming({ durationInFrames: 20 })} />
    <TransitionSeries.Sequence durationInFrames={360} name="Governed context"><ContextScene /></TransitionSeries.Sequence>
    <TransitionSeries.Transition presentation={fade()} timing={linearTiming({ durationInFrames: 20 })} />
    <TransitionSeries.Sequence durationInFrames={260} name="Finale"><FinaleScene /></TransitionSeries.Sequence>
  </TransitionSeries>
);