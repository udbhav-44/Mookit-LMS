from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Pagination(BaseModel):
    page: int
    limit: int
    totalRecords: int
    totalPages: int
    hasNextPage: bool
    hasPrevPage: bool


class ListMeta(BaseModel):
    pagination: Pagination
    sort: dict | None = None
    filters: dict | None = None
    respectOrder: bool = False


class ResponseEnvelope(BaseModel):
    success: bool
    code: int
    message: str
    data: Any = None


class ErrorDetail(BaseModel):
    code: int
    message: str
    details: dict | None = None


class ErrorEnvelope(BaseModel):
    success: Literal[False]
    error: ErrorDetail


class UserMe(BaseModel):
    """Matches the mooKIT GET /users/me → data (User schema)."""
    model_config = ConfigDict(extra="ignore")

    id: int
    name: str
    fullname: str | None = None
    email: str | None = None
    rolename: str | None = None   # student|instructor|tutor|teaching_assistant


class TaxonomyTerm(BaseModel):
    id: int
    name: str
    type: str  # e.g. "week", "module", "topic"


class ManagedFile(BaseModel):
    id: int
    fileUrl: str
    filemime: str
    filesize: int
    filename: str


class McqOptionInput(BaseModel):
    """One MCQ option — used in QuestionCreate.options."""
    optionText: str
    isCorrect: int = 0   # 0|1


class FibBlankInput(BaseModel):
    """One fill-in-the-blank answer set — used in QuestionCreate.blanks."""
    blankIndex: int
    placeholderLabel: str | None = None
    answers: list[str] = Field(default_factory=list)


class AssessmentCreate(BaseModel):
    title: str
    startDate: int
    endDate: int
    endDapDate: int
    resultsDate: int
    published: dict            # {status: 0|1, releaseOn: unix|null}
    timed: int = 0
    duration: int | None = None
    durationDap: int | None = None
    retakeAllowed: int = 0
    retakeLimit: int | None = None
    instructions: str | None = None
    totalScore: float | None = None
    showCorrectAnswers: int = 0
    misconductDetection: int = 0
    misconductMaxAttempts: int | None = None
    minimumOofTimeMs: int = 5000
    secureExamBrowser: int = 0
    calculatorEnabled: int = 0
    restrictSingleIp: int = 0
    tutorialSectionIds: list[int] | None = None
    solFileIds: list[int] | None = None


class SectionCreate(BaseModel):
    """POST /assessments/{type}/{id}/sections body."""
    title: str
    description: str | None = None
    showOneQuestion: int = 0
    allowNavigation: int = 0
    randomizeQuestions: int = 0
    randomizeOptions: int = 0
    # Required when randomizeQuestions=1; must be >= 1.
    randomQuestionCount: int | None = None


class QuestionCreate(BaseModel):
    """POST /assessments/{type}/{id}/sections/{sectionId}/questions body."""
    questionType: str   # mcq_single | mcq_multi | true_false | fib | descriptive
    questionText: str
    score: float
    negativeScore: float        # required — no default per spec
    published: dict             # {status: 0|1}
    allowPartialMarks: int = 0  # not allowed for true_false or mcq_single
    options: list[McqOptionInput] | None = None
    trueFalseAnswer: int | None = None
    blanks: list[FibBlankInput] | None = None
    fibUseRange: int | None = None
    fibRangeLower: float | None = None
    fibRangeUpper: float | None = None
    fileIds: list[int] | None = None


class AnnouncementCreate(BaseModel):
    """POST /announcements/add body."""
    title: str
    description: str | None = None   # nullable in spec
    type: Literal["normal", "urgent"]
    notifyMail: int             # 0=LMS-only, 1=also email
    published: dict             # {status: 0|1, releaseOn: unix|null}
    sectionIds: list[int] | None = None
    fileIds: list[int] | None = None


class AnnouncementUpdate(BaseModel):
    """PUT /announcements/edit/{id} body — all fields optional."""
    title: str | None = None
    description: str | None = None
    type: Literal["normal", "urgent"] | None = None
    notifyMail: int | None = None
    published: dict | None = None
    sectionIds: list[int] | None = None
    fileIds: list[int] | None = None


class LectureCreate(BaseModel):
    """POST /lectures body."""
    title: str
    weekId: int
    topicId: int
    published: int              # 0=draft, 1=published
    modeOfTeaching: str | None = None  # oldRecording|newRecording|liveSession
    releaseOn: int | None = None
    taughtBy: int | None = None


class CourseResourceCreate(BaseModel):
    """One entry in POST /{entityType}/{entityId}/course-resources resources array."""
    resourceType: Literal["file", "audio", "video"]
    resourceFileId: int
    isPrimary: bool = False
