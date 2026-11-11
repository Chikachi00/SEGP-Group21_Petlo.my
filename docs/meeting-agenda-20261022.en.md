# Supervisor Meeting Agenda

**Date:** 22 October 2026  
**Status:** Questions and proposed requirements for discussion; not yet agreed.

## 1. Definition of a Successful Catch

- [ ] Does a successful airborne catch mean that the dog catches the disc with its mouth before the disc first touches the ground?
- [ ] If the dog catches the disc before it lands but immediately drops it, does this count as a successful catch?
- [ ] Should a ground pickup (the disc lands first, then the dog picks it up) be counted separately from an airborne catch?

## 2. Camera Views and Uncertain Outcomes

- [ ] Are both front and side views mandatory, or can the system also accept a single fixed view?
- [ ] May the system report `uncertain` when occlusion, an out-of-frame disc or insufficient evidence prevents a reliable decision, even with two views?
- [ ] Should uncertain events be excluded from the catch-rate denominator and reported separately?

## 3. Video Specifications

- [ ] Are the following initial recommendations acceptable?

| Item | Proposed specification |
| --- | --- |
| File size | No more than 500 MB per file |
| Resolution | Prefer 1080p |
| Frame rate | Prefer 60 fps |
| Container / codec | Prefer MP4 / H.264 |
| Clip duration | Initially 30–60 seconds per continuous clip for validation |

- [ ] Must the system also support 30 fps, 4K and HEVC videos?
- [ ] If a recording exceeds the size limit, may it be split into consecutive clips while preserving the complete throw and outcome within each clip?

## 4. Recording Requirements

- [ ] Can the current scope require a fixed tripod camera and exclude handheld recording or camera-following shots?
- [ ] Can recordings be expected to cover the throw, disc flight, dog–disc contact and the immediate aftermath as completely as possible?
- [ ] For two-view recordings, can both cameras record the same session simultaneously and include a synchronization reference?

## 5. Interface and Delivery Scope

- [ ] Are the current statistics, event playback and `uncertain` indications sufficient? What changes are required?
- [ ] Is manual confirmation or correction of machine results required?
- [ ] What is the expected deliverable by the end of this semester: a refined local version with improved algorithms, event classification and reporting for demonstration and validation, or an online version that allows the client to upload videos and test the system through the website without installing software?
- [ ] If an online version is required this semester, can the company or university provide deployment resources and help confirm permission to upload videos for cloud processing?

## 6. Video Use, Cloud Processing and Privacy Permissions

- [ ] Does the restriction mean that videos must not be published publicly on GitHub, or that they must not be uploaded to any third-party platform at all?
- [ ] May videos be uploaded to a private cloud service for temporary analysis and deleted afterwards?
- [ ] May reports, thumbnails, screenshots or compressed previews be retained? Should access be restricted to authorized users, or is public demonstration permitted?
- [ ] How long may each type of data be retained, who may access it, and who is responsible for deletion?

**Clarification:** Cloud video analysis normally still requires transferring video or frames, even if they are not permanently stored. Thumbnails and previews can still reveal people or the scene; their use needs separate confirmation. If video must remain on the local machine, video analysis should also run locally, and only explicitly permitted report data should be sent to the cloud.

Confirm these permissions with the supervisor and video provider, and record the agreed scope. Keep GitHub limited to code and documentation approved for public release.

## Meeting Notes

- Confirmed decisions:
- Open questions:
- Follow-up actions:
