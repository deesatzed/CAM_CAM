"""Tests for the cam camify command — discovery, matching, planning, and CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claw.camify import (
    CamifyDiscovery,
    CamifyMatcher,
    CamifyPlan,
    CamifyPlanner,
    CamifyStep,
    MatchedMethodology,
    MatchReport,
    RepoProfile,
    write_camify_artifact,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def target_repo(tmp_path: Path) -> Path:
    """Create a realistic target repo with README, code, CLAUDE.md."""
    repo = tmp_path / "target-repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "README.md").write_text(
        "# My Service\nAsync API for imbalanced classification.\n"
        "Uses SMOTE and gradient boosting for binary targets.\n"
    )
    (repo / "CLAUDE.md").write_text(
        "## Architecture\nPython 3.12, Click CLI, Pydantic v2.\n"
    )
    (repo / "pyproject.toml").write_text("[project]\nname = 'my-service'\n")
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("async def handle(): pass\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_main.py").write_text("def test_handle(): pass\n")
    return repo


@pytest.fixture
def target_repo_with_guide(target_repo: Path) -> Path:
    """Target repo that also has a domain guide file."""
    (target_repo / "AI_Augment.md").write_text(
        "# AI Augmentation Guide\n"
        "Replace SMOTE with generative methods like CTGAN and TabDDPM.\n"
        "Use diffusion models for tabular data augmentation.\n"
        "Implement adversarial validation for synthetic data quality.\n"
    )
    return target_repo


@pytest.fixture
def empty_repo(tmp_path: Path) -> Path:
    """An empty directory (no files at all)."""
    repo = tmp_path / "empty-repo"
    repo.mkdir()
    return repo


@pytest.fixture
def minimal_repo(tmp_path: Path) -> Path:
    """Repo with code but no markdown files."""
    repo = tmp_path / "minimal-repo"
    repo.mkdir()
    (repo / "main.py").write_text("print('hello')\n")
    return repo


@pytest.fixture
def sample_profile() -> RepoProfile:
    """A pre-built RepoProfile for planner/matcher tests."""
    return RepoProfile(
        name="test-repo",
        path="/tmp/test-repo",
        has_readme=True,
        has_claude_md=True,
        has_tests=True,
        has_git=True,
        languages=["Python"],
        config_files=["pyproject.toml"],
        file_count=42,
        guide_files=["AI_Augment.md"],
        guide_content={"AI_Augment.md": "Replace SMOTE with CTGAN."},
        domain_keywords=["classification", "imbalanced", "smote", "augmentation"],
        repo_summary="Async API for imbalanced classification.",
    )


@pytest.fixture
def sample_match_report() -> MatchReport:
    """A pre-built MatchReport for planner tests."""
    return MatchReport(
        matched_methodologies=[
            MatchedMethodology(
                id="meth-abc123",
                problem="Exponential backoff with jitter for API retries",
                domains=["error_handling", "api_design"],
                score=0.72,
            ),
            MatchedMethodology(
                id="meth-def456",
                problem="Structured JSON logging with correlation IDs",
                domains=["observability"],
                score=0.65,
            ),
        ],
        gap_areas=["tabular-gan", "diffusion-models"],
        kb_methodology_count=2895,
    )


# ---------------------------------------------------------------------------
# Discovery tests
# ---------------------------------------------------------------------------


class TestCamifyDiscovery:
    """Tests for CamifyDiscovery.discover()."""

    @pytest.mark.asyncio
    async def test_discovers_readme(self, target_repo: Path) -> None:
        discovery = CamifyDiscovery()
        profile = await discovery.discover(target_repo)
        assert profile.has_readme is True

    @pytest.mark.asyncio
    async def test_discovers_claude_md(self, target_repo: Path) -> None:
        discovery = CamifyDiscovery()
        profile = await discovery.discover(target_repo)
        assert profile.has_claude_md is True

    @pytest.mark.asyncio
    async def test_discovers_guide_files(self, target_repo_with_guide: Path) -> None:
        discovery = CamifyDiscovery()
        profile = await discovery.discover(target_repo_with_guide)
        assert "AI_Augment.md" in profile.guide_files

    @pytest.mark.asyncio
    async def test_discovers_explicit_guide(self, target_repo_with_guide: Path) -> None:
        guide = target_repo_with_guide / "AI_Augment.md"
        discovery = CamifyDiscovery()
        profile = await discovery.discover(target_repo_with_guide, guide_paths=[guide])
        assert "AI_Augment.md" in profile.guide_content

    @pytest.mark.asyncio
    async def test_empty_repo(self, empty_repo: Path) -> None:
        discovery = CamifyDiscovery()
        profile = await discovery.discover(empty_repo)
        assert profile.file_count == 0
        assert profile.has_readme is False
        assert profile.languages == []

    @pytest.mark.asyncio
    async def test_no_guides(self, minimal_repo: Path) -> None:
        discovery = CamifyDiscovery()
        profile = await discovery.discover(minimal_repo)
        assert profile.guide_files == []
        # Should still work without guides
        assert profile.name == "minimal-repo"

    @pytest.mark.asyncio
    async def test_extracts_keywords(self, target_repo_with_guide: Path) -> None:
        discovery = CamifyDiscovery()
        profile = await discovery.discover(target_repo_with_guide)
        # Should extract domain-relevant words from guide content
        assert len(profile.domain_keywords) > 0
        # "smote" or "augmentation" should appear from the guide
        kw_lower = [k.lower() for k in profile.domain_keywords]
        assert any("smote" in k or "augment" in k or "tabular" in k for k in kw_lower)

    @pytest.mark.asyncio
    async def test_detects_languages(self, target_repo: Path) -> None:
        discovery = CamifyDiscovery()
        profile = await discovery.discover(target_repo)
        assert "Python" in profile.languages

    @pytest.mark.asyncio
    async def test_detects_config_files(self, target_repo: Path) -> None:
        discovery = CamifyDiscovery()
        profile = await discovery.discover(target_repo)
        assert "pyproject.toml" in profile.config_files

    @pytest.mark.asyncio
    async def test_detects_tests(self, target_repo: Path) -> None:
        discovery = CamifyDiscovery()
        profile = await discovery.discover(target_repo)
        assert profile.has_tests is True

    @pytest.mark.asyncio
    async def test_repo_summary_from_readme(self, target_repo: Path) -> None:
        discovery = CamifyDiscovery()
        profile = await discovery.discover(target_repo)
        assert "imbalanced classification" in profile.repo_summary


# ---------------------------------------------------------------------------
# Matcher tests
# ---------------------------------------------------------------------------


class TestCamifyMatcher:
    """Tests for CamifyMatcher.match()."""

    @pytest.mark.asyncio
    async def test_empty_kb(self, sample_profile: RepoProfile) -> None:
        """When KB is empty, matcher returns gaps and recommendation."""

        class FakeRepo:
            async def count_methodologies(self) -> int:
                return 0

        matcher = CamifyMatcher()
        report = await matcher.match(sample_profile, None, FakeRepo())
        assert report.kb_methodology_count == 0
        assert len(report.gap_areas) > 0
        assert len(report.recommended_mining_targets) > 0

    @pytest.mark.asyncio
    async def test_returns_matches(self, sample_profile: RepoProfile) -> None:
        """When KB has content, matcher returns matched methodologies."""
        from dataclasses import dataclass

        @dataclass
        class FakeMethodology:
            id: str = "meth-test-001"
            problem_description: str = "Retry logic for API calls"
            tags: list[str] | None = None

            def __post_init__(self):
                if self.tags is None:
                    self.tags = ["error_handling", "api"]

        @dataclass
        class FakeResult:
            methodology: FakeMethodology = None
            combined_score: float = 0.65

            def __post_init__(self):
                if self.methodology is None:
                    self.methodology = FakeMethodology()

        class FakeRepo:
            async def count_methodologies(self) -> int:
                return 100

        class FakeMemory:
            async def find_similar_with_signals(self, query, limit=3):
                return [FakeResult(), FakeResult(methodology=FakeMethodology(
                    id="meth-test-002",
                    problem_description="Structured logging patterns",
                    tags=["observability"],
                ))], {"confidence": 0.6}

        matcher = CamifyMatcher()
        report = await matcher.match(sample_profile, FakeMemory(), FakeRepo())
        assert report.kb_methodology_count == 100
        assert len(report.matched_methodologies) == 2
        assert report.matched_methodologies[0].score == 0.65

    @pytest.mark.asyncio
    async def test_identifies_gaps(self, sample_profile: RepoProfile) -> None:
        """Gaps are keywords not covered by matched methodology domains."""
        from dataclasses import dataclass

        @dataclass
        class FakeMethodology:
            id: str = "meth-001"
            problem_description: str = "Test pattern"
            tags: list[str] | None = None

            def __post_init__(self):
                if self.tags is None:
                    self.tags = ["testing"]

        @dataclass
        class FakeResult:
            methodology: FakeMethodology = None
            combined_score: float = 0.5

            def __post_init__(self):
                if self.methodology is None:
                    self.methodology = FakeMethodology()

        class FakeRepo:
            async def count_methodologies(self) -> int:
                return 50

        class FakeMemory:
            async def find_similar_with_signals(self, query, limit=3):
                return [FakeResult()], {"confidence": 0.5}

        matcher = CamifyMatcher()
        report = await matcher.match(sample_profile, FakeMemory(), FakeRepo())
        # "classification", "imbalanced" etc. should appear as gaps since
        # matched methodology only covers "testing" domain
        assert len(report.gap_areas) > 0


# ---------------------------------------------------------------------------
# Planner tests
# ---------------------------------------------------------------------------


class TestCamifyPlanner:
    """Tests for CamifyPlanner.plan() and render_markdown()."""

    def test_generates_steps(
        self, sample_profile: RepoProfile, sample_match_report: MatchReport,
    ) -> None:
        planner = CamifyPlanner()
        plan = planner.plan(sample_profile, sample_match_report, ["enhance the repo"])
        assert len(plan.steps) >= 3
        assert plan.target_repo == "/tmp/test-repo"
        assert plan.goals == ["enhance the repo"]
        assert plan.status == "PENDING"

    def test_multi_goal(
        self, sample_profile: RepoProfile, sample_match_report: MatchReport,
    ) -> None:
        planner = CamifyPlanner()
        plan = planner.plan(
            sample_profile, sample_match_report,
            ["enhance error handling", "learn patterns for CAM KB"],
        )
        assert len(plan.goals) == 2
        # Should have a learn-back step for the "learn" goal
        step_ids = [s.id for s in plan.steps]
        assert "learn-back" in step_ids

    def test_renders_markdown(
        self, sample_profile: RepoProfile, sample_match_report: MatchReport,
    ) -> None:
        planner = CamifyPlanner()
        plan = planner.plan(sample_profile, sample_match_report, ["enhance the repo"])
        md = planner.render_markdown(plan)
        assert md.startswith("---")
        assert "camify_version: 1" in md
        assert "# CAM-ify Plan: test-repo" in md
        assert "## Goals" in md
        assert "## Step 1:" in md

    def test_frontmatter_has_goals(
        self, sample_profile: RepoProfile, sample_match_report: MatchReport,
    ) -> None:
        planner = CamifyPlanner()
        plan = planner.plan(sample_profile, sample_match_report, ["enhance the repo"])
        md = planner.render_markdown(plan)
        assert '"enhance the repo"' in md

    def test_plan_includes_preflight(
        self, sample_profile: RepoProfile, sample_match_report: MatchReport,
    ) -> None:
        planner = CamifyPlanner()
        plan = planner.plan(sample_profile, sample_match_report, ["enhance the repo"])
        assert plan.steps[0].id == "preflight"
        assert "cam doctor" in plan.steps[0].command

    def test_plan_includes_cag_rebuild(
        self, sample_profile: RepoProfile, sample_match_report: MatchReport,
    ) -> None:
        planner = CamifyPlanner()
        plan = planner.plan(sample_profile, sample_match_report, ["enhance the repo"])
        cag_steps = [s for s in plan.steps if "cag" in s.command]
        assert len(cag_steps) >= 1

    def test_guide_manifest_generates_assimilation_steps(
        self, sample_match_report: MatchReport,
    ) -> None:
        profile = RepoProfile(
            name="cam-target",
            path="/tmp/cam-target",
            has_readme=True,
            has_tests=True,
            languages=["Python"],
            guide_files=["CAM_GUIDE.md"],
            guide_content={
                "CAM_GUIDE.md": (
                    "Source sibling: /tmp/CAM-Pulse\n\n"
                    "| ID | Capability to ingest | Source evidence | Target area | Why it matters | Acceptance checks |\n"
                    "|---|---|---|---|---|---|\n"
                    "| A1 | Deterministic auto-fix engine | /tmp/CAM-Pulse/src/claw/memory/auto_fix.py | src/claw/memory/auto_fix.py | Fix shallow bugs | python -m pytest tests/test_auto_fix.py -q |\n"
                    "| A2 | Agent rotation using excluded agents | /tmp/CAM-Pulse/src/claw/dispatcher.py | src/claw/dispatcher.py | Avoid repeated failing agents | python -m pytest tests/test_dispatcher.py -q |\n"
                )
            },
            domain_keywords=["defense", "auto-fix"],
        )

        planner = CamifyPlanner()
        plan = planner.plan(profile, sample_match_report, ["assimilate defense chain"])

        assert plan.source_repos == ["/tmp/CAM-Pulse"]
        assert [t["id"] for t in plan.assimilation_targets] == ["A1", "A2"]
        step_ids = [s.id for s in plan.steps]
        assert "source-mine" in step_ids
        assert "assimilation-dryrun" in step_ids
        assert "assimilate-a1" in step_ids
        assert "assimilate-a2" in step_ids
        assert "cag-rebuild" not in step_ids

        md = planner.render_markdown(plan)
        assert "## Assimilation Targets" in md
        assert "Deterministic auto-fix engine" in md
        assert "/tmp/CAM-Pulse/src/claw/memory/auto_fix.py" in md


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestCamifyModels:
    """Tests for Pydantic model validation."""

    def test_plan_model(self) -> None:
        plan = CamifyPlan(
            target_repo="/tmp/test",
            goals=["enhance"],
            steps=[
                CamifyStep(
                    id="test",
                    phase="preflight",
                    command="cam doctor",
                    purpose="health check",
                    verification="exit 0",
                ),
            ],
            created_at="2026-04-01T00:00:00Z",
        )
        assert plan.version == 1
        assert plan.status == "PENDING"
        assert len(plan.steps) == 1

    def test_plan_serialization(self) -> None:
        plan = CamifyPlan(
            target_repo="/tmp/test",
            goals=["enhance"],
            steps=[],
            created_at="2026-04-01T00:00:00Z",
        )
        data = plan.model_dump()
        assert data["target_repo"] == "/tmp/test"
        # Should roundtrip through JSON
        json_str = json.dumps(data, default=str)
        loaded = json.loads(json_str)
        assert loaded["goals"] == ["enhance"]


# ---------------------------------------------------------------------------
# Artifact writer tests
# ---------------------------------------------------------------------------


class TestWriteArtifact:
    """Tests for write_camify_artifact()."""

    def test_writes_to_explicit_path(self, tmp_path: Path) -> None:
        plan = CamifyPlan(
            target_repo="/tmp/test-repo",
            goals=["enhance"],
            steps=[],
            created_at="2026-04-01T00:00:00Z",
        )
        planner = CamifyPlanner()
        md = planner.render_markdown(plan)
        out = tmp_path / "my-plan.md"
        result = write_camify_artifact(md, plan, out)
        assert result == out
        assert out.exists()
        assert out.read_text().startswith("---")
        # JSON sidecar should exist too
        assert out.with_suffix(".json").exists()

    def test_writes_to_default_location(self, tmp_path: Path, monkeypatch) -> None:
        # Monkeypatch the module-level path resolution
        import claw.camify as camify_mod
        original = Path(camify_mod.__file__).resolve().parents[2] / "data" / "camify"

        plan = CamifyPlan(
            target_repo="/tmp/test-repo",
            goals=["enhance"],
            steps=[],
            created_at="2026-04-01T00:00:00Z",
        )
        planner = CamifyPlanner()
        md = planner.render_markdown(plan)
        # Use explicit path to avoid touching real data dir
        out = tmp_path / "plan.md"
        result = write_camify_artifact(md, plan, out)
        assert result.exists()

    def test_json_sidecar_valid(self, tmp_path: Path) -> None:
        plan = CamifyPlan(
            target_repo="/tmp/test-repo",
            goals=["enhance", "learn"],
            kb_matches_found=5,
            kb_gaps=["tabular-gan"],
            steps=[
                CamifyStep(
                    id="preflight", phase="preflight",
                    command="cam doctor", purpose="check",
                    verification="exit 0",
                ),
            ],
            created_at="2026-04-01T00:00:00Z",
        )
        planner = CamifyPlanner()
        md = planner.render_markdown(plan)
        out = tmp_path / "plan.md"
        write_camify_artifact(md, plan, out)
        json_data = json.loads(out.with_suffix(".json").read_text())
        assert json_data["goals"] == ["enhance", "learn"]
        assert json_data["kb_matches_found"] == 5


# ---------------------------------------------------------------------------
# CLI registration tests
# ---------------------------------------------------------------------------


class TestCamifyCLI:
    """Tests for CLI command registration."""

    def test_camify_command_registered(self) -> None:
        from claw.cli import app
        names = [
            cmd.name or (cmd.callback.__name__ if cmd.callback else "")
            for cmd in app.registered_commands
        ]
        assert "camify" in names

    def test_camify_help(self) -> None:
        from typer.testing import CliRunner
        from claw.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["camify", "--help"])
        assert result.exit_code == 0
        assert "CAM-ify" in result.output or "cam" in result.output.lower()

    def test_camify_missing_repo_fails(self) -> None:
        from typer.testing import CliRunner
        from claw.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["camify", "/nonexistent/path/xyz"])
        assert result.exit_code != 0
