#!/usr/bin/env bash
# Walkthrough of the Team Notes API using only bash and curl.
#
# Usage: bash examples/walkthrough.sh [BASE_URL]
#   BASE_URL defaults to http://127.0.0.1:8000
#   e.g.   bash examples/walkthrough.sh https://team-notes-api.onrender.com
#
# Steps: create a team, create a note, read it with its ETag, edit it with If-Match, try a stale
# edit (412), delete the note (to the trash), list the trash, and restore the note.
# The team it creates is left in place; its name starts with "walkthrough-".

set -u

BASE="${1:-http://127.0.0.1:8000}"
BASE="${BASE%/}"
API="/api/v1"

# Globals filled in by request(): the full response (headers + body, CRs removed).
RESPONSE=""

# request METHOD PATH [extra curl args...]
# Runs curl, stores the response in $RESPONSE and aborts if the server is unreachable.
request() {
  local method="$1" path="$2"
  shift 2
  RESPONSE="$(curl -sS -i --max-time 90 -X "$method" "$BASE$path" "$@" | tr -d '\r')"
  if [ -z "$RESPONSE" ]; then
    echo "No response from $BASE$path (is the server running and reachable?)" >&2
    exit 1
  fi
}

# Pieces of $RESPONSE.
status_line() { printf '%s\n' "$RESPONSE" | head -n 1; }
headers() { printf '%s\n' "$RESPONSE" | sed -n '1,/^$/p'; }
body() { printf '%s\n' "$RESPONSE" | sed '1,/^$/d'; }
header_value() { headers | grep -i "^$1:" | head -n 1 | sed 's/^[^:]*: *//'; }

# Print the status line, the interesting headers and the body.
show() {
  status_line
  headers | grep -i -E '^(location|etag|content-type):' || true
  local b
  b="$(body)"
  if [ -n "$b" ]; then
    echo "$b"
  else
    echo "(empty body)"
  fi
  echo
}

heading() {
  echo "=============================================================="
  echo "$1"
  echo "=============================================================="
}

# Pull the first "id" value out of a JSON body (the top-level object always lists "id" first).
json_id() { body | sed -n 's/^{"id":"\([^"]*\)".*/\1/p' | head -n 1; }

die() {
  echo "Walkthrough aborted: $1" >&2
  exit 1
}

echo "Base URL: $BASE"
echo "(The first request can take up to a minute if the server was asleep.)"
echo

TEAM_NAME="walkthrough-$(date +%s)-$RANDOM"
JSON='Content-Type: application/json'

heading "1. Create a team ($TEAM_NAME)"
request POST "$API/teams" -H "$JSON" -d "{\"name\":\"$TEAM_NAME\"}"
show
TEAM_ID="$(json_id)"
[ -n "$TEAM_ID" ] || die "could not read the team id from the response above"
echo "TEAM_ID=$TEAM_ID"
echo

heading "2. Create a note in the team"
request POST "$API/teams/$TEAM_ID/notes" -H "$JSON" \
  -d '{"title":"Walkthrough note","body":"First draft.","author_name":"Walkthrough"}'
show
NOTE_ID="$(json_id)"
[ -n "$NOTE_ID" ] || die "could not read the note id from the response above"
echo "NOTE_ID=$NOTE_ID"
echo

heading "3. Read the note and its ETag"
request GET "$API/notes/$NOTE_ID"
show
ETAG="$(header_value etag)"
[ -n "$ETAG" ] || die "no ETag header in the response above"
echo "ETAG=$ETAG"
echo

heading "4. Edit the note with If-Match: $ETAG (expect 200 and a new ETag)"
request PATCH "$API/notes/$NOTE_ID" -H "$JSON" -H "If-Match: $ETAG" \
  -d '{"body":"Second draft, edited with If-Match."}'
show
NEW_ETAG="$(header_value etag)"
echo "NEW_ETAG=$NEW_ETAG"
echo

heading "5. Edit again with the OLD ETag $ETAG (expect 412 Precondition Failed)"
request PATCH "$API/notes/$NOTE_ID" -H "$JSON" -H "If-Match: $ETAG" \
  -d '{"body":"This stale edit must be rejected."}'
show

heading "6. Delete the note (expect 204; it moves to the trash)"
request DELETE "$API/notes/$NOTE_ID"
show

heading "7. The note is gone from normal reads (expect 404)"
request GET "$API/notes/$NOTE_ID"
show

heading "8. List the team's trash (the note should be there with deleted_at set)"
request GET "$API/teams/$TEAM_ID/trash"
show

heading "9. Restore the note (expect 200, deleted_at null, version bumped, new ETag)"
request POST "$API/notes/$NOTE_ID/restore"
show

heading "10. Read the restored note"
request GET "$API/notes/$NOTE_ID"
show

echo "Done. The team '$TEAM_NAME' (id $TEAM_ID) was left in place."
echo "To remove it: curl -X DELETE $BASE$API/teams/$TEAM_ID"
