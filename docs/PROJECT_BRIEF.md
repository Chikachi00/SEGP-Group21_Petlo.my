# Project Brief

## Module Context

**Module:** COMP2019 Software Engineering Group Project

**Group:** Group 21

**Client/project theme:** petlo.my disc dog video analytics

**Topic:** Robust detection and event recognition for fast small-object sports analytics using disc dog videos.

## Problem Summary

Disc dog training videos can contain fast motion, a small flying disc, occlusion, camera movement, and ambiguous moments around throws and catches. The intended final prototype should help users analyse uploaded footage by estimating how many throws occurred, how many were successfully caught, and the resulting catch ratio.

The project should use existing computer vision components where appropriate, but the team must first inspect representative videos and establish measurable baselines. Detection, tracking, and event recognition are related but distinct tasks.

## Expected Final Prototype

The intended final system may include:

- video upload and management
- footage review with generated results
- automated throw, catch, and miss recognition
- catch ratio calculation
- event timestamps
- saved session records
- a history view or simple trend summary
- technical documentation, testing evidence, and deployment notes

These are planned capabilities. They should be implemented and evaluated gradually in later milestones.

## Current Foundation and Feasibility Scope

The current repository contains:

- project definition and provisional requirements
- current and proposed future architecture
- a local video metadata inspection tool
- a selected-frame extraction tool
- a pretrained object detection baseline for dog, frisbee, and person observations
- a dataset preparation strategy
- an empty findings template for representative-video experiments

The baseline has not yet been evaluated on representative project videos. It does not implement tracking, trajectory analysis, throw recognition, catch recognition, miss recognition, a frontend, a backend, or a database.

## Open Decisions

The group should confirm:

- definitions of throw, catch, miss, and uncertain event
- source, permission, and storage rules for videos
- whether labelled data is available or must be created
- baseline evaluation method and acceptable error measures
- team responsibilities for computer vision, interface, application services, storage, testing, and documentation
- whether uploaded videos should be stored, deleted after processing, or retained for review

## Data and Repository Rules

Keep large or sensitive artefacts out of Git, including raw videos, generated outputs, model weights, local environment files, and private configuration. Record decisions and small documentation files in the repository so the development history remains reviewable.
