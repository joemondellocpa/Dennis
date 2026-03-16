"""
Tool registry: OpenAI function-call schema definitions + dispatcher.
All tools are exposed to DeepSeek via the function-calling API.
"""
import json
from typing import Any

# ── Tool definitions (OpenAI function-call format) ─────────────────────────
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "Execute a shell command on the Mac mini. Use for file operations, running scripts, opening apps, checking system status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The shell command to run"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web via DuckDuckGo. Use for research, finding information, market research.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"},
                    "num_results": {"type": "integer", "description": "Number of results (default 5)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_page",
            "description": "Fetch and extract text content from a specific URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to fetch"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_emails",
            "description": "List emails from Gmail. Supports Gmail search syntax in the query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Gmail search query (e.g. 'is:unread', 'from:someone@example.com')"},
                    "max_results": {"type": "integer", "description": "Max emails to return (default 10)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_email_body",
            "description": "Get the full body text of an email by message ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "Gmail message ID"},
                },
                "required": ["message_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Send an email via Gmail.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address"},
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Email body (plain text)"},
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_calendar_events",
            "description": "List upcoming Google Calendar events.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days_ahead": {"type": "integer", "description": "How many days ahead to look (default 7)"},
                    "max_results": {"type": "integer", "description": "Max events to return (default 10)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_calendar_event",
            "description": "Create a Google Calendar event.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Event title"},
                    "start_time": {"type": "string", "description": "Start time in ISO 8601 format (e.g. 2024-01-15T10:00:00)"},
                    "end_time": {"type": "string", "description": "End time in ISO 8601 format"},
                    "description": {"type": "string", "description": "Event description"},
                    "attendees": {"type": "array", "items": {"type": "string"}, "description": "List of attendee email addresses"},
                },
                "required": ["summary", "start_time", "end_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_repos",
            "description": "List your GitHub repositories.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_repo_info",
            "description": "Get info about a specific GitHub repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_name": {"type": "string", "description": "Repository name (without username)"},
                },
                "required": ["repo_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_github_issue",
            "description": "Create an issue on a GitHub repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_name": {"type": "string"},
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "labels": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["repo_name", "title", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "linkedin_post",
            "description": "Publish a post to LinkedIn. Always get user approval before posting.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The post content"},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "linkedin_search_people",
            "description": "Search LinkedIn for people by keywords (e.g. job title, company, industry).",
            "parameters": {
                "type": "object",
                "properties": {
                    "keywords": {"type": "string", "description": "Search keywords"},
                    "connection_degree": {"type": "string", "description": "2nd or 3rd (default 2nd)"},
                },
                "required": ["keywords"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "linkedin_send_connection",
            "description": "Send a LinkedIn connection request. Always get user approval before sending.",
            "parameters": {
                "type": "object",
                "properties": {
                    "profile_url": {"type": "string", "description": "LinkedIn profile URL"},
                    "message": {"type": "string", "description": "Optional personal note (max 300 chars)"},
                },
                "required": ["profile_url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember_fact",
            "description": "Store a persistent fact about the user, their preferences, or important context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Fact category (e.g. 'user_preferences', 'contacts', 'business')"},
                    "key": {"type": "string", "description": "Unique key for this fact"},
                    "value": {"type": "string", "description": "The fact value"},
                },
                "required": ["category", "key", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall_facts",
            "description": "Retrieve stored facts by category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Fact category to retrieve"},
                },
                "required": ["category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": "Semantic search over past conversations and knowledge base.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_knowledge",
            "description": "Save a piece of research or learned information to the knowledge base.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The knowledge to save"},
                    "source": {"type": "string", "description": "Where this came from"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags for categorization"},
                },
                "required": ["content", "source"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_goal",
            "description": "Create a new autonomous goal for Dennis to pursue in the background.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short goal title"},
                    "description": {"type": "string", "description": "Detailed goal description with success criteria"},
                    "priority": {"type": "integer", "description": "Priority 1-10 (10 = highest)"},
                },
                "required": ["title", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_goals",
            "description": "List all active autonomous goals.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_goal",
            "description": "Add a progress note to an existing goal.",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal_id": {"type": "string"},
                    "progress_note": {"type": "string"},
                },
                "required": ["goal_id", "progress_note"],
            },
        },
    },
]

# ── Dispatcher ─────────────────────────────────────────────────────────────
async def dispatch_tool(name: str, args: dict, memory=None) -> Any:
    """Route a tool call to its implementation."""
    from tools import shell, browser, github_tool, google_tool, linkedin_tool, memory_tool

    handlers = {
        # Shell
        "run_shell": lambda: shell.run_shell(**args),
        # Browser
        "web_search": lambda: browser.web_search(**args),
        "fetch_page": lambda: browser.fetch_page(**args),
        # Google
        "list_emails": lambda: google_tool.list_emails(**args),
        "get_email_body": lambda: google_tool.get_email_body(**args),
        "send_email": lambda: google_tool.send_email(**args),
        "list_calendar_events": lambda: google_tool.list_calendar_events(**args),
        "create_calendar_event": lambda: google_tool.create_calendar_event(**args),
        # GitHub
        "list_repos": lambda: github_tool.list_repos(),
        "get_repo_info": lambda: github_tool.get_repo_info(**args),
        "create_github_issue": lambda: github_tool.create_issue(**args),
        # LinkedIn
        "linkedin_post": lambda: linkedin_tool.create_post(**args),
        "linkedin_search_people": lambda: linkedin_tool.search_people(**args),
        "linkedin_send_connection": lambda: linkedin_tool.send_connection_request(**args),
        # Memory (require memory instance)
        "remember_fact": lambda: memory_tool.remember_fact(memory, **args),
        "recall_facts": lambda: memory_tool.recall_facts(memory, **args),
        "search_memory": lambda: memory_tool.search_memory(memory, **args),
        "save_knowledge": lambda: memory_tool.save_knowledge(memory, **args),
        "create_goal": lambda: memory_tool.create_goal(memory, **args),
        "list_goals": lambda: memory_tool.list_goals(memory),
        "update_goal": lambda: memory_tool.update_goal(memory, **args),
        "complete_goal": lambda: memory_tool.complete_goal(memory, **args),
    }

    handler = handlers.get(name)
    if not handler:
        return {"success": False, "error": f"Unknown tool: {name}"}

    result = await handler()
    return result
