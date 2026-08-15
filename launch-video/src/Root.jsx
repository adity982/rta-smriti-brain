import { Composition, Folder } from "remotion";
import { LaunchVideo } from "./LaunchVideo";
import { ProblemScene } from "./scenes/ProblemScene";
import { BrainScene } from "./scenes/BrainScene";
import { EvidenceScene } from "./scenes/EvidenceScene";
import { AgentScene } from "./scenes/AgentScene";
import { ContextScene } from "./scenes/ContextScene";
import { FinaleScene } from "./scenes/FinaleScene";

const video = { fps: 30, width: 1920, height: 1080 };

export const VideoRoot = () => (
  <>
    <Folder name="Launch-scenes">
      <Composition id="ProblemScene" component={ProblemScene} durationInFrames={270} {...video} />
      <Composition id="BrainScene" component={BrainScene} durationInFrames={360} {...video} />
      <Composition id="EvidenceScene" component={EvidenceScene} durationInFrames={300} {...video} />
      <Composition id="AgentScene" component={AgentScene} durationInFrames={300} {...video} />
      <Composition id="ContextScene" component={ContextScene} durationInFrames={370} {...video} />
      <Composition id="FinaleScene" component={FinaleScene} durationInFrames={300} {...video} />
    </Folder>
    <Composition id="RtaSmritiLaunch" component={LaunchVideo} durationInFrames={1800} {...video} />
  </>
);
