# Initial Requirements — Version 0.1

These requirements are provisional and should be validated with the supervisor and client.

## Requirement Status

The current feasibility requirements describe the local command-line tools in this repository. The future full-system requirements describe planned behaviour and are not claims about completed functionality.

## Current Feasibility Requirements

| ID | Requirement |
|---|---|
| FR01 | The system shall accept a pre-recorded video for analysis. |
| FR02 | The system shall process video frames automatically. |
| FR03 | The current feasibility prototype shall detect dogs using a general object detection model. |
| FR04 | The current feasibility prototype shall attempt to detect flying discs. |

The feasibility prototype also observes the general `person` class so the team can study whether handler observations may be useful. This does not establish a confirmed requirement to detect handlers in the final system.

## Future Full-System Requirements

| ID | Requirement |
|---|---|
| FR05 | The future system shall identify throw events. |
| FR06 | The future system shall identify catch events. |
| FR07 | The future system shall identify missed catches where technically feasible. |
| FR08 | The future system shall calculate the total number of throws. |
| FR09 | The future system shall calculate the total number of catches. |
| FR10 | The future system shall calculate a catch ratio. |
| FR11 | The future system shall associate detected events with video timestamps. |
| FR12 | The future web system shall allow users to review analysis results. |
| FR13 | The future system shall retain training session results. |
| FR14 | The future system shall display historical performance information. |

## Non-Functional Requirements

Quantitative targets have not yet been agreed. Suitable measures and thresholds should be defined only after representative videos, event definitions, and a labelled evaluation set are available.

| Area | Provisional requirement |
|---|---|
| Usability | Commands and future review screens should use clear labels, errors, and instructions. |
| Maintainability | Detection, tracking, trajectory analysis, and event recognition should remain modular and independently testable. |
| Reliability | Processing failures should be reported clearly and should not be presented as valid results. |
| Performance | Processing time and resource use should be measured on agreed hardware before targets are set. |
| Detection Quality | Detection quality should be evaluated against labelled, representative footage using agreed metrics. |
| Privacy | Client-private footage should remain outside the public repository and follow an agreed retention policy. |
| Compatibility | The feasibility tools should support the team's agreed Python environment and common pre-recorded video formats readable by OpenCV. |
| Testability | Pure utility logic should have lightweight automated tests; video and model evaluation should use recorded test procedures. |

## Open Questions for Client / Supervisor

- What exactly constitutes a throw?
- What exactly constitutes a successful catch?
- If a dog catches the disc and immediately drops it, should it count as a catch?
- What constitutes a miss?
- Are videos normally recorded with a fixed camera?
- What is the typical video resolution?
- What is the typical frame rate?
- What is the typical video duration?
- Is there normally one dog in each video?
- Is there normally one disc in each video?
- Is the human handler always visible?
- Does the handler need to be detected?
- Are disc colours predictable?
- Will petlo.my provide sample or training videos?
- Should users be able to manually correct automatically detected events?
- Should uploaded videos be permanently stored?
- Is real-time processing required in the future, or only uploaded-video processing?

