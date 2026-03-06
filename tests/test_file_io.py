"""Tests for file I/O code: _extract_save_to_file_request, _infer_file_action,
ForgedWorker read_file, and FileWorker open→read alias."""
from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from beekeeper.contracts import (
    AgentIdentity,
    RuleProfile,
    SkillProfile,
    SoulProfile,
    TaskEnvelope,
    TrustTier,
)
from beekeeper.queen import QueenAgent, QueenConfig
from beekeeper.worker import FileWorker, ForgedWorker, WorkerContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_queen(tmp_path: Path) -> QueenAgent:
    return QueenAgent(
        QueenConfig(
            honeycomb_root=tmp_path / ".honeycomb",
            scheduler_backend="inline",
            vector_backend="memory",
            max_reruns=0,
        )
    )


def _stub_llm(queen: QueenAgent) -> None:
    from beekeeper.worker import ForgedWorker, WebSearchWorker, WorkerKind

    ws = queen.worker_runtime._workers.get(WorkerKind.web_search)
    if isinstance(ws, WebSearchWorker):
        ws.llm_router.call = lambda **kwargs: ("GitHub profile for anmolnoor: developer.", "stub")  # type: ignore
        ws.searxng.search = lambda **kwargs: []  # type: ignore

    fg = queen.worker_runtime._workers.get(WorkerKind.forged)
    if isinstance(fg, ForgedWorker):
        fg.llm_router.call = lambda **kwargs: ("GitHub profile for anmolnoor: developer.", "stub")  # type: ignore


def _make_task(operation: str, file_path: str, content: str = "") -> TaskEnvelope:
    return TaskEnvelope(
        queen_trace_id="t1",
        queen_request_id="r1",
        task_type="file_op",
        idempotency_key=str(uuid4()),
        payload={"operation": operation, "file_path": file_path, "content": content},
    )


def _make_context() -> WorkerContext:
    return WorkerContext(
        identity=AgentIdentity(
            agent_type="file",
            skill_profile_id="s1",
            soul_profile_id="sp1",
        ),
        skill=SkillProfile(
            skill_profile_id="s1",
            name="file",
            description="file worker",
        ),
        rule=RuleProfile(rule_profile_id="r1", name="file"),
        soul=SoulProfile(soul_profile_id="sp1", name="default"),
    )


# ---------------------------------------------------------------------------
# Group 1: _extract_save_to_file_request — 7 tests
# ---------------------------------------------------------------------------

class TestExtractSaveToFileRequest:
    def test_explicit_md_filename(self) -> None:
        ok, fname = QueenAgent._extract_save_to_file_request(
            "write the output to report.md"
        )
        assert ok is True
        assert fname == "report.md"

    def test_explicit_txt_filename(self) -> None:
        ok, fname = QueenAgent._extract_save_to_file_request(
            "write the results to output.txt"
        )
        assert ok is True
        assert fname == "output.txt"

    def test_markdown_file_no_filename(self) -> None:
        ok, fname = QueenAgent._extract_save_to_file_request(
            "create a report and save it in a markdown file"
        )
        assert ok is True
        assert fname.endswith(".md")
        assert len(fname) > 3

    def test_user_bug_query(self) -> None:
        ok, fname = QueenAgent._extract_save_to_file_request(
            "go to github and create a report and save it in a markdown file from user anmolnoor"
        )
        assert ok is True
        assert fname.endswith(".md")
        assert len(fname) > 3

    def test_export_keyword(self) -> None:
        ok, fname = QueenAgent._extract_save_to_file_request(
            "export it to summary.md"
        )
        assert ok is True
        assert fname == "summary.md"

    def test_dot_md_file_named_phrase(self) -> None:
        ok, fname = QueenAgent._extract_save_to_file_request(
            "save the report as an .md file named anmolnoor_github_report.md"
        )
        assert ok is True
        assert fname == "anmolnoor_github_report.md"

    def test_strips_trailing_punctuation_from_filename(self) -> None:
        ok, fname = QueenAgent._extract_save_to_file_request(
            "write the output to anmolnoor_github_report.md."
        )
        assert ok is True
        assert fname == "anmolnoor_github_report.md"

    def test_no_save_intent(self) -> None:
        ok, fname = QueenAgent._extract_save_to_file_request(
            "search github for anmolnoor"
        )
        assert ok is False
        assert fname == ""

    def test_plain_chat(self) -> None:
        ok, fname = QueenAgent._extract_save_to_file_request(
            "what is the weather today"
        )
        assert ok is False
        assert fname == ""


# ---------------------------------------------------------------------------
# Group 2: _infer_file_action new read operation — 4 tests
# ---------------------------------------------------------------------------

class TestInferFileAction:
    def test_open_by_name(self) -> None:
        result = QueenAgent._infer_file_action("open report.md")
        assert result is not None
        assert result["operation"] == "read"
        assert result["file_path"] == "report.md"

    def test_show_file(self) -> None:
        result = QueenAgent._infer_file_action("show anmolnoor_github_report.md")
        assert result is not None
        assert result["operation"] == "read"
        assert result["file_path"] == "anmolnoor_github_report.md"

    def test_read_the_file(self) -> None:
        result = QueenAgent._infer_file_action("read the output.txt")
        assert result is not None
        assert result["operation"] == "read"
        assert result["file_path"] == "output.txt"

    def test_non_file_query_returns_none(self) -> None:
        result = QueenAgent._infer_file_action("open a new conversation")
        assert result is None


# ---------------------------------------------------------------------------
# Group 3: ForgedWorker._infer_action_from_query + _execute_action — 4 tests
# ---------------------------------------------------------------------------

class TestForgedWorkerReadFile:
    def _make_forged(self) -> ForgedWorker:
        return ForgedWorker()

    def test_infer_read_file_from_open(self) -> None:
        w = self._make_forged()
        result = w._infer_action_from_query("open foo.txt")
        assert result is not None
        assert result["action"] == "read_file"
        assert result["path"] == "foo.txt"

    def test_execute_read_file_existing(self, tmp_path: Path) -> None:
        w = self._make_forged()
        p = tmp_path / "foo.txt"
        p.write_text("Hello from foo", encoding="utf-8")
        summary, evidence = w._execute_action({"action": "read_file", "path": str(p)})
        assert "Hello from foo" in summary
        assert evidence == [f"read:{p}"]

    def test_execute_read_file_missing(self) -> None:
        w = self._make_forged()
        summary, evidence = w._execute_action(
            {"action": "read_file", "path": "/nonexistent/x.md"}
        )
        assert summary.startswith("File not found:")

    def test_long_file_truncated(self, tmp_path: Path) -> None:
        w = self._make_forged()
        p = tmp_path / "big.txt"
        p.write_text("x" * 3000, encoding="utf-8")
        summary, _ = w._execute_action({"action": "read_file", "path": str(p)})
        assert "... (" in summary


# ---------------------------------------------------------------------------
# Group 4: FileWorker.execute with open→read alias — 2 tests
# ---------------------------------------------------------------------------

class TestFileWorkerOpenAlias:
    def test_open_aliased_to_read(self, tmp_path: Path) -> None:
        w = FileWorker()
        p = tmp_path / "sample.txt"
        p.write_text("sample content", encoding="utf-8")
        task = _make_task("open", str(p))
        ctx = _make_context()
        output = w.execute(task, ctx)
        assert output["success"] is True
        assert output["operation"] == "read"
        assert "sample content" in output["content_preview"]

    def test_read_operation_works(self, tmp_path: Path) -> None:
        w = FileWorker()
        p = tmp_path / "sample.txt"
        p.write_text("sample content", encoding="utf-8")
        task = _make_task("read", str(p))
        ctx = _make_context()
        output = w.execute(task, ctx)
        assert output["success"] is True
        assert output["operation"] == "read"
        assert "sample content" in output["content_preview"]


# ---------------------------------------------------------------------------
# Group 5: Queen post-processing integration — 2 tests
# ---------------------------------------------------------------------------

class TestQueenPostProcessing:
    def test_file_written_when_requested(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        queen = _make_queen(tmp_path)
        _stub_llm(queen)

        # "save it in a markdown file" matches _extract_save_to_file_request (Pattern 1)
        # but NOT _infer_file_action (no explicit file extension in the path group),
        # so ForgedWorker runs and produces assistant_reply from the stub LLM.
        queen.run(
            intent="research_topic",
            payload={
                "query": "research anmolnoor github and save it in a markdown file",
                "delegate_to_worker": True,
            },
        )
        md_files = list(tmp_path.glob("*.md"))
        assert len(md_files) >= 1
        # File must be non-empty (post-processing extracted at least one worker reply)
        assert md_files[0].stat().st_size > 0

    def test_no_file_written_without_save_intent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        queen = _make_queen(tmp_path)
        _stub_llm(queen)

        queen.run(
            intent="research_topic",
            payload={
                "query": "research anmolnoor on github",
                "delegate_to_worker": True,
            },
        )
        md_files = list(tmp_path.glob("*.md"))
        assert len(md_files) == 0

    def test_unverified_save_claim_helpers(self) -> None:
        assert QueenAgent._query_requests_file_save("save this report as markdown") is True
        sanitized = QueenAgent._remove_unverified_save_claims(
            "I analyzed the data.\nReport saved to /tmp/fake_report.md"
        )
        assert "saved to /tmp/fake_report.md" not in sanitized.lower()

    def test_canonicalize_save_reply_uses_only_verified_path(self, tmp_path: Path) -> None:
        saved = tmp_path / "anmolnoor_github_report.md"
        raw = (
            "Analysis complete.\n\n"
            "### 📍 Exact File Path\n"
            "The report has been prepared for storage at:\n"
            "**`reports/anmolnoor_github_report.md`**\n"
            "(Note: mirrored to `/home/anmol_noor/hive_terminal/github/anmolnoor_github_report.md`)."
        )
        reply = QueenAgent._canonicalize_save_reply(
            raw,
            save_requested=True,
            save_succeeded=True,
            save_path=saved,
        )
        assert "reports/anmolnoor_github_report.md" not in reply
        assert "/home/anmol_noor/hive_terminal/github/anmolnoor_github_report.md" not in reply
        assert f"**Report saved to:** `{saved}`" in reply
        assert reply.count("Report saved to") == 1
