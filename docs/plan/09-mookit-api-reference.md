# 09 — mooKIT API Reference (extracted from the live OpenAPI spec)

Source: `https://test.mookit.in/docs/openapi.json` — **mooKIT Instructor Express API v0.1.0, OpenAPI 3.1**,
55 endpoints. This is the contract Dev A's `MooKitClient` is built against. **Confirm with the mooKIT team
that this live spec is the source of truth** (the written spec §13 lists endpoints as "TBD", but the live
swagger is already populated).

> Dev note: a few request-body field details below were inferred by resolving `$ref`s in the spec; verify
> exact payloads against the live test instance during P0/P3 before relying on them for writes.

## Global conventions

### Required headers (every request)
| Header | Type | Required | Notes |
|---|---|---|---|
| `course` | string | yes | course short-name → selects course-scoped DB (alias `x-course`) |
| `token` | string (JWT) | yes | auth token |
| `uid` | integer | yes | authenticated user id (alias `x-user-id`) |

For dev, `details.md` provides static values: `course=coursetest`, `token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...`, `uid=1`.

There are **no OpenAPI `securitySchemes`** — auth is purely these header parameters (consistent with the
**pass-through auth** decision: the frontend forwards them; our service relays them).

### Response envelope
```jsonc
// success
{ "success": true, "code": 200, "message": "Success", "data": <object|array|null> }
// list payloads
{ "data": { "items": [...], "meta": { "pagination": {page,limit,totalRecords,totalPages,hasNextPage,hasPrevPage},
                                      "sort": {column, order}, "filters": {}, "respectOrder": bool } } }
// error
{ "success": false, "error": { "code": <int>, "message": <str>, "details": <null|object> } }
```
`MooKitClient.call()` unwraps `data` on success and raises a typed error on `success:false`.

---

## Assessments (Quiz/Exam/Assignment generation)
`{type}` ∈ **`quizzes` | `exams` | `assignments`**.

| Method | Path | Purpose |
|---|---|---|
| POST | `/assessments/{type}` | Create assessment |
| GET | `/assessments/{type}/{id}` | Get one |
| PUT | `/assessments/{type}/{id}` | Update (partial) — **publish via this (set `published.status=1`)** |
| DELETE | `/assessments/{type}/{id}` | Delete |
| GET | `/assessments/{type}` | List |
| POST/GET/PUT/DELETE | `/assessments/{type}/{assessmentId}/sections[/{id}]` | Sections (optional grouping) |
| POST/GET/PUT/DELETE | `/assessments/{type}/{assessmentId}/sections/{sectionId}/questions[/{id}]` | Questions |
| GET | `/assessments/{type}/{assessmentId}/questions` | List all questions (optionally `?sectionId=`) |

**Create assessment — key body fields**
- Required: `title`; date fields `startDate`, `endDate`, `endDapDate`, `resultsDate` (Unix seconds, cascade-validated);
  `published.{status (0/1), releaseOn}`; flags `timed`, `retakeAllowed`, `showCorrectAnswers`,
  `misconductDetection`, `secureExamBrowser`, `calculatorEnabled`, `restrictSingleIp` (0/1).
- Conditional: `duration`/`durationDap` if `timed=1`; `retakeLimit` if `retakeAllowed=1`; `misconductMaxAttempts` if `misconductDetection=1`.
- Optional: `instructions`, `totalScore`, `tutorialSectionIds`, `solFileIds`, `minimumOofTimeMs` (default 5000).

**Question types & payloads** (map directly to the requirement's 5 types)
| `questionType` | Key payload |
|---|---|
| `mcq_single` | `options:[{optionText,isCorrect}]` — **exactly one** `isCorrect=1` |
| `mcq_multi` | `options:[{optionText,isCorrect}]` — **≥1** correct; `allowPartialMarks` permitted |
| `true_false` | `trueFalseAnswer: 0|1` |
| `fib` | discrete: `blanks:[{blankIndex,placeholderLabel,answers:[{answerText,caseSensitive}]}]` **or** numeric: `fibUseRange:1,fibRangeLower,fibRangeUpper` |
| `descriptive` | no structured answer (free-form; we auto-attach a rubric) |

Common question fields: `questionType`, `questionText`, `score`, `negativeScore`, `allowPartialMarks`
(not for `true_false`/`mcq_single`), `published.status`, optional `fileIds`.

**Publish/draft:** `published.{status: 0=draft|1=published, releaseOn: unix|null}`.
**Sections are optional** — questions can be created directly under a section; section creation is not a prerequisite for assessment creation.

**Create flow:** `POST /assessments/{type}` (status=0) → [optional `POST .../sections`] → loop
`POST .../sections/{sectionId}/questions` → publish via `PUT /assessments/{type}/{id}` (status=1).

---

## Announcements
| Method | Path |
|---|---|
| POST | `/announcements/add` |
| PUT | `/announcements/edit/{id}` |
| DELETE | `/announcements/delete/{id}` |
| GET | `/announcements/{id}` |
| GET | `/announcements/type/{type}` (`type` ∈ all/normal/urgent; paginated) |

**Create body:** `title` (required), `description`, `type` (`normal`|`urgent`, required), `notifyMail`
(0/1 — **email channel** vs LMS-only, required), `sectionIds` (audience; **empty = all students**),
`fileIds`, `published.{status (0=draft|1=published), releaseOn}` (required). `title`=subject, `description`=body.

---

## Files
| Method | Path | Notes |
|---|---|---|
| POST | `/files/add` | `multipart/form-data`, field `files` (array). Query `entityType`, `entityId` (default 0). Returns `ManagedFile[]` with `id`, `fileUrl`, `filemime`, `filesize`, ... |
| GET | `/files/allowed_extensions` | `{entityTypesAndFileFormat:{...}, fileMimeTypes:{...}}` |
| DELETE | `/files/delete/{id}` | |

---

## Lectures + Resources
| Method | Path | Notes |
|---|---|---|
| POST | `/lectures` | Create lecture |
| GET | `/lectures` | List (filters: `week_id`, `topic_id`, `published`, `mode_of_teaching`, paginated) |
| GET/PUT/DELETE | `/lectures/{id}` | |
| GET | `/lectures/vimeo/{videoid}` | Vimeo metadata |
| POST/GET | `/{entityType}/{entityId}/course-resources` | Attach/list resources for an entity (e.g. `entityType=lectures`) |
| GET/PATCH/DELETE | `/course-resources/{resourceId}` | One resource |
| GET/POST/.../ | `/resources[/{id}]` | Reusable resource containers (distinct from weeks/topics) |
| PUT | `/order/update` | Reorder (`{entity, listOrder:[{entityId,listOrder}]}`) |

**Lecture create body:** `title` (req), `weekId` (req), `topicId` (req), `published` (req, 0/1),
optional `modeOfTeaching` (`oldRecording`|`newRecording`|`liveSession`|null), `releaseOn` (unix — **schedule**), `taughtBy`.

> **Weeks/Modules/Topics are taxonomy term IDs, not resource containers.** Resolve "Week 4" via
> `GET /taxonomies/{type}` → use the term `id` as `weekId`/`topicId`.

**Video attach flow:** `POST /files/add` → get `fileId` → `POST /lectures` → `POST /lectures/{id}/course-resources`
with `{resourceType:"video", resourceFileId:fileId, isPrimary:true}` → schedule via `releaseOn`/`published`.
(`resourceType` ∈ file|audio|video; only one `isPrimary` per entity; primary resources can't be deleted.)
**Confirm with mooKIT team** whether the intended video path is uploaded file vs Vimeo id vs external URL.

---

## Users / Permissions / Taxonomy
| Method | Path | Notes |
|---|---|---|
| GET | `/users/me` | Current user (from `uid` header) |
| GET | `/users`, `/users/{id}`, `/users/stats/{id}` | List/get/stats |
| POST/PUT/DELETE | `/users/add`, `/users/edit/{id}`, `/users/delete/{id}` | |
| GET | `/user_permissions/allowed` | **Permission matrix for current user** — used to authorize actions |
| GET/PUT | `/user_permissions/{role}`, `/user_permissions/edit/{role}` | Role matrices |
| GET/POST/PUT/DELETE | `/taxonomies/{type}[/add|/edit/{id}|/delete/{id}]` | Terms (e.g. `week`, `module`, `topic`, `section`) |

**Permission matrix shape:** `{ resourceName: [actions...] }`, e.g. `{"lectures":["list","create","update","delete"], "files":["upload","delete"]}`.
Authorize every mutating tool against `GET /user_permissions/allowed` (cached per session) **in code**, in addition to mooKIT's own enforcement.

## Zoom (secondary, not Phase-1 core)
`POST /zoom/import`, `GET /zoom_meetings`, `POST /zoom/webhooks` (app-only).
