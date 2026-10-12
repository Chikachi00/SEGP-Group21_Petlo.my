# Petlo.my Dog Movement Analysis System

## User Requirements Specification

| Document field | Value |
|---|---|
| Project | SEGP Group 21 — Petlo.my |
| Document version | 0.1 |
| Document status | Initial Draft |
| Author | SEGP Group 21 |
| Date | 2026-10-08 |

**Status terms:** **Confirmed** requirements are supported by the first client meeting; **Proposed** requirements require client approval; **TBD** marks an unresolved value or decision.

## 1. Introduction

This URS defines the initial user requirements for the Petlo.my dog movement analysis project. The intended final users are ordinary pet owners who record a dog performing an exercise or play activity and review the resulting movement analysis.

Version 0.1 covers an early prototype based on client-provided videos. The first priority is computer vision: accepting video, detecting the dog, and tracking its movement. Disc tracking, movement measurements, result presentation, and a pet-owner interface remain proposed until confirmed by the client.

The client will provide authorised videos; detailed recording and compatibility conditions remain TBD.

### 1.1 Prototype Scope

The initial prototype is limited to:

- accepting representative client-approved recorded videos;
- detecting a dog and tracking its movement over time; and
- producing results that the team and client can inspect.

Disc analysis, distance and height estimates, and a pet-owner interface are proposed extensions. Real-time camera input, multiple-dog support, and the final deployment platform have not been confirmed.

## 2. Functional Requirements

| ID | Requirement | Priority | Status | Acceptance criteria |
|---|---|---:|---|---|
| FR-01 | The system shall accept a client-approved recorded dog video for analysis. Supported formats, limits, resolutions, and frame rates are TBD. | High | Confirmed at high level | An approved sample video can be opened and processed in frame order; unsupported input produces a clear error. |
| FR-02 | The system shall detect the dog in relevant video frames. The initial case is expected to contain one dog. | High | Confirmed at high level | Dog detections can be inspected on an agreed test video; the quantitative accuracy target is TBD. |
| FR-03 | The system shall track the detected dog's movement over time. | High | Confirmed at high level | The prototype produces an inspectable, time-ordered dog trajectory for an agreed test video; error tolerance is TBD. |
| FR-04 | The prototype should detect and, if required, track one exercise object, initially proposed as a disc. | Medium | Proposed | After client approval, the disc is identified in agreed sample footage; whether detection or full tracking is required is confirmed. |
| FR-05 | The system should estimate the distance travelled by the dog during a defined running activity. | Medium | Proposed | The output has an agreed unit and is compared with a reference measurement; activity boundaries, calibration, and acceptable error are TBD. |
| FR-06 | The system should estimate the dog's jump height from suitable footage. | Medium | Proposed | The output has an agreed unit and is compared with a reference measurement; the measurement definition, calibration, and acceptable error are TBD. |
| FR-07 | The system should present available analysis results, such as tracked positions, annotated media, or approved measurements. | Medium | Proposed | Results are linked to the correct video, use clear labels and units, and distinguish unavailable results from zero values. |
| FR-08 | The final product should allow a pet owner to select a supported video and start analysis through a simple interface. | Medium | Proposed | A user can submit a video, view processing status, and understand input or processing errors. The platform is TBD. |
| FR-09 | The system should handle suitable front-view and side-view recordings. Whether paired views must be combined is TBD. | Medium | Proposed | The required view for each approved analysis is identified and tested using client-approved footage. |

Computer vision and dog tracking are the first prototype priorities. Proposed functions become acceptance requirements only after client approval.

## 3. Non-Functional Requirements

| ID | Category | Requirement | Priority | Status | Acceptance criteria |
|---|---|---|---:|---|---|
| NFR-01 | Privacy | Client videos and identifiable derived media shall not be uploaded to a publicly accessible location. Storage, access, retention, and deletion rules are TBD. | High | Confirmed | No client video or identifiable derived media is publicly accessible, and the client approves the final data-handling procedure. |
| NFR-02 | Performance | The system should process accepted videos within a practical period. | Medium | Proposed | Processing time is measured on agreed footage and hardware against a client-approved target, currently TBD. |
| NFR-03 | Usability | The final interaction should be understandable to ordinary pet owners without computer-vision knowledge. | Medium | Proposed | Representative users can complete agreed core tasks; the task set and success threshold are TBD. |
| NFR-04 | Reliability | Supported inputs should be handled consistently, and failures shall not be presented as valid measurements. | High | Proposed | Repeated reference tests remain within an agreed tolerance, and invalid input produces a controlled error; tolerance is TBD. |
| NFR-05 | Video compatibility | The system should support client-approved video characteristics. HD landscape footage at 30 FPS or 60 FPS is the current expectation. | High | Proposed; details TBD | Approved samples for every supported format, resolution, orientation, and frame rate are processed successfully. |

No numerical performance or accuracy targets are stated because none have yet been confirmed by the client.

## 4. Constraints and Open Questions

### 4.1 Constraints and Current Assumptions

- The prototype shall prioritise computer vision and dog tracking before detailed user-interface development.
- The client will provide authorised dog exercise videos for development and evaluation.
- Initial videos are expected to contain one dog and may provide separate front and side views.
- HD landscape video at 30 FPS or 60 FPS is expected, but exact formats and limits are unconfirmed.
- Pet owners are expected to arrange the camera themselves and may require recording guidance.
- Video quality, camera position, visibility, and scene calibration may limit possible measurements.
- Real-world distance or height measurements may require a known reference or camera calibration.
- The prototype may initially restrict object analysis to a disc.
- Client videos and identifiable derived media must not be made publicly accessible.
- The URS does not require a specific model, library, programming language, or architecture.

All assumptions require client review before they become acceptance conditions.




### 4.2 Open Questions for Client Confirmation

| ID | Topic | Question requiring confirmation |
|---|---|---|
| OQ-01 | Camera setup | Must the camera be fixed, may it move to follow the dog, or must both cases be supported? What position and recording guidance should users follow? The meeting record is contradictory about camera movement. |
| OQ-02 | Video compatibility | Which containers, codecs, resolutions, frame rates, durations, and file sizes must be supported? Must both 30 FPS and 60 FPS be supported? |
| OQ-03 | Distance and height | Are running distance and jump height required? How are they defined, calibrated, expressed, and validated, and which camera view is required? |
| OQ-04 | Disc tracking | Is a disc the correct first object, and is detection alone sufficient or is full tracking required? |
| OQ-05 | Accuracy and performance | What detection, tracking, and measurement accuracy is acceptable? What processing-time target and reference hardware should be used? |
| OQ-06 | Privacy and data use | Where may videos and results be processed or stored, who may access them, how long may they be retained, and may they be used for training, testing, or demonstrations? |
| OQ-07 | Open-source licensing | May the team use Ultralytics or other open-source libraries, and what licensing, attribution, distribution, or commercial-use restrictions apply? |
| OQ-08 | Views, output, and interface | Must front and side videos be paired or synchronised? Which results must pet owners see, and on which interface or platform? |


## 5. Revision History

| Version | Date | Status | Author | Summary |
|---|---|---|---|---|
| 0.1 | 2026-10-08 | Initial Draft | SEGP Group 21 | Concise initial URS based on the first client meeting. |
