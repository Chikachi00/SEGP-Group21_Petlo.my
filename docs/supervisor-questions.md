# Supervisor and Client Questions

This document is a working checklist for discussions with the supervisor and client. It is intended to clarify project requirements, data access, event definitions, technical constraints, and evaluation expectations.

Answers should be recorded after meetings and used to update the project requirements and architecture where necessary.

**Status:** Open

**Last reviewed:** Not yet reviewed with supervisor/client

## 1. Project Scope and Success Criteria

- [ ] What is the minimum expected functionality for the final prototype?
- [ ] Which features are considered essential for project success?
- [ ] Which features are optional or stretch goals?
- [ ] Is the main project focus expected to be computer vision performance, software integration, or a balance of both?
- [ ] What level of automation is expected in the final prototype?
- [ ] Is manual correction of detected events expected or optional?
- [ ] What would the supervisor/client consider a successful final demonstration?

## 2. Video Data Availability

- [ ] Does petlo.my or the supervisor have representative disc dog videos available for the project?
- [ ] Approximately how many videos may be available?
- [ ] Are these training videos, competition videos, or both?
- [ ] What is the typical video duration?
- [ ] What is the typical video resolution?
- [ ] What is the typical frame rate?
- [ ] Are videos usually recorded using a fixed camera or a moving camera?
- [ ] Are videos usually recorded from similar camera positions?
- [ ] Is the dog usually fully visible?
- [ ] Is the handler usually visible?
- [ ] Is there normally one dog in each video?
- [ ] Is there normally one disc in each video?
- [ ] Are multiple people or dogs ever visible in the same scene?
- [ ] Are disc colours usually predictable?
- [ ] Are there common environmental conditions such as grass fields, indoor venues, or specific lighting conditions?

## 3. Data Permission and Privacy

- [ ] Are the provided videos permitted for use in this university project?
- [ ] May the project team download and store the videos locally?
- [ ] May all group members access the provided videos?
- [ ] May frames be extracted from the videos for development and evaluation?
- [ ] May the extracted frames be manually annotated?
- [ ] May derived annotations be shared within the project team?
- [ ] May anonymised screenshots be included in the final report or presentation?
- [ ] May example screenshots be included in the GitHub repository?
- [ ] Are the original videos strictly prohibited from being uploaded to the public repository?
- [ ] Are there any retention requirements for local copies of the videos?
- [ ] Should local copies be deleted after the project ends?
- [ ] Are there any faces, personal information, or sensitive material that must be anonymised?
- [ ] Is there a preferred storage location or access method for client-provided files?

> **Note:** Until permission is explicitly confirmed, client-provided videos should be treated as private project material and should not be uploaded to the public repository.

## 4. Event Definitions

- [ ] What exactly constitutes a throw?
- [ ] When should a throw event begin?
- [ ] What exactly constitutes a successful catch?
- [ ] If the dog catches the disc and immediately drops it, does this count as a catch?
- [ ] If the dog touches the disc but does not control it, does this count as a miss?
- [ ] What exactly constitutes a miss?
- [ ] How should incomplete or ambiguous events be treated?
- [ ] What should happen if the disc leaves the camera view?
- [ ] What should happen if the catch occurs outside the camera view?
- [ ] Can multiple throws occur in a single continuous clip?
- [ ] Should interrupted or aborted throws be counted?
- [ ] Should uncertain events be represented as a separate category?

## 5. Detection Targets

- [ ] Is dog detection mandatory?
- [ ] Is disc detection mandatory?
- [ ] Is handler/person detection required for the final system?
- [ ] Are there other objects that should be detected?
- [ ] Is detecting the dog's body sufficient, or is a more specific region such as the head or mouth eventually required?
- [ ] Is identifying individual dogs required?
- [ ] Is identifying the handler required?
- [ ] Does the client expect the system to support more than one dog in a video?
- [ ] Does the client expect the system to support more than one disc?

## 6. Output and User Experience

- [ ] Which statistics should be shown to the user?
- [ ] Is throw count required?
- [ ] Is catch count required?
- [ ] Is miss count required?
- [ ] Is catch ratio required?
- [ ] Should each detected event include a timestamp?
- [ ] Should users be able to click an event and jump to the corresponding video moment?
- [ ] Should the system display annotated video with bounding boxes?
- [ ] Should users be able to correct incorrect event detections?
- [ ] Should corrected results replace the automatically generated results?
- [ ] Should users be able to add missing events manually?
- [ ] Is a historical performance view required?
- [ ] Which historical metrics are most useful?
- [ ] Is a chart required, or is a table sufficient?
- [ ] Does the final prototype require user accounts?
- [ ] Does the final prototype require multiple dog profiles?

## 7. Processing and Technical Expectations

- [ ] Is real-time processing required?
- [ ] Is offline processing of uploaded videos sufficient?
- [ ] Is there an acceptable processing time for a typical video?
- [ ] Does the system need to run on standard laptops?
- [ ] Will dedicated graphics hardware be available during development or demonstration?
- [ ] Does the final prototype need to be deployed online?
- [ ] Is local deployment acceptable for the final demonstration?
- [ ] Are there any restrictions on third-party libraries or pretrained models?
- [ ] Are there any licensing requirements that the team should consider?
- [ ] Is there a preferred programming language, framework, or deployment environment?

## 8. Evaluation Expectations

- [ ] How should detection quality be evaluated?
- [ ] Which metrics does the supervisor/client consider most meaningful?
- [ ] Is object detection evaluation using Precision, Recall, and mAP expected?
- [ ] Is event-level Precision, Recall, and F1 score expected?
- [ ] Should the project report count errors such as throw-count error and catch-count error?
- [ ] Is qualitative evaluation acceptable during early feasibility work?
- [ ] How many representative videos would be sufficient for initial feasibility evaluation?
- [ ] Is a separately labelled test set expected?
- [ ] Should evaluation be performed on unseen videos?
- [ ] Should processing time also be measured?
- [ ] Is user evaluation or usability testing expected for the final web prototype?

## 9. Dataset and Annotation

- [ ] Will labelled data be provided?
- [ ] If not, is the team expected to create its own labelled dataset?
- [ ] Is there any existing annotation for throws or catches?
- [ ] Is there any existing bounding-box annotation for dogs or discs?
- [ ] Approximately how much annotation effort is considered reasonable?
- [ ] Which classes should be included in the initial dataset?
- [ ] Should annotation include dog, disc, and handler?
- [ ] Should difficult or ambiguous frames be excluded or marked separately?
- [ ] Is frame-level annotation sufficient for the detection stage?
- [ ] Is event-level annotation required for throw and catch evaluation?
- [ ] Are there recommended annotation tools or formats?

## 10. Repository and Deliverables

- [ ] What materials are expected to be included in the GitHub repository?
- [ ] Should documentation and meeting decisions be version controlled?
- [ ] Should datasets remain outside the repository?
- [ ] Should model weights remain outside the repository?
- [ ] Is source code history considered part of the assessment?
- [ ] Are regular commits expected from all team members?
- [ ] Are branches and pull requests expected as part of the software engineering process?
- [ ] What technical documentation is expected for the final submission?
- [ ] Is a deployment guide required?
- [ ] Is an API specification expected?
- [ ] Is a user guide required?

## 11. Roles and Communication

- [ ] Who should be the main contact for technical questions?
- [ ] Who should be the main contact for client requirements?
- [ ] How frequently should the team provide progress updates?
- [ ] Is there a preferred communication channel?
- [ ] Should major requirement changes be confirmed in writing?
- [ ] Should the team provide experiment results before implementing later stages?
- [ ] When should the next project review take place?

## Meeting Notes Template

### Meeting Information

| Field | Details |
|---|---|
| Date | |
| Meeting type | Supervisor / Client / Internal |
| Attendees | |
| Main topics | |

### Confirmed Decisions

| ID | Decision | Confirmed by | Date |
|---|---|---|---|

### Updated Requirements

| Requirement | Change | Reason |
|---|---|---|

### Data Permissions

| Item | Permission / Restriction |
|---|---|
| Local video storage | |
| Group sharing | |
| Frame extraction | |
| Annotation | |
| Report screenshots | |
| Public repository use | |

### Action Items

| Action | Owner | Due date | Status |
|---|---|---|---|

### Open Questions After Meeting

- [ ]

## Decision Log

| ID | Date | Decision | Reason | Source |
|---|---|---|---|---|
