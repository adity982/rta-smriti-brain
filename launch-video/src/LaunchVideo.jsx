import { TransitionSeries, linearTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { ProblemScene } from "./scenes/ProblemScene";
import { BrainScene } from "./scenes/BrainScene";
import { EvidenceScene } from "./scenes/EvidenceScene";
import { AgentScene } from "./scenes/AgentScene";
import { ContextScene } from "./scenes/ContextScene";
import { FinaleScene } from "./scenes/FinaleScene";

export const LaunchVideo = () => (
  <TransitionSeries>
    <TransitionSeries.Sequence durationInFrames={270} name="The context problem"><ProblemScene /></TransitionSeries.Sequence>
    <TransitionSeries.Transition presentation={fade()} timing={linearTiming({ durationInFrames: 20 })} />
    <TransitionSeries.Sequence durationInFrames={360} name="The local project brain"><BrainScene /></TransitionSeries.Sequence>
    <TransitionSeries.Transition presentation={fade()} timing={linearTiming({ durationInFrames: 20 })} />
    <TransitionSeries.Sequence durationInFrames={300} name="Evidence-aware memory"><EvidenceScene /></TransitionSeries.Sequence>
    <TransitionSeries.Transition presentation={fade()} timing={linearTiming({ durationInFrames: 20 })} />
    <TransitionSeries.Sequence durationInFrames={300} name="Any agent"><AgentScene /></TransitionSeries.Sequence>
    <TransitionSeries.Transition presentation={fade()} timing={linearTiming({ durationInFrames: 20 })} />
    <TransitionSeries.Sequence durationInFrames={370} name="Focused context pack"><ContextScene /></TransitionSeries.Sequence>
    <TransitionSeries.Transition presentation={fade()} timing={linearTiming({ durationInFrames: 20 })} />
    <TransitionSeries.Sequence durationInFrames={300} name="Finale"><FinaleScene /></TransitionSeries.Sequence>
  </TransitionSeries>
);
