"""GitHub tool – read/write repos, issues, PRs.

All PyGitHub calls are synchronous/blocking. We run them in threads via
asyncio.to_thread() so they don't stall the event loop.
"""
import asyncio
from typing import Optional
import config


def _client():
    from github import Github
    return Github(config.GITHUB_TOKEN)


async def list_repos() -> dict:
    def _fetch():
        g = _client()
        repos = [
            {"name": r.name, "description": r.description, "url": r.html_url}
            for r in list(g.get_user().get_repos())[:20]
        ]
        return {"success": True, "repos": repos}
    try:
        return await asyncio.to_thread(_fetch)
    except Exception as e:
        return {"success": False, "error": str(e)}


async def get_repo_info(repo_name: str) -> dict:
    def _fetch():
        g = _client()
        r = g.get_repo(f"{config.GITHUB_USERNAME}/{repo_name}")
        return {
            "success": True,
            "name": r.name,
            "description": r.description,
            "language": r.language,
            "stars": r.stargazers_count,
            "open_issues": r.open_issues_count,
            "url": r.html_url,
        }
    try:
        return await asyncio.to_thread(_fetch)
    except Exception as e:
        return {"success": False, "error": str(e)}


async def read_file(repo_name: str, file_path: str, ref: str = "main") -> dict:
    def _fetch():
        g = _client()
        r = g.get_repo(f"{config.GITHUB_USERNAME}/{repo_name}")
        content = r.get_contents(file_path, ref=ref)
        return {"success": True, "content": content.decoded_content.decode()}
    try:
        return await asyncio.to_thread(_fetch)
    except Exception as e:
        return {"success": False, "error": str(e)}


async def create_issue(repo_name: str, title: str, body: str, labels: list[str] = None) -> dict:
    def _create():
        g = _client()
        r = g.get_repo(f"{config.GITHUB_USERNAME}/{repo_name}")
        issue = r.create_issue(title=title, body=body, labels=labels or [])
        return {"success": True, "issue_url": issue.html_url, "number": issue.number}
    try:
        return await asyncio.to_thread(_create)
    except Exception as e:
        return {"success": False, "error": str(e)}


async def list_issues(repo_name: str, state: str = "open") -> dict:
    def _fetch():
        g = _client()
        r = g.get_repo(f"{config.GITHUB_USERNAME}/{repo_name}")
        issues = [
            {"number": i.number, "title": i.title, "url": i.html_url, "state": i.state}
            for i in list(r.get_issues(state=state))[:20]
        ]
        return {"success": True, "issues": issues}
    try:
        return await asyncio.to_thread(_fetch)
    except Exception as e:
        return {"success": False, "error": str(e)}
