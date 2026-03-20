"""
Tests for agent/core.py logic that doesn't require live API calls.
Covers shell safety checks, result truncation, and budget guard.
"""
import json
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_agent():
    """Return an Agent with a mocked Memory and a no-op send_message."""
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

    from unittest.mock import MagicMock
    mem = MagicMock()
    mem.get_active_goals.return_value = []
    mem.recall_relevant.return_value = []
    mem.get_behavior_config.return_value = {}
    mem.get_api_calls_today.return_value = 0

    with patch("agent.core.AsyncOpenAI"):
        from agent.core import Agent
        agent = Agent(memory=mem, send_message_fn=AsyncMock())
    return agent


# ── Shell safety ───────────────────────────────────────────────────────────

class TestIsReadonlyShell:
    def setup_method(self):
        self.agent = _make_agent()

    def test_plain_ls_is_readonly(self):
        assert self.agent._is_readonly_shell("ls -la") is True

    def test_ls_with_pipe_is_not_readonly(self):
        assert self.agent._is_readonly_shell("ls | rm -rf /") is False

    def test_ls_with_semicolon_is_not_readonly(self):
        assert self.agent._is_readonly_shell("ls; rm foo") is False

    def test_ls_with_redirect_is_not_readonly(self):
        assert self.agent._is_readonly_shell("ls > /tmp/out") is False

    def test_subshell_injection_blocked(self):
        assert self.agent._is_readonly_shell("echo $(rm -rf ~)") is False

    def test_backtick_injection_blocked(self):
        assert self.agent._is_readonly_shell("echo `id`") is False

    def test_cat_is_readonly(self):
        assert self.agent._is_readonly_shell("cat /etc/hosts") is True

    def test_grep_is_readonly(self):
        assert self.agent._is_readonly_shell("grep -r foo .") is True

    def test_rm_is_not_readonly(self):
        assert self.agent._is_readonly_shell("rm -rf /tmp/test") is False

    def test_curl_is_not_readonly(self):
        # curl isn't in the readonly set
        assert self.agent._is_readonly_shell("curl https://example.com") is False

    def test_empty_command(self):
        assert self.agent._is_readonly_shell("") is False

    def test_full_path_readonly(self):
        # /bin/ls should still be recognised
        assert self.agent._is_readonly_shell("/bin/ls -la") is True

    def test_ampersand_background_blocked(self):
        assert self.agent._is_readonly_shell("sleep 100 &") is False


# ── _needs_approval ────────────────────────────────────────────────────────

class TestNeedsApproval:
    def setup_method(self):
        self.agent = _make_agent()

    @pytest.mark.asyncio
    async def test_read_only_shell_needs_no_approval(self):
        result = await self.agent._needs_approval("run_shell", {"command": "ls -la"})
        assert result is None

    @pytest.mark.asyncio
    async def test_destructive_shell_needs_approval_with_risk(self):
        result = await self.agent._needs_approval("run_shell", {"command": "rm -rf /tmp/foo"})
        assert result is not None
        assert "needs approval" in result
        assert "Risks:" in result
        assert "Recursive/force delete" in result

    @pytest.mark.asyncio
    async def test_sudo_command_explains_root_risk(self):
        result = await self.agent._needs_approval("run_shell", {"command": "sudo chmod 777 /etc"})
        assert result is not None
        assert "root/admin privileges" in result
        assert "permissions" in result

    @pytest.mark.asyncio
    async def test_send_email_always_needs_approval(self):
        result = await self.agent._needs_approval("send_email", {"to": "x@x.com", "subject": "hi", "body": "hi"})
        assert result is not None

    @pytest.mark.asyncio
    async def test_web_search_needs_no_approval(self):
        result = await self.agent._needs_approval("web_search", {"query": "test"})
        assert result is None

    @pytest.mark.asyncio
    async def test_linkedin_post_needs_approval(self):
        result = await self.agent._needs_approval("linkedin_post", {"content": "hi"})
        assert result is not None

    @pytest.mark.asyncio
    async def test_readonly_pipe_needs_no_approval(self):
        result = await self.agent._needs_approval("run_shell", {"command": "ps aux | grep python"})
        assert result is None

    @pytest.mark.asyncio
    async def test_readonly_pipe_multiple_stages_needs_no_approval(self):
        result = await self.agent._needs_approval("run_shell", {"command": "cat file.txt | grep foo | wc -l"})
        assert result is None

    @pytest.mark.asyncio
    async def test_shell_pipe_with_destructive_cmd_needs_approval(self):
        result = await self.agent._needs_approval("run_shell", {"command": "ls | rm dangerous"})
        assert result is not None
        assert "Risks:" in result


# ── _truncate_tool_result ──────────────────────────────────────────────────

class TestTruncateToolResult:
    def setup_method(self):
        self.agent = _make_agent()

    def test_small_result_unchanged(self):
        result = {"success": True, "content": "short"}
        out = self.agent._truncate_tool_result(result)
        assert out == result
        assert "_truncated" not in out

    def test_large_content_is_truncated(self):
        big = "x" * 5000
        result = {"success": True, "content": big}
        out = self.agent._truncate_tool_result(result)
        assert len(out["content"]) < len(big)
        assert "truncated" in out["content"]
        assert out.get("_truncated") is True

    def test_non_string_fields_pass_through(self):
        result = {"success": True, "count": 42, "items": [1, 2, 3]}
        out = self.agent._truncate_tool_result(result)
        assert out["count"] == 42
        assert out["items"] == [1, 2, 3]

    def test_multiple_large_fields_all_truncated(self):
        result = {"stdout": "a" * 3000, "stderr": "b" * 3000}
        out = self.agent._truncate_tool_result(result)
        assert len(out["stdout"]) <= 900
        assert len(out["stderr"]) <= 900


# ── Memory: task loop detection ────────────────────────────────────────────

class TestMemoryTaskCountToday:
    def test_returns_zero_with_no_tasks(self, tmp_path):
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

        # Patch config paths to use temp dir
        with patch("config.MEMORY_DB_PATH", str(tmp_path / "memory.db")), \
             patch("config.CHROMA_DB_PATH", str(tmp_path / "chroma")):
            from agent.memory import Memory
            mem = Memory()
            assert mem.get_task_count_today("nonexistent-goal-id") == 0

    def test_counts_tasks_created_today(self, tmp_path):
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

        with patch("config.MEMORY_DB_PATH", str(tmp_path / "memory.db")), \
             patch("config.CHROMA_DB_PATH", str(tmp_path / "chroma")):
            from agent.memory import Memory
            mem = Memory()
            goal_id = mem.create_goal("Test goal", "Test description")
            mem.add_goal_task(goal_id, "Task 1")
            mem.add_goal_task(goal_id, "Task 2")
            mem.add_goal_task(goal_id, "Task 3")
            assert mem.get_task_count_today(goal_id) == 3


# ── Memory: behavior config ────────────────────────────────────────────────

class TestBehaviorConfig:
    def test_set_and_get_behavior(self, tmp_path):
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

        with patch("config.MEMORY_DB_PATH", str(tmp_path / "memory.db")), \
             patch("config.CHROMA_DB_PATH", str(tmp_path / "chroma")):
            from agent.memory import Memory
            mem = Memory()
            mem.set_behavior_config("focus_area", "LinkedIn outreach")
            mem.set_behavior_config("response_style", "concise bullets")
            config = mem.get_behavior_config()
            assert config["focus_area"] == "LinkedIn outreach"
            assert config["response_style"] == "concise bullets"

    def test_overwrite_behavior(self, tmp_path):
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

        with patch("config.MEMORY_DB_PATH", str(tmp_path / "memory.db")), \
             patch("config.CHROMA_DB_PATH", str(tmp_path / "chroma")):
            from agent.memory import Memory
            mem = Memory()
            mem.set_behavior_config("tone", "formal")
            mem.set_behavior_config("tone", "casual")
            assert mem.get_behavior_config()["tone"] == "casual"


# ── API budget tracking ────────────────────────────────────────────────────

class TestApiBudget:
    def test_records_and_counts_calls(self, tmp_path):
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

        with patch("config.MEMORY_DB_PATH", str(tmp_path / "memory.db")), \
             patch("config.CHROMA_DB_PATH", str(tmp_path / "chroma")):
            from agent.memory import Memory
            mem = Memory()
            assert mem.get_api_calls_today() == 0
            mem.record_api_call("deepseek-chat", "chat")
            mem.record_api_call("deepseek-chat", "chat")
            mem.record_api_call("deepseek-chat", "autonomous")
            assert mem.get_api_calls_today() == 3

    def test_stats_returns_list(self, tmp_path):
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

        with patch("config.MEMORY_DB_PATH", str(tmp_path / "memory.db")), \
             patch("config.CHROMA_DB_PATH", str(tmp_path / "chroma")):
            from agent.memory import Memory
            mem = Memory()
            mem.record_api_call("deepseek-chat", "chat")
            stats = mem.get_api_call_stats(days=7)
            assert len(stats) >= 1
            assert "date" in stats[0]
            assert "calls" in stats[0]
