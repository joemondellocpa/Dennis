"""Memory management tools exposed to the LLM."""
# These are thin wrappers; the Memory instance is injected at runtime.
# The agent core passes `memory` when calling these.

async def remember_fact(memory, category: str, key: str, value: str) -> dict:
    memory.set_fact(category, key, value)
    return {"success": True, "stored": f"{category}/{key}"}


async def recall_facts(memory, category: str) -> dict:
    facts = memory.get_facts_by_category(category)
    return {"success": True, "facts": facts}


async def search_memory(memory, query: str) -> dict:
    conv = memory.recall_relevant(query, n=5)
    know = memory.search_knowledge(query, n=5)
    return {"success": True, "conversation_memory": conv, "knowledge": know}


async def save_knowledge(memory, content: str, source: str, tags: list[str] = None) -> dict:
    doc_id = memory.add_knowledge(content, source, tags)
    return {"success": True, "id": doc_id}


async def create_goal(memory, title: str, description: str, priority: int = 5) -> dict:
    goal_id = memory.create_goal(title, description, priority)
    return {"success": True, "goal_id": goal_id}


async def list_goals(memory) -> dict:
    goals = memory.get_active_goals()
    return {"success": True, "goals": goals}


async def update_goal(memory, goal_id: str, progress_note: str) -> dict:
    memory.update_goal_progress(goal_id, progress_note)
    return {"success": True}


async def complete_goal(memory, goal_id: str) -> dict:
    memory.complete_goal(goal_id)
    return {"success": True}
