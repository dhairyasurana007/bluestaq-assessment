from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Team Notes API</title>
<style>
  body { font: 16px/1.5 system-ui, sans-serif; max-width: 42rem; margin: 2rem auto;
         padding: 0 1rem; }
  code, pre { font-family: ui-monospace, Consolas, monospace; background: rgba(127,127,127,.15); }
  code { padding: .1em .3em; border-radius: 4px; }
  pre { padding: .75rem; overflow-x: auto; border-radius: 6px; }
  li { margin: .25rem 0; }
</style>
</head>
<body>
<h1>Team Notes API</h1>
<p>A small REST service for notes shared across team spaces. This is the API root, so start
with one of the links below.</p>

<h2>Where to go</h2>
<ul>
  <li><a href="/app"><code>/app</code></a>: the notes web app: create teams and notes in the
      browser.</li>
  <li><a href="/docs"><code>/docs</code></a>: interactive API docs. Try every endpoint
      from here.</li>
  <li><a href="/api/v1/teams"><code>/api/v1/teams</code></a>: the demo teams
      (<code>Platform</code> and <code>Research</code>).</li>
  <li><a href="/health"><code>/health</code></a>: liveness check and the deployed commit.</li>
  <li><a href="https://github.com/dhairyasurana007/bluestaq-assessment#readme">README</a>:
      quick start, API overview and design decisions.</li>
</ul>

<h2>Try it</h2>
<pre>curl -s &lt;this-url&gt;/api/v1/teams
curl -s -X POST &lt;this-url&gt;/api/v1/teams \\
  -H 'Content-Type: application/json' -d '{"name": "My team"}'</pre>

<h2>Good to know</h2>
<ul>
  <li>There are no accounts: anyone with this URL can read, write, edit and delete.</li>
  <li>Editing a note needs an <code>If-Match</code> header with its <code>ETag</code>
      (otherwise 428; a stale one gives 412).</li>
  <li>Deleted notes go to a per-team trash and can be restored.</li>
  <li>The free instance sleeps when idle, so the first request can take up to a minute.</li>
  <li>The demo database resets on every deploy and is reseeded with demo data.</li>
</ul>
</body>
</html>
"""


@router.get("/", include_in_schema=False)
def root() -> HTMLResponse:
    return HTMLResponse(_PAGE)
