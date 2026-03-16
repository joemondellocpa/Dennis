"""GitHub tool – read/write repos, issues, PRs."""
from typing import Optional
import config


def _client():
    from github import Github
    return Github(config.GITHUB_TOKEN)


async def list_repos() -> dict:
    try:
        g = _client()
        user = g.get_user()
        repos = [{"name": r.name, "description": r.description, "url": r.html_url}
                 for r in user.get_repos()[:20]]
        return {"success": True, "repos": repos}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def get_repo_info(repo_name: str) -> dict:
    try:
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
    except Exception as e:
        return {"success": False, "error": str(e)}


async def read_file(repo_name: str, file_path: str, ref: str = "main") -> dict:
    try:
        g = _client()
        r = g.get_repo(f"{config.GITHUB_USERNAME}/{repo_name}")
        content = r.get_contents(file_path, ref=ref)
        return {"success": True, "content": content.decoded_content.decode()}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def create_issue(repo_name: str, title: str, body: str, labels: list[str] = None) -> dict:
    try:
        g = _client()
        r = g.get_repo(f"{config.GITHUB_USERNAME}/{repo_name}")
        issue = r.create_issue(title=title, body=body, labels=labels or [])
        return {"success": True, "issue_url": issue.html_url, "number": issue.number}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def list_issues(repo_name: str, state: str = "open") -> dict:
    try:
        g = _client()
        r = g.get_repo(f"{config.GITHUB_USERNAME}/{repo_name}")
        issues = [
            {"number": i.number, "title": i.title, "url": i.html_url, "state": i.state}
            for i in r.get_issues(state=state)[:20]
        ]
        return {"success": True, "issues": issues}
    except Exception as e:
        return {"success": False, "error": str(e)}
