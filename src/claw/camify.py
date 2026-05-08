"""CAM-ify planner — discover, match, and plan repo enhancements.

Automates the manual workflow: read a target repo's files, cross-reference
with CAM's knowledge base, and generate an executable step-by-step plan.
"""

from __future__ import annotations

import json
import logging
import re
import time as _time
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Guide file auto-detection patterns
# ---------------------------------------------------------------------------
GUIDE_NAME_PATTERNS = [
    "AI_*.md", "*augment*.md", "*enhance*.md", "*roadmap*.md",
    "*upgrade*.md", "*improve*.md", "*backlog*.md", "*TODO*.md",
]

# Keyword extraction: words we consider domain-relevant when they appear
# in guide files or README content.
_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "must", "to", "of",
    "in", "for", "on", "with", "at", "by", "from", "as", "into", "through",
    "during", "before", "after", "above", "below", "between", "under",
    "again", "further", "then", "once", "here", "there", "when", "where",
    "why", "how", "all", "each", "every", "both", "few", "more", "most",
    "other", "some", "such", "no", "nor", "not", "only", "own", "same",
    "so", "than", "too", "very", "just", "because", "but", "and", "or",
    "if", "while", "about", "this", "that", "these", "those", "it", "its",
    "you", "your", "we", "our", "they", "their", "he", "she", "his", "her",
    "what", "which", "who", "whom", "using", "use", "used", "also", "new",
    "one", "two", "based", "like", "make", "get", "set", "see", "way",
})

# Minimum word length for keyword extraction
_MIN_KEYWORD_LEN = 4


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class RepoProfile(BaseModel):
    """Fingerprint of a target repository."""
    name: str
    path: str
    has_readme: bool = False
    has_claude_md: bool = False
    has_spec: bool = False
    has_git: bool = False
    has_tests: bool = False
    languages: list[str] = Field(default_factory=list)
    config_files: list[str] = Field(default_factory=list)
    file_count: int = 0
    guide_files: list[str] = Field(default_factory=list)
    guide_content: dict[str, str] = Field(default_factory=dict)
    domain_keywords: list[str] = Field(default_factory=list)
    repo_summary: str = ""


class MatchedMethodology(BaseModel):
    """A KB methodology that matches the target repo's domain."""
    id: str = ""
    problem: str = ""
    domains: list[str] = Field(default_factory=list)
    score: float = 0.0


class MatchReport(BaseModel):
    """Results from cross-referencing repo profile with CAM KB."""
    matched_methodologies: list[MatchedMethodology] = Field(default_factory=list)
    gap_areas: list[str] = Field(default_factory=list)
    kb_methodology_count: int = 0
    recommended_mining_targets: list[str] = Field(default_factory=list)


class CamifyStep(BaseModel):
    """A single step in the generated plan."""
    id: str
    phase: str  # preflight | mine | match | evaluate | enhance | post
    command: str
    purpose: str
    verification: str
    required: bool = True
    fallback: Optional[str] = None


class CamifyPlan(BaseModel):
    """The full CAM-ify plan artifact."""
    version: int = 1
    target_repo: str
    goals: list[str] = Field(default_factory=list)
    guide_files_used: list[str] = Field(default_factory=list)
    source_repos: list[str] = Field(default_factory=list)
    assimilation_targets: list[dict[str, str]] = Field(default_factory=list)
    kb_matches_found: int = 0
    kb_gaps: list[str] = Field(default_factory=list)
    steps: list[CamifyStep] = Field(default_factory=list)
    created_at: str = ""
    status: str = "PENDING"


# ---------------------------------------------------------------------------
# CamifyDiscovery — fingerprint the target repo
# ---------------------------------------------------------------------------

class CamifyDiscovery:
    """Discovers and fingerprints a target repository."""

    async def discover(
        self,
        repo_path: Path,
        guide_paths: list[Path] | None = None,
    ) -> RepoProfile:
        """Analyze a target repo and build a profile.

        Args:
            repo_path: Path to the target repository.
            guide_paths: Explicit guide file paths (auto-detected if empty).

        Returns:
            RepoProfile with metadata, guide content, and domain keywords.
        """
        repo_path = repo_path.resolve()
        name = repo_path.name

        # Structural analysis (mirrors _analyze_repo pattern)
        has_readme = any(
            (repo_path / f).exists()
            for f in ["README.md", "readme.md", "README", "README.rst"]
        )
        has_claude_md = (repo_path / "CLAUDE.md").exists()
        has_spec = any(
            (repo_path / f).exists()
            for f in ["spec.json", "spec.yaml", "spec.yml"]
        )
        has_git = (repo_path / ".git").exists()
        has_tests = any(
            (repo_path / d).exists()
            for d in ["tests", "test", "spec", "__tests__"]
        )

        # Count files and detect languages
        ext_counts: dict[str, int] = {}
        total = 0
        for f in repo_path.rglob("*"):
            if f.is_file() and ".git" not in f.parts:
                total += 1
                ext = f.suffix.lower() or "(no ext)"
                ext_counts[ext] = ext_counts.get(ext, 0) + 1

        lang_map = {
            ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
            ".rs": "Rust", ".go": "Go", ".java": "Java", ".rb": "Ruby",
            ".cpp": "C++", ".c": "C", ".cs": "C#", ".swift": "Swift",
        }
        languages = [lang for ext, lang in lang_map.items() if ext in ext_counts]

        config_file_names = [
            "pyproject.toml", "package.json", "Cargo.toml", "go.mod",
            "pom.xml", "build.gradle", "Gemfile", "Makefile",
            "docker-compose.yml", "Dockerfile",
        ]
        config_files = [f for f in config_file_names if (repo_path / f).exists()]

        # Discover guide files
        guide_files: list[Path] = []
        if guide_paths:
            guide_files = [p.resolve() for p in guide_paths if p.exists()]
        else:
            guide_files = self._auto_detect_guides(repo_path)

        # Always include CLAUDE.md and README.md if they exist
        for special in ["CLAUDE.md", "README.md"]:
            p = repo_path / special
            if p.exists() and p not in guide_files:
                guide_files.append(p)

        # Read guide content
        guide_content: dict[str, str] = {}
        for gf in guide_files:
            try:
                content = gf.read_text(encoding="utf-8", errors="replace")
                guide_content[gf.name] = content[:50_000]  # Cap per file
            except OSError:
                logger.warning("Could not read guide file: %s", gf)

        # Extract domain keywords
        all_text = " ".join(guide_content.values())
        domain_keywords = self._extract_keywords(all_text)

        # Build repo summary (first 2000 chars of README if available)
        repo_summary = ""
        for readme_name in ["README.md", "readme.md", "README"]:
            readme_path = repo_path / readme_name
            if readme_path.exists():
                try:
                    repo_summary = readme_path.read_text(
                        encoding="utf-8", errors="replace"
                    )[:2000]
                except OSError:
                    pass
                break

        return RepoProfile(
            name=name,
            path=str(repo_path),
            has_readme=has_readme,
            has_claude_md=has_claude_md,
            has_spec=has_spec,
            has_git=has_git,
            has_tests=has_tests,
            languages=languages,
            config_files=config_files,
            file_count=total,
            guide_files=[str(gf.relative_to(repo_path)) for gf in guide_files if gf.is_relative_to(repo_path)],
            guide_content=guide_content,
            domain_keywords=domain_keywords,
            repo_summary=repo_summary,
        )

    def _auto_detect_guides(self, repo_path: Path) -> list[Path]:
        """Find guide/roadmap .md files in repo root and docs/."""
        found: list[Path] = []
        search_dirs = [repo_path]
        docs_dir = repo_path / "docs"
        if docs_dir.is_dir():
            search_dirs.append(docs_dir)

        for search_dir in search_dirs:
            for pattern in GUIDE_NAME_PATTERNS:
                for match in search_dir.glob(pattern):
                    if match.is_file() and match not in found:
                        found.append(match)
        return found

    @staticmethod
    def _extract_keywords(text: str, max_keywords: int = 30) -> list[str]:
        """Extract domain keywords from text via simple word frequency."""
        words = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{3,}", text.lower())
        freq: dict[str, int] = {}
        for w in words:
            if w not in _STOPWORDS and len(w) >= _MIN_KEYWORD_LEN:
                freq[w] = freq.get(w, 0) + 1
        # Sort by frequency descending, take top N
        ranked = sorted(freq.items(), key=lambda x: -x[1])
        return [w for w, _ in ranked[:max_keywords]]


# ---------------------------------------------------------------------------
# CamifyMatcher — cross-reference with CAM KB
# ---------------------------------------------------------------------------

class CamifyMatcher:
    """Cross-references a repo profile with CAM's knowledge base."""

    async def match(
        self,
        profile: RepoProfile,
        semantic_memory: Any,
        repository: Any,
    ) -> MatchReport:
        """Search KB for methodologies relevant to the target repo.

        Args:
            profile: Target repo profile from CamifyDiscovery.
            semantic_memory: SemanticMemory instance with find_similar_with_signals().
            repository: Repository instance with count_methodologies().

        Returns:
            MatchReport with matches, gaps, and recommendations.
        """
        kb_count = await repository.count_methodologies()

        if kb_count == 0:
            return MatchReport(
                kb_methodology_count=0,
                gap_areas=profile.domain_keywords[:5],
                recommended_mining_targets=[
                    "Mine repos in the target domain to build KB first"
                ],
            )

        # Build query from domain keywords + repo summary
        query_parts = profile.domain_keywords[:15]
        if profile.repo_summary:
            query_parts.insert(0, profile.repo_summary[:500])
        query = " ".join(query_parts)

        results, signals = await semantic_memory.find_similar_with_signals(
            query=query,
            limit=10,
        )

        matched: list[MatchedMethodology] = []
        seen_domains: set[str] = set()
        for r in results:
            meth = r.methodology
            domains = []
            if hasattr(meth, "tags") and meth.tags:
                domains = [t for t in meth.tags if ":" not in t][:3]
            seen_domains.update(domains)
            matched.append(MatchedMethodology(
                id=meth.id[:12] if hasattr(meth, "id") else "",
                problem=getattr(meth, "problem_description", "")[:200],
                domains=domains,
                score=round(getattr(r, "combined_score", getattr(r, "score", 0.0)), 3),
            ))

        # Identify gaps: keywords not covered by matched domains
        gap_areas = [
            kw for kw in profile.domain_keywords[:10]
            if kw not in seen_domains
            and not any(kw in d for d in seen_domains)
        ][:5]

        return MatchReport(
            matched_methodologies=matched,
            gap_areas=gap_areas,
            kb_methodology_count=kb_count,
        )


# ---------------------------------------------------------------------------
# CamifyPlanner — generate executable plan
# ---------------------------------------------------------------------------

class CamifyPlanner:
    """Generates a step-by-step CAM-ification plan."""

    @staticmethod
    def _clean_guide_cell(value: str) -> str:
        """Normalize a markdown table cell into compact plain text."""
        cleaned = value.strip()
        cleaned = cleaned.replace("`", "")
        cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip()

    def _extract_source_repos(self, profile: RepoProfile) -> list[str]:
        """Extract absolute source repo paths mentioned in guide content."""
        text = "\n".join(profile.guide_content.values())
        candidates = re.findall(r"/[^\s`|]+CAM[-_][^\s`|]+", text)
        repos: list[str] = []
        for candidate in candidates:
            # Strip punctuation that may be adjacent in prose.
            path = candidate.rstrip(".,);]")
            for marker in ("/src/", "/tests/", "/docs/", "/scripts/", "/packages/", "/apps/"):
                if marker in path:
                    path = path.split(marker, 1)[0]
                    break
            local_path = Path(path)
            if path.startswith("/") and local_path.exists() and not local_path.is_dir():
                continue
            if path.startswith("/") and local_path.suffix and not local_path.is_dir():
                continue
            if path == profile.path or path.startswith(f"{profile.path}/"):
                continue
            if path.startswith("//"):
                continue
            if path not in repos:
                repos.append(path)
        return repos

    def _extract_assimilation_targets(
        self, profile: RepoProfile
    ) -> list[dict[str, str]]:
        """Extract explicit A1/A2/... assimilation targets from guide tables.

        This lets domain guides act as constrained merge manifests instead of
        only keyword sources. Rows are expected to look like:

        | A1 | Capability | Source evidence | Target area | Why | Acceptance |
        """
        targets: list[dict[str, str]] = []
        for guide_name, content in profile.guide_content.items():
            for raw_line in content.splitlines():
                line = raw_line.strip()
                if not re.match(r"^\|\s*A\d+\s*\|", line):
                    continue
                cells = [self._clean_guide_cell(c) for c in line.strip("|").split("|")]
                if len(cells) < 6:
                    continue
                targets.append({
                    "id": cells[0],
                    "capability": cells[1],
                    "source": cells[2],
                    "target": cells[3],
                    "why": cells[4],
                    "acceptance": cells[5],
                    "guide": guide_name,
                })
        return targets

    def plan(
        self,
        profile: RepoProfile,
        matches: MatchReport,
        goals: list[str],
    ) -> CamifyPlan:
        """Generate a CamifyPlan from profile, matches, and goals."""
        steps: list[CamifyStep] = []
        repo = profile.path
        source_repos = self._extract_source_repos(profile)
        assimilation_targets = self._extract_assimilation_targets(profile)

        # Step 1: Always start with pre-flight
        steps.append(CamifyStep(
            id="preflight",
            phase="preflight",
            command="cam doctor environment",
            purpose="Verify CAM installation, API keys, and database health",
            verification="Exit code 0, all checks green",
        ))

        steps.append(CamifyStep(
            id="govern-check",
            phase="preflight",
            command="cam govern stats",
            purpose="Verify KB has methodologies to apply",
            verification=f"Shows {matches.kb_methodology_count}+ methodologies",
        ))

        steps.append(CamifyStep(
            id="target-write-policy",
            phase="preflight",
            command=(
                f"git -C {repo} status --short && "
                f"git -C {repo} branch --show-current && "
                f"git -C {repo} log -1 --oneline"
            ),
            purpose=(
                "Snapshot target repo state and choose branch, patch artifact, "
                "or explicit direct-push approval before code changes"
            ),
            verification=(
                "Target HEAD, dirty state, and write destination are recorded; "
                "direct main pushes require explicit approval"
            ),
        ))

        if assimilation_targets:
            source_repo = source_repos[0] if source_repos else repo
            steps.append(CamifyStep(
                id="source-mine",
                phase="mine",
                command=(
                    f"cam mine {source_repo}"
                    f" --target {repo}"
                    f" --max-repos 1 --depth 5 --max-minutes 30"
                ),
                purpose=(
                    "Mine the source sibling named in the guide before enhancing "
                    "the target champion"
                ),
                verification=(
                    "cam govern stats increases, and CAM records methodologies "
                    "related to the guide's assimilation targets"
                ),
            ))

            steps.append(CamifyStep(
                id="assimilation-dryrun",
                phase="evaluate",
                command=f"cam enhance {repo} --battery --dry-run --verbose",
                purpose=(
                    "Generate a target-specific task plan and verify it mentions "
                    "the guide's assimilation targets before code changes"
                ),
                verification=(
                    "Dry-run task list mentions auto-fix, failure knowledge, "
                    "agent rotation, verifier hardening, or other A-targets"
                ),
            ))

            for target in assimilation_targets:
                acceptance = target.get("acceptance", "")
                steps.append(CamifyStep(
                    id=f"assimilate-{target['id'].lower()}",
                    phase="enhance",
                    command=f"cam enhance {repo} --mode attended --max-tasks 1 --verbose",
                    purpose=(
                        f"{target['id']}: {target['capability']}. "
                        f"Source: {target['source']}. "
                        f"Target: {target['target']}. "
                        f"Reason: {target['why']}"
                    ),
                    verification=acceptance or "Target-specific tests pass",
                ))

            steps.append(CamifyStep(
                id="assimilation-full-validation",
                phase="post",
                command="python -m pytest -q",
                purpose="Run full target validation after all accepted assimilation patches",
                verification=(
                    "Full suite passes, or unrelated pre-existing failures are "
                    "documented separately from assimilation failures"
                ),
            ))

            guide_files_used = profile.guide_files
            created_at = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
            return CamifyPlan(
                target_repo=repo,
                goals=goals,
                guide_files_used=guide_files_used,
                source_repos=source_repos,
                assimilation_targets=assimilation_targets,
                kb_matches_found=len(matches.matched_methodologies),
                kb_gaps=matches.gap_areas,
                steps=steps,
                created_at=created_at,
            )

        # Step 2: Mine if KB has gaps or goals include learning
        needs_mine = (
            len(matches.gap_areas) > 0
            or any("learn" in g.lower() for g in goals)
            or matches.kb_methodology_count == 0
        )

        if needs_mine:
            # Determine mine target based on goals
            mine_target = repo
            for g in goals:
                if "learn" in g.lower() and "cam" in g.lower():
                    mine_target = "."  # Mine into CAM's own KB
                    break

            steps.append(CamifyStep(
                id="mine",
                phase="mine",
                command=(
                    f"cam mine {repo}"
                    f" --target {mine_target}"
                    f" --max-repos 1 --depth 5 --max-minutes 30"
                ),
                purpose="Study the target repo to extract patterns and identify gaps",
                verification="cam govern stats shows increased methodology count",
            ))

        # Step 3: KB inspection
        search_terms = profile.domain_keywords[:3]
        if search_terms:
            steps.append(CamifyStep(
                id="kb-inspect",
                phase="match",
                command=(
                    "cam kb insights && "
                    + " && ".join(f'cam kb search "{term}"' for term in search_terms)
                ),
                purpose="Inspect what CAM knows about the target domain",
                verification="Search returns relevant methodologies",
                required=False,
            ))

        # Step 4: Dry-run enhancement
        steps.append(CamifyStep(
            id="enhance-dryrun",
            phase="evaluate",
            command=f"cam enhance {repo} --battery --dry-run --verbose",
            purpose="Generate enhancement task plan without writing code",
            verification="Task list generated with relevant improvements",
        ))

        # Step 5: Execute enhancement (for enhance goals)
        enhance_goals = [g for g in goals if "enhance" in g.lower() or "improve" in g.lower() or not any(
            kw in g.lower() for kw in ["learn", "audit", "create"]
        )]
        if enhance_goals:
            steps.append(CamifyStep(
                id="enhance-execute",
                phase="enhance",
                command=f"cam enhance {repo} --mode attended --max-tasks 10 --verbose",
                purpose="Execute enhancement tasks with human approval per task",
                verification="Tasks complete with verification gate passing",
            ))

        # Step 6: Learn-back goal (mine enhanced repo back into CAM)
        learn_goals = [g for g in goals if "learn" in g.lower()]
        if learn_goals:
            steps.append(CamifyStep(
                id="learn-back",
                phase="post",
                command=f"cam mine {repo} --target . --max-repos 1 --depth 5",
                purpose="Assimilate enhanced patterns back into CAM KB",
                verification="cam govern stats shows new methodologies",
                required=False,
            ))

        # Step 7: Post-enhancement CAG rebuild
        steps.append(CamifyStep(
            id="cag-rebuild",
            phase="post",
            command="cam cag rebuild && cam cag status",
            purpose="Rebuild CAG cache with updated knowledge",
            verification="cam cag status shows current cache",
            required=False,
        ))

        guide_files_used = profile.guide_files
        created_at = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())

        return CamifyPlan(
            target_repo=repo,
            goals=goals,
            guide_files_used=guide_files_used,
            source_repos=source_repos,
            assimilation_targets=assimilation_targets,
            kb_matches_found=len(matches.matched_methodologies),
            kb_gaps=matches.gap_areas,
            steps=steps,
            created_at=created_at,
        )

    def render_markdown(self, plan: CamifyPlan) -> str:
        """Render a CamifyPlan as markdown with YAML frontmatter."""
        lines: list[str] = []

        # YAML frontmatter
        lines.append("---")
        lines.append(f"camify_version: {plan.version}")
        lines.append(f"target_repo: {plan.target_repo}")
        lines.append("goals:")
        for g in plan.goals:
            lines.append(f'  - "{g}"')
        if plan.guide_files_used:
            lines.append("guide_files:")
            for gf in plan.guide_files_used:
                lines.append(f"  - {gf}")
        if plan.source_repos:
            lines.append("source_repos:")
            for source in plan.source_repos:
                lines.append(f"  - {source}")
        if plan.assimilation_targets:
            lines.append("assimilation_targets:")
            for target in plan.assimilation_targets:
                lines.append(f"  - {target.get('id', '')}: {target.get('capability', '')}")
        lines.append(f"kb_matches_found: {plan.kb_matches_found}")
        if plan.kb_gaps:
            lines.append("kb_gaps:")
            for gap in plan.kb_gaps:
                lines.append(f"  - {gap}")
        lines.append(f'created_at: "{plan.created_at}"')
        lines.append(f"status: {plan.status}")
        lines.append("---")
        lines.append("")

        # Title
        repo_name = Path(plan.target_repo).name
        lines.append(f"# CAM-ify Plan: {repo_name}")
        lines.append("")

        # Goals
        lines.append("## Goals")
        for i, g in enumerate(plan.goals, 1):
            lines.append(f"{i}. {g}")
        lines.append("")

        # KB Summary
        lines.append("## KB Match Summary")
        lines.append(f"- {plan.kb_matches_found} relevant methodologies found")
        if plan.kb_gaps:
            lines.append(f"- Gaps: {', '.join(plan.kb_gaps)}")
        lines.append("")

        if plan.assimilation_targets:
            lines.append("## Assimilation Targets")
            lines.append("")
            lines.append("| ID | Capability | Source | Target | Acceptance |")
            lines.append("|---|---|---|---|---|")
            for target in plan.assimilation_targets:
                lines.append(
                    "| {id} | {capability} | {source} | {target_area} | {acceptance} |".format(
                        id=target.get("id", ""),
                        capability=target.get("capability", ""),
                        source=target.get("source", ""),
                        target_area=target.get("target", ""),
                        acceptance=target.get("acceptance", ""),
                    )
                )
            lines.append("")

        # Steps
        for i, step in enumerate(plan.steps, 1):
            opt = " (optional)" if not step.required else ""
            lines.append(f"## Step {i}: {step.phase.title()}{opt}")
            lines.append(f"**Command**: `{step.command}`")
            lines.append(f"**Purpose**: {step.purpose}")
            lines.append(f"**Verify**: {step.verification}")
            if step.fallback:
                lines.append(f"**Fallback**: {step.fallback}")
            lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Artifact writer
# ---------------------------------------------------------------------------

def write_camify_artifact(
    plan_md: str,
    plan: CamifyPlan,
    output_path: Path | None = None,
) -> Path:
    """Write plan markdown and JSON sidecar to disk.

    Args:
        plan_md: Rendered markdown string.
        plan: CamifyPlan model (saved as JSON sidecar).
        output_path: Explicit output path. If None, uses data/camify/.

    Returns:
        Path to the written markdown file.
    """
    if output_path:
        out_md = Path(output_path)
    else:
        camify_dir = Path(__file__).resolve().parents[2] / "data" / "camify"
        camify_dir.mkdir(parents=True, exist_ok=True)
        timestamp = _time.strftime("%Y%m%d-%H%M%S", _time.localtime())
        repo_slug = Path(plan.target_repo).name or "repo"
        out_md = camify_dir / f"{timestamp}-{repo_slug}-camify-plan.md"

    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(plan_md, encoding="utf-8")

    # JSON sidecar for machine consumption
    json_path = out_md.with_suffix(".json")
    json_path.write_text(
        json.dumps(plan.model_dump(), indent=2, default=str),
        encoding="utf-8",
    )

    logger.info("Camify plan written to: %s", out_md)
    return out_md
