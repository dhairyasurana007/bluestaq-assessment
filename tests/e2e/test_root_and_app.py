"""E2E: the API root guide page (GET /) and the web app page (GET /app), over plain HTTP."""

from html.parser import HTMLParser

from playwright.sync_api import APIRequestContext

from tests.e2e.helpers import make_team

README_URL = "https://github.com/dhairyasurana007/bluestaq-assessment#readme"


class _Tags(HTMLParser):
    """Collects every start tag as (tag, attrs-dict)."""

    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def _parse(html: str) -> list[tuple[str, dict[str, str | None]]]:
    parser = _Tags()
    parser.feed(html)
    return parser.tags


def _anchors(html: str) -> list[dict[str, str | None]]:
    return [attrs for tag, attrs in _parse(html) if tag == "a"]


# ----- GET / ----------------------------------------------------------------


def test_root_is_html_guide(api: APIRequestContext):
    resp = api.get("/")
    assert resp.status == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "Team Notes API" in resp.text()


def test_root_links_to_every_entry_point(api: APIRequestContext):
    hrefs = {a.get("href") for a in _anchors(api.get("/").text())}
    for expected in ("/app", "/docs", "/api/v1/teams", "/health", README_URL):
        assert expected in hrefs, f"missing link {expected}; found {sorted(h or '' for h in hrefs)}"


def test_root_anchors_open_in_new_tab_safely(api: APIRequestContext):
    anchors = _anchors(api.get("/").text())
    assert len(anchors) >= 5
    for a in anchors:
        assert a.get("target") == "_blank", f"anchor {a.get('href')} lacks target=_blank"
        assert "noopener" in (a.get("rel") or "").split(), f"anchor {a.get('href')} lacks noopener"


def test_root_groups_links_for_people_and_programs(api: APIRequestContext):
    body = api.get("/").text()
    assert "<h2>For people</h2>" in body
    assert "For programs" in body
    people, programs = body.index("For people"), body.index("For programs")
    assert people < programs
    # Each link sits under the heading for its audience.
    for href in ('href="/app"', 'href="/docs"', f'href="{README_URL}"'):
        assert people < body.index(href) < programs, href
    for href in ('href="/api/v1/teams"', 'href="/health"'):
        assert body.index(href) > programs, href


def test_root_ignores_accept_json(api: APIRequestContext):
    resp = api.get("/", headers={"Accept": "application/json"})
    assert resp.status == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "Team Notes API" in resp.text()


# ----- GET /app -------------------------------------------------------------


def test_app_is_full_html_document(api: APIRequestContext):
    resp = api.get("/app")
    assert resp.status == 200
    assert resp.headers["content-type"].startswith("text/html")
    body = resp.text()
    assert body.lstrip().lower().startswith("<!doctype html")
    assert "</html>" in body
    assert any(tag == "title" for tag, _ in _parse(body))
    assert "<title>" in body and "</title>" in body


def test_app_talks_to_same_origin_api(api: APIRequestContext):
    assert "/api/v1" in api.get("/app").text()


def test_app_references_no_external_origin(api: APIRequestContext):
    body = api.get("/app").text()
    tags = _parse(body)
    for tag, attrs in tags:
        # No external script files at all: everything is inline.
        assert not (tag == "script" and "src" in attrs), f"external <script src>: {attrs}"
        if tag == "link":
            href = attrs.get("href") or ""
            assert not href.startswith(("http://", "https://", "//")), f"external <link>: {href}"
        for name in ("src", "href"):
            value = attrs.get(name) or ""
            if value.startswith(("http://", "https://", "//")):
                assert value == README_URL, f"unexpected external {name}={value} on <{tag}>"
    assert "<script src=" not in body


# ----- OpenAPI exclusion ----------------------------------------------------


def test_root_and_app_hidden_from_openapi(api: APIRequestContext):
    paths = api.get("/openapi.json").json()["paths"]
    assert "/" not in paths
    assert "/app" not in paths
    assert "/health" in paths
    assert "/api/v1/teams" in paths


# ----- Trailing slash and unknown paths -------------------------------------


def test_app_trailing_slash_is_not_a_server_error(api: APIRequestContext):
    assert api.get("/app/").status < 500
    assert api.head("/app/").status < 500


def test_unknown_path_is_problem_json_404(api: APIRequestContext):
    for method in (api.get, api.head):
        resp = method("/nope")
        assert resp.status == 404
    resp = api.get("/nope")
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["status"] == 404


# ----- API / pages consistency ----------------------------------------------


def test_pages_unaffected_by_api_writes(api: APIRequestContext):
    team = make_team(api)
    fetched = api.get(f"/api/v1/teams/{team['id']}")
    assert fetched.status == 200
    assert fetched.json()["id"] == team["id"]
    assert api.get("/").status == 200
    assert api.get("/app").status == 200


def test_app_ignores_accept_json(api: APIRequestContext):
    resp = api.get("/app", headers={"Accept": "application/json"})
    assert resp.status == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert resp.text().lstrip().lower().startswith("<!doctype html")
