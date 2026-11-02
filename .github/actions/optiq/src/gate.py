"""Decide from the GitHub event whether this run starts, before anything is installed.

Issue and comment text is untrusted, so only GitHub decides who may start a run: the
sender's type and login, and their permission on the repository. The event's
`author_association` is not enough on its own: COLLABORATOR and MEMBER include people
who can only read.
"""
from __future__ import annotations

import json
import os
import re
import subprocess

#: Worth asking GitHub about; anyone else is refused without a call.
ASSOCIATED = {"OWNER", "MEMBER", "COLLABORATOR"}
CAN_WRITE = {"admin", "maintain", "write"}


def mentions(text: str | None, trigger: str) -> bool:
    """The trigger as a whole word, outside quoted lines: quoting a request is not a request."""
    lines = [ln for ln in (text or "").splitlines() if not ln.lstrip().startswith(">")]
    return bool(re.search(rf"(?<![\w/-]){re.escape(trigger)}(?![\w-])", "\n".join(lines), re.I))


#: The branches this bot works on; the number is the issue the work started from.
BRANCH = re.compile(r"^optiq/issue-(\d+)(?:-\d+)?$")


def own_thread(branch: str | None, head_repo: str | None, repo: str) -> str | None:
    """The issue number of one of the bot's own branches in this repository, else None.
    A fork's branch never counts: a fork can name its branch anything."""
    m = BRANCH.match(branch or "")
    return m.group(1) if m and head_repo == repo else None


def decide(event_name: str, event: dict, trigger: str, allowed: set[str], repo: str,
           pr_head=lambda number: (None, None),
           permission=lambda login: "none") -> tuple[str | None, str]:
    """(thread, why): the issue number a run belongs to, or None when no run starts.

    `pr_head(number)` gives a pull request's branch and repository, which a comment's
    event does not carry; `permission(login)` gives a sender's permission on the
    repository. Both are only asked once the rest of the event has passed.
    """
    sender = event.get("sender") or {}

    def trusted(item: dict) -> bool:
        login = sender.get("login") or ""
        if login.lower() in allowed:
            return True
        return item.get("author_association") in ASSOCIATED and permission(login) in CAN_WRITE

    if event_name == "workflow_run":
        run = event.get("workflow_run") or {}
        if run.get("conclusion") != "failure" or run.get("event") != "pull_request":
            return None, "not a failed pull request check"
        head = (run.get("head_repository") or {}).get("full_name")
        thread = own_thread(run.get("head_branch"), head, repo)
        return thread, "CI failed" if thread else "CI of another branch"
    if sender.get("type") == "Bot":
        return None, "sent by a bot"
    if event_name == "pull_request_review":
        review = event.get("review") or {}
        if (review.get("state") or "").lower() == "approved":
            return None, "an approval"
        if not trusted(review):
            return None, f"{sender.get('login')} may not start a run"
        head = (event.get("pull_request") or {}).get("head") or {}
        thread = own_thread(head.get("ref"), (head.get("repo") or {}).get("full_name"), repo)
        return thread, "a review" if thread else "a review of another pull request"
    if event_name == "issues":
        item = event.get("issue") or {}
    elif event_name == "issue_comment":
        item = event.get("comment") or {}
    else:
        return None, f"event {event_name}"
    if not mentions(item.get("body"), trigger):
        return None, f"no {trigger}"
    if not trusted(item):
        return None, f"{sender.get('login')} may not start a run"
    issue = event.get("issue") or {}
    if "pull_request" in issue:
        thread = own_thread(*pr_head(issue["number"]), repo)
        return thread, "a comment" if thread else "a comment on another pull request"
    return str(issue["number"]), f"{sender.get('login')} asked"


def pr_head_from_github(number: int) -> tuple[str | None, str | None]:
    out = subprocess.run(["gh", "api", f"repos/{os.environ['GITHUB_REPOSITORY']}/pulls/{number}"],
                         text=True, capture_output=True)
    if out.returncode:
        return None, None
    head = json.loads(out.stdout)["head"]
    return head["ref"], (head.get("repo") or {}).get("full_name")


def permission_from_github(login: str) -> str:
    out = subprocess.run(["gh", "api", f"repos/{os.environ['GITHUB_REPOSITORY']}/collaborators/{login}/permission"],
                         text=True, capture_output=True)
    return json.loads(out.stdout).get("permission", "none") if out.returncode == 0 else "none"


def main() -> None:
    with open(os.environ["GITHUB_EVENT_PATH"]) as f:
        event = json.load(f)
    allowed = {u.strip().lower() for u in os.environ.get("INPUT_ALLOWED_USERS", "").split(",") if u.strip()}
    thread, why = decide(os.environ["GITHUB_EVENT_NAME"], event, os.environ["INPUT_TRIGGER"], allowed,
                         os.environ["GITHUB_REPOSITORY"], pr_head_from_github, permission_from_github)
    print(f"optiq: {'starting' if thread else 'skipping'}: {why}")
    with open(os.environ["GITHUB_OUTPUT"], "a") as f:
        f.write(f"run={'true' if thread else 'false'}\nthread={thread or ''}\n")


if __name__ == "__main__":
    main()
