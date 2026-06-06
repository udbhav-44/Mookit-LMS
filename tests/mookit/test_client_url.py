"""Lock the live mooKIT URL scheme: {base}/{course}/{endpoint}."""

import httpx
import respx

from app.contracts import RequestContext
from app.mookit.client import MooKitClient

BASE = "https://test.mookit.in/v2/api"


def _ctx() -> RequestContext:
    return RequestContext(
        instance_id="test.mookit.in", course_id="coursetest", user_id=1, session_id="s",
        forwarded_headers={"course": "coursetest", "token": "jwt", "uid": "1"},
    )


@respx.mock
async def test_users_me_url_includes_course():
    route = respx.get(f"{BASE}/coursetest/users/me").mock(
        return_value=httpx.Response(200, json={"success": True, "code": 200, "message": "ok",
                                               "data": {"id": 1, "name": "Inst"}})
    )
    async with httpx.AsyncClient() as http:
        client = MooKitClient(http=http, base_url_resolver=lambda _i: BASE)
        user = await client.users_me(_ctx())
    assert route.called
    assert user.id == 1
    # Header still carries course + token.
    sent = route.calls.last.request
    assert sent.headers.get("course") == "coursetest"
    assert sent.headers.get("token") == "jwt"


@respx.mock
async def test_taxonomy_and_assessment_urls():
    respx.get(f"{BASE}/coursetest/taxonomies/week").mock(
        return_value=httpx.Response(200, json={"success": True, "code": 200, "message": "ok",
                                               "data": [{"id": 104, "name": "Week 4", "type": "week"}]})
    )
    post = respx.post(f"{BASE}/coursetest/assessments/quizzes").mock(
        return_value=httpx.Response(200, json={"success": True, "code": 200, "message": "ok",
                                               "data": {"id": 7, "title": "Q"}})
    )
    async with httpx.AsyncClient() as http:
        client = MooKitClient(http=http, base_url_resolver=lambda _i: BASE)
        terms = await client.list_taxonomy(_ctx(), "week")
        from app.mookit.schemas import AssessmentCreate
        await client.create_assessment(_ctx(), "quizzes", AssessmentCreate(
            title="Q", startDate=0, endDate=1, endDapDate=1, resultsDate=2, published={"status": 0},
        ))
    assert terms[0].name == "Week 4"
    assert post.called
