# System Architecture

## Architecture Principles

Detection, tracking, trajectory evidence, event candidates, and statistics are separate stages. A detection or a temporary disappearance alone does not establish a catch or miss. Each stage produces inspectable outputs and keeps uncertain events explicit.

## Current Local Prototype

The current command-line workflow has two paths: a source-reading/review path and a sample event-analysis path. The event path is tested on the fixed front and side sample videos only.

```mermaid
flowchart LR
    V[Local video] --> DET[Disc and dog detections]
    DET --> TR[Disc and dog tracks]
    TR --> JO[Joint disc/dog evidence]
    JO --> EV[Throw-event candidates]
    EV --> FU[Front/side sample fusion]
    FU --> ST[Candidate session statistics]
    PK[FFmpeg source packet] --> RV[Frame and crop review]
    TR --> RV
    EV --> RV
```

The FFmpeg packet stores real frame timestamps and supports browsing, crops, and result review. Algorithms still process continuous source frames. The event prototype analyzes the front and side tripod samples, pairs their four attempts by event order, and leaves the views' timestamps independent. The statistics report distinguishes in-air catch candidates, ground-pickup candidates, miss candidates, and uncertain outcomes. Human labels are used only for sample comparison, not to calculate candidate statistics.

## Component Status

| Component | Current status |
|---|---|
| Video reader and source packet | Implemented; four local samples completely decoded and indexed |
| Dog detector and tracker | Prototype implemented; provisional single-dog IDs and pixel trajectories |
| Disc detector and tracker | Small-disc detection and tracking prototypes; sample review tools available |
| Joint dog/disc evidence | Prototype implemented with source-time and observation provenance |
| Throw-event recognition | Sample-bound candidate rules; no mouth localization or general accuracy claim |
| Two-angle fusion | Implemented for the matching, ordered front/side sample recordings only |
| Session statistics | Candidate counts, in-air catch candidate rate, retrieval candidate rate, and uncertainty coverage |
| Accuracy evaluation | Four user-reviewed side labels provide a sample diagnostic, not independent evaluation |
| REST API, frontend, database, deployment | Not implemented |
| Physical distance and speed | Not implemented; camera calibration is required |

Candidate statistics currently use classified candidate events as their denominator; uncertain events are reported separately and excluded. Ground pickups count as non-air catches for the in-air catch candidate rate and as retrieved for the retrieval candidate rate. These rates describe model candidates, not verified outcomes.

## Future Application Architecture

```mermaid
flowchart TB
    UI[Frontend<br/>React and TypeScript] --> API[REST API]
    API --> BE[Backend<br/>FastAPI]
    BE --> VR[Video Reader]
    VR --> OD[Object Detector]
    OD --> OT[Object Tracker]
    OT --> TA[Trajectory Analysis]
    TA --> ER[Event Recognition]
    ER --> ST[Statistics]
    BE <--> DB[(PostgreSQL<br/>Sessions, Events, Statistics)]
    BE <--> VS[(Video Storage)]
```

This is a proposed system direction. The web interface, REST API, database, and deployment are not part of the current prototype. Multi-camera synchronization and reliable matching outside the supplied sample also remain future work.