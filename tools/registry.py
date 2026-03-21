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
            "description": "Execute a shell command on the Mac mini. Use for file operations, running scripts, checking system status. Requires explicit user approval for any non-read-only command.",
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
            "description": "Send an email via Gmail. Always get user approval before sending.",
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
            "name": "drive_list_files",
            "description": "List files in Google Drive. Supports Drive search syntax (e.g. \"name contains 'report'\", \"mimeType='application/vnd.google-apps.spreadsheet'\").",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Drive search query. Leave empty to list recent files."},
                    "max_results": {"type": "integer", "description": "Max files to return (default 20)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "drive_read_file",
            "description": "Download and read the text content of a Google Drive file. Google Docs are exported as plain text, Sheets as CSV.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_id": {"type": "string", "description": "Google Drive file ID"},
                },
                "required": ["file_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "drive_upload_file",
            "description": "Upload a text file to Google Drive.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "File name (including extension)"},
                    "content": {"type": "string", "description": "Text content to upload"},
                    "parent_folder_id": {"type": "string", "description": "Optional Drive folder ID to upload into"},
                    "mime_type": {"type": "string", "description": "MIME type (default: text/plain)"},
                },
                "required": ["name", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "drive_create_folder",
            "description": "Create a folder in Google Drive.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Folder name"},
                    "parent_folder_id": {"type": "string", "description": "Optional parent folder ID"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sheets_create",
            "description": "Create a new Google Spreadsheet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Spreadsheet title"},
                    "sheets": {"type": "array", "items": {"type": "string"}, "description": "Optional list of sheet/tab names to create"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sheets_read",
            "description": "Read values from a Google Sheet range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID"},
                    "range_": {"type": "string", "description": "A1 notation range (e.g. 'Sheet1!A1:D10'). Defaults to 'Sheet1'."},
                },
                "required": ["spreadsheet_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sheets_write",
            "description": "Write values to a Google Sheet, overwriting the specified range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID"},
                    "range_": {"type": "string", "description": "A1 notation range (e.g. 'Sheet1!A1')"},
                    "values": {"type": "array", "items": {"type": "array"}, "description": "2D array of values (rows × columns)"},
                },
                "required": ["spreadsheet_id", "range_", "values"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sheets_append",
            "description": "Append rows to the end of a Google Sheet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID"},
                    "range_": {"type": "string", "description": "Sheet name or range to append after (e.g. 'Sheet1')"},
                    "values": {"type": "array", "items": {"type": "array"}, "description": "2D array of rows to append"},
                },
                "required": ["spreadsheet_id", "range_", "values"],
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
            "name": "create_goal_task",
            "description": "Add a concrete, actionable task to an existing goal's queue.",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal_id": {"type": "string", "description": "The goal ID to add this task to"},
                    "description": {"type": "string", "description": "Specific, actionable task description"},
                },
                "required": ["goal_id", "description"],
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
    {
        "type": "function",
        "function": {
            "name": "complete_goal",
            "description": "Mark a goal as completed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal_id": {"type": "string", "description": "The goal ID to complete"},
                },
                "required": ["goal_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_behavior",
            "description": (
                "Persist a behavioral preference or working style override. "
                "Use this when the owner asks you to change how you behave "
                "(e.g. 'focus on LinkedIn outreach', 'only notify for high-priority findings', "
                "'be more concise'). These preferences survive restarts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Setting name (e.g. 'focus_area', 'notification_threshold', 'response_style')",
                    },
                    "value": {"type": "string", "description": "The new value for this preference"},
                },
                "required": ["key", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_draft",
            "description": (
                "Save a draft email or LinkedIn post for user review instead of sending immediately. "
                "Use this in autonomous mode whenever you want to send an email or post to LinkedIn. "
                "The user will be notified and can approve, edit, or reject the draft via /drafts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "draft_type": {
                        "type": "string",
                        "enum": ["email", "linkedin_post"],
                        "description": "Type of draft",
                    },
                    "title": {"type": "string", "description": "Short descriptive title for the draft"},
                    "content": {"type": "string", "description": "Full draft content"},
                    "metadata": {
                        "type": "object",
                        "description": "For email: {to, subject}. For linkedin_post: {}",
                    },
                },
                "required": ["draft_type", "title", "content"],
            },
        },
    },
]

# ── Dispatcher ─────────────────────────────────────────────────────────────
async def dispatch_tool(name: str, args: dict, memory=None) -> Any:
    """Route a tool call to its implementation."""
    import config
    from tools import shell, github_tool, google_tool, linkedin_tool, memory_tool

    if config.LIGHTWEIGHT_MODE:
        from tools import browser_lite as browser
    else:
        from tools import browser

    handlers = {
        # Shell
        "run_shell": lambda: shell.run_shell(**args),
        # Browser
        "web_search": lambda: browser.web_search(**args),
        "fetch_page": lambda: browser.fetch_page(**args),
        # Google - Gmail
        "list_emails": lambda: google_tool.list_emails(**args),
        "get_email_body": lambda: google_tool.get_email_body(**args),
        "send_email": lambda: google_tool.send_email(**args),
        # Google - Calendar
        "list_calendar_events": lambda: google_tool.list_calendar_events(**args),
        "create_calendar_event": lambda: google_tool.create_calendar_event(**args),
        # Google - Drive
        "drive_list_files": lambda: google_tool.drive_list_files(**args),
        "drive_read_file": lambda: google_tool.drive_read_file(**args),
        "drive_upload_file": lambda: google_tool.drive_upload_file(**args),
        "drive_create_folder": lambda: google_tool.drive_create_folder(**args),
        # Google - Sheets
        "sheets_create": lambda: google_tool.sheets_create(**args),
        "sheets_read": lambda: google_tool.sheets_read(**args),
        "sheets_write": lambda: google_tool.sheets_write(**args),
        "sheets_append": lambda: google_tool.sheets_append(**args),
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
        "create_goal_task": lambda: memory_tool.create_goal_task(memory, **args),
        "list_goals": lambda: memory_tool.list_goals(memory),
        "update_goal": lambda: memory_tool.update_goal(memory, **args),
        "complete_goal": lambda: memory_tool.complete_goal(memory, **args),
        "update_behavior": lambda: memory_tool.update_behavior(memory, **args),
        "save_draft": lambda: memory_tool.save_draft(memory, **args),
    }

    handler = handlers.get(name)
    if not handler:
        return {"success": False, "error": f"Unknown tool: {name}"}

    result = await handler()
    return result
