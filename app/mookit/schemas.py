from pydantic import BaseModel, ConfigDict, Field
from typing import Any, List, Literal, Optional


class Pagination(BaseModel):
    page: int
    limit: int
    totalRecords: int
    totalPages: int
    hasNextPage: bool
    hasPrevPage: bool


class ListMeta(BaseModel):
    pagination: Pagination
    sort: Optional[dict] = None
    filters: Optional[dict] = None
    respectOrder: bool = False


class ResponseEnvelope(BaseModel):
    success: bool
    code: int
    message: str
    data: Any = None


class ErrorDetail(BaseModel):
    code: int
    message: str
    details: Optional[dict] = None


class ErrorEnvelope(BaseModel):
    success: Literal[False]
    error: ErrorDetail


class UserMe(BaseModel):
    """Matches the mooKIT GET /users/me → data (User schema)."""
    model_config = ConfigDict(extra="ignore")

    id: int
    name: str
    fullname: Optional[str] = None
    email: Optional[str] = None
    rolename: Optional[str] = None   # student|instructor|tutor|teaching_assistant


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
    placeholderLabel: Optional[str] = None
    answers: List[str] = Field(default_factory=list)


class AssessmentCreate(BaseModel):
    title: str
    startDate: int
    endDate: int
    endDapDate: int
    resultsDate: int
    published: dict            # {status: 0|1, releaseOn: unix|null}
    timed: int = 0
    duration: Optional[int] = None
    durationDap: Optional[int] = None
    retakeAllowed: int = 0
    retakeLimit: Optional[int] = None
    instructions: Optional[str] = None
    totalScore: Optional[float] = None
    showCorrectAnswers: int = 0
    misconductDetection: int = 0
    misconductMaxAttempts: Optional[int] = None
    minimumOofTimeMs: int = 5000
    secureExamBrowser: int = 0
    calculatorEnabled: int = 0
    restrictSingleIp: int = 0
    tutorialSectionIds: Optional[List[int]] = None
    solFileIds: Optional[List[int]] = None


class SectionCreate(BaseModel):
    """POST /assessments/{type}/{id}/sections body."""
    title: str
    description: Optional[str] = None
    showOneQuestion: int = 0
    allowNavigation: int = 0
    randomizeQuestions: int = 0
    randomizeOptions: int = 0
    # Required when randomizeQuestions=1; must be >= 1.
    randomQuestionCount: Optional[int] = None


class QuestionCreate(BaseModel):
    """POST /assessments/{type}/{id}/sections/{sectionId}/questions body."""
    questionType: str   # mcq_single | mcq_multi | true_false | fib | descriptive
    questionText: str
    score: float
    negativeScore: float        # required — no default per spec
    published: dict             # {status: 0|1}
    allowPartialMarks: int = 0  # not allowed for true_false or mcq_single
    options: Optional[List[McqOptionInput]] = None
    trueFalseAnswer: Optional[int] = None
    blanks: Optional[List[FibBlankInput]] = None
    fibUseRange: Optional[int] = None
    fibRangeLower: Optional[float] = None
    fibRangeUpper: Optional[float] = None
    fileIds: Optional[List[int]] = None


class AnnouncementCreate(BaseModel):
    """POST /announcements/add body."""
    title: str
    description: Optional[str] = None   # nullable in spec
    type: Literal["normal", "urgent"]
    notifyMail: int             # 0=LMS-only, 1=also email
    published: dict             # {status: 0|1, releaseOn: unix|null}
    sectionIds: Optional[List[int]] = None
    fileIds: Optional[List[int]] = None


class AnnouncementUpdate(BaseModel):
    """PUT /announcements/edit/{id} body — all fields optional."""
    title: Optional[str] = None
    description: Optional[str] = None
    type: Optional[Literal["normal", "urgent"]] = None
    notifyMail: Optional[int] = None
    published: Optional[dict] = None
    sectionIds: Optional[List[int]] = None
    fileIds: Optional[List[int]] = None


class LectureCreate(BaseModel):
    """POST /lectures body."""
    title: str
    weekId: int
    topicId: int
    published: int              # 0=draft, 1=published
    modeOfTeaching: Optional[str] = None  # oldRecording|newRecording|liveSession
    releaseOn: Optional[int] = None
    taughtBy: Optional[int] = None


class CourseResourceCreate(BaseModel):
    """One entry in POST /{entityType}/{entityId}/course-resources resources array."""
    resourceType: Literal["file", "audio", "video"]
    resourceFileId: int
    isPrimary: bool = False
