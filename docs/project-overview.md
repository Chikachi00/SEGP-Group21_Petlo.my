# Project Overview

## Project Title

Robust Detection and Event Recognition for Fast Small-Object Sports Analytics: A Disc Dog Case Study

## Client

petlo.my

## Problem Statement

Reviewing disc dog training footage manually takes time and makes it difficult to compare activity across sessions. The footage is also technically challenging: the disc may be small, fast, blurred, partly hidden, or temporarily outside the frame. A future system should help review pre-recorded footage without treating a single detection or disappearance as proof of an event.

## Motivation

A consistent video analysis workflow could reduce repetitive review and provide useful session summaries. Before building the full application, the project must establish whether a general detection model can provide sufficient observations of dogs, people, and flying discs in representative footage.

## Proposed Solution

The proposed solution is a staged computer vision pipeline that reads a recorded video, detects relevant objects, tracks their motion, analyses trajectories, recognises events, and produces session statistics for review in a future web application.

The current version is limited to video inspection, frame extraction, and a pretrained object detection baseline. Tracking, trajectory analysis, and event recognition remain future work.

## Main Objectives

- Define an agreed and measurable project scope.
- Inspect the technical properties of representative videos.
- Establish an honest object detection baseline.
- Plan a labelled dataset without introducing frame-level data leakage.
- Separate object observations from throw, catch, and miss decisions.
- Provide a foundation for later application and evaluation work.

## System Input

The proposed input is a pre-recorded disc dog training video. Supported formats, maximum duration, recording setup, and retention rules remain open questions for the client and supervisor.

## Expected Output

The future system is expected to provide:

- throw count
- catch count
- miss count
- catch ratio
- event timestamps
- historical session data

These outputs are planned and are not produced by the current feasibility tools.

## Initial Scope

The current scope covers:

- project definition and provisional requirements
- current and future architecture descriptions
- local video metadata inspection
- local frame extraction
- pretrained dog, disc, and person detection as a feasibility baseline
- dataset collection, annotation, splitting, and evaluation planning

## Current Out-of-Scope Items

- object tracking and trajectory analysis
- throw, catch, and miss recognition
- model fine-tuning
- video upload and account management
- frontend, backend, and database implementation
- historical dashboards
- deployment and real-time processing

## Assumptions, Proposed Requirements, and Open Questions

- **Assumption:** The first technical evaluation will use pre-recorded rather than live video.
- **Assumption:** The team will use only videos it is authorised to process.
- **Proposed requirement:** Detection, tracking, and event recognition results should remain distinguishable in code and reports.
- **Open question:** What definitions should be used for a throw, successful catch, miss, and uncertain event?
- **Open question:** What video formats and recording conditions are typical?
- **Open question:** Should uploaded videos be retained or removed after analysis?

These points require confirmation and are not presented as agreed client requirements.

## Main Technical Risks

- small flying disc detection
- high-speed motion and motion blur
- temporary disappearance and occlusion
- distinguishing a catch from temporary occlusion
- different recording environments and camera distances
- limited labelled data
- biased evaluation if neighbouring frames are divided across dataset splits

Third-party library and model licences should be reviewed before any future commercial deployment.

