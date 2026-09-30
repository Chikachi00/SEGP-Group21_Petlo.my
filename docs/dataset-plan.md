# Dataset Strategy

## Purpose

The dataset should support honest evaluation of object detection and, later, event recognition. Collection and annotation should begin only after permissions, event definitions, and the intended evaluation procedure are agreed.

## Initial Classes

The initial object classes are:

- `dog`
- `disc`
- `person` / `handler`

General COCO detection models commonly use the class name `frisbee`. Project-facing documentation and displays use `disc` because it better matches the project's domain language. The mapping must remain explicit in code and evaluation records.

## Data Collection

Preferred sources are:

- client-authorised project videos
- team-recorded videos with suitable permission
- legally usable sources with recorded terms of use

Large source videos should not be committed to GitHub. Private or client-provided videos should not be committed to the public repository. The team should record the source, permission status, recording conditions, and any usage restrictions for each video without exposing private material.

## Annotation

CVAT, Label Studio, and Roboflow are possible annotation tools. No tool has been selected as mandatory.

The team should define a versioned class list and annotation guide before dividing work. A small shared calibration set should be annotated and reviewed first so that disagreements can be resolved before larger-scale labelling.

## Annotation Guidelines

Draw bounding boxes for:

- dogs
- discs
- handlers when the handler class is included in the agreed experiment

The guide should address:

- partially visible discs
- blurred discs
- discs overlapping with dogs
- temporary occlusion
- objects cut by the frame boundary
- ambiguous frames

Boxes should cover the visible object consistently according to the chosen tool's convention. If an object is too blurred or ambiguous to identify reliably, annotators should not guess a label. Such frames should be flagged for review or excluded under a documented rule.

## Dataset Split

An initial split could be approximately:

- 70% training
- 15% validation
- 15% test

The final proportions should reflect the number and diversity of available videos. The split must be performed at **video level**, not by randomly dividing frames.

Frames from the same recording are strongly correlated. For example, Video A Frame 100 and Video A Frame 101 must not be placed in training and test sets respectively. That arrangement would introduce data leakage and make the evaluation result untrustworthy. Clips from the same original recording should remain in the same split unless a documented study design justifies otherwise.

The test split should remain unchanged during model development. Where possible, recording locations, sessions, and subjects should also be considered so that near-duplicate conditions do not cross splits.

## Dataset Diversity

Future collection should aim to cover:

- different disc colours
- different dog breeds and sizes
- different backgrounds, including grass fields
- different lighting conditions
- different camera distances
- high-speed motion and motion blur
- partial occlusion
- camera movement
- different video resolutions
- different recording angles

Coverage should be measured and reported rather than assumed.

## Future Evaluation

### Object Detection Metrics

- Precision
- Recall
- mAP@50
- mAP@50:95

### Event Recognition Metrics

- Event Precision
- Event Recall
- Event F1 Score

### Product-Oriented Metrics

- Mean Absolute Throw Count Error
- Mean Absolute Catch Count Error

No metric results are available yet. Event-level evaluation will also require a documented timestamp tolerance and rules for uncertain or disputed events.

## Data Governance Decisions Still Needed

- who may access client-provided footage
- where raw and labelled data will be stored
- how long uploaded or source videos will be retained
- whether faces or other identifying details require additional handling
- which artefacts may be shared with assessors or placed in a public repository
- how dataset versions and annotation changes will be recorded

