"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import {
  getFederationTopology,
  analyzeFederation,
  getFederationPackets,
  requestSpecialistPacketExchange,
  getExternalSpecialistExchanges,
  exportExternalSpecialistExchange,
  importExternalSpecialistExchanges,
  type TopologyNode,
  type TopologyEdge,
  type CrossLanguageReport,
  type FederationPacketResponse,
  type SpecialistPacketExchangeResponse,
  type ExternalSpecialistExchange,
  type ExternalSpecialistExchangeImportResponse,
  type SpecialistAgent,
} from "@/lib/api";
import { Card, CardTitle } from "@/components/card";
import { GanglionBadge } from "@/components/badge";
import { Skeleton, SkeletonCard, SkeletonGrid } from "@/components/skeleton";
import { ErrorBanner } from "@/components/error-banner";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const NODE_COLORS: Record<string, string> = {
  primary: "#ff6b3d",
  online: "#58a6ff",
  offline: "#484f58",
};

const SVG_WIDTH = 600;
const SVG_HEIGHT = 400;
const CENTER_X = SVG_WIDTH / 2;
const CENTER_Y = SVG_HEIGHT / 2;
const ORBIT_RX = 200;
const ORBIT_RY = 140;
const MIN_RADIUS = 20;
const MAX_RADIUS = 48;

function formatExchangeTime(value?: string | null): string {
  if (!value) return "unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function exchangeStatusClass(status: string): string {
  const normalized = status.toLowerCase();
  if (normalized.includes("reject") || normalized.includes("fail")) {
    return "text-red-300 border-red-400/30 bg-red-400/10";
  }
  if (normalized.includes("import") || normalized.includes("complete") || normalized.includes("reconcile")) {
    return "text-cam-green border-cam-green/30 bg-cam-green/10";
  }
  if (normalized.includes("export") || normalized.includes("pending") || normalized.includes("awaiting")) {
    return "text-cam-blue border-cam-blue/30 bg-cam-blue/10";
  }
  return "text-muted border-card-border bg-card-border/30";
}

// ---------------------------------------------------------------------------
// Topology Visualization (SVG)
// ---------------------------------------------------------------------------

interface LayoutNode extends TopologyNode {
  x: number;
  y: number;
  r: number;
  color: string;
}

function computeLayout(
  nodes: TopologyNode[],
  edges: TopologyEdge[]
): { layoutNodes: LayoutNode[]; layoutEdges: Array<{ x1: number; y1: number; x2: number; y2: number }> } {
  const primary = nodes.find((n) => n.type === "primary");
  const siblings = nodes.filter((n) => n.type === "sibling");

  const maxCount = Math.max(...nodes.map((n) => n.methodology_count), 1);

  function radius(count: number): number {
    return MIN_RADIUS + ((count / maxCount) * (MAX_RADIUS - MIN_RADIUS));
  }

  function color(node: TopologyNode): string {
    if (node.type === "primary") return NODE_COLORS.primary;
    return node.db_exists ? NODE_COLORS.online : NODE_COLORS.offline;
  }

  const layoutNodes: LayoutNode[] = [];

  if (primary) {
    layoutNodes.push({
      ...primary,
      x: CENTER_X,
      y: CENTER_Y,
      r: Math.max(radius(primary.methodology_count), MAX_RADIUS),
      color: color(primary),
    });
  }

  siblings.forEach((sib, i) => {
    const angle = (2 * Math.PI * i) / Math.max(siblings.length, 1) - Math.PI / 2;
    layoutNodes.push({
      ...sib,
      x: CENTER_X + ORBIT_RX * Math.cos(angle),
      y: CENTER_Y + ORBIT_RY * Math.sin(angle),
      r: radius(sib.methodology_count),
      color: color(sib),
    });
  });

  // Build a quick lookup by id
  const nodeMap = new Map<string, LayoutNode>();
  for (const ln of layoutNodes) nodeMap.set(ln.id, ln);

  const layoutEdges = edges
    .map((e) => {
      const s = nodeMap.get(e.source);
      const t = nodeMap.get(e.target);
      if (!s || !t) return null;
      return { x1: s.x, y1: s.y, x2: t.x, y2: t.y };
    })
    .filter(Boolean) as Array<{ x1: number; y1: number; x2: number; y2: number }>;

  return { layoutNodes, layoutEdges };
}

function TopologyGraph({
  nodes,
  edges,
}: {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
}) {
  const { layoutNodes, layoutEdges } = useMemo(
    () => computeLayout(nodes, edges),
    [nodes, edges]
  );

  const [hovered, setHovered] = useState<string | null>(null);

  return (
    <svg
      viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
      className="w-full max-w-[700px] mx-auto"
      style={{ height: "auto" }}
    >
      {/* Orbit guide */}
      <ellipse
        cx={CENTER_X}
        cy={CENTER_Y}
        rx={ORBIT_RX}
        ry={ORBIT_RY}
        fill="none"
        stroke="#21262d"
        strokeDasharray="4 4"
        strokeWidth={1}
      />

      {/* Edges */}
      {layoutEdges.map((e, i) => (
        <line
          key={i}
          x1={e.x1}
          y1={e.y1}
          x2={e.x2}
          y2={e.y2}
          stroke="#30363d"
          strokeWidth={1.5}
        />
      ))}

      {/* Nodes */}
      {layoutNodes.map((node) => {
        const isHovered = hovered === node.id;
        return (
          <g
            key={node.id}
            onMouseEnter={() => setHovered(node.id)}
            onMouseLeave={() => setHovered(null)}
            style={{ cursor: "default" }}
          >
            {/* Glow */}
            <circle
              cx={node.x}
              cy={node.y}
              r={node.r + 4}
              fill="none"
              stroke={node.color}
              strokeWidth={isHovered ? 2 : 0}
              opacity={0.5}
            />
            {/* Circle */}
            <circle
              cx={node.x}
              cy={node.y}
              r={node.r}
              fill={`${node.color}22`}
              stroke={node.color}
              strokeWidth={2}
            />
            {/* Count */}
            <text
              x={node.x}
              y={node.y + 1}
              textAnchor="middle"
              dominantBaseline="middle"
              fill={node.color}
              fontSize={node.r > 30 ? 16 : 12}
              fontWeight="bold"
              fontFamily="var(--font-geist-mono), monospace"
            >
              {node.methodology_count}
            </text>
            {/* Label */}
            <text
              x={node.x}
              y={node.y + node.r + 14}
              textAnchor="middle"
              fill={isHovered ? "#c9d1d9" : "#8b949e"}
              fontSize={11}
              fontFamily="var(--font-geist-sans), sans-serif"
            >
              {node.id}
            </text>
            {/* Tooltip on hover */}
            {isHovered && node.description && (
              <text
                x={node.x}
                y={node.y + node.r + 28}
                textAnchor="middle"
                fill="#8b949e"
                fontSize={9}
              >
                {node.description.length > 50
                  ? node.description.slice(0, 50) + "..."
                  : node.description}
              </text>
            )}
          </g>
        );
      })}

      {/* Legend */}
      <g transform="translate(12, 12)">
        {[
          { label: "Primary", color: NODE_COLORS.primary },
          { label: "Sibling (online)", color: NODE_COLORS.online },
          { label: "Sibling (offline)", color: NODE_COLORS.offline },
        ].map((item, i) => (
          <g key={item.label} transform={`translate(0, ${i * 18})`}>
            <circle cx={6} cy={6} r={5} fill={`${item.color}22`} stroke={item.color} strokeWidth={1.5} />
            <text x={16} y={10} fill="#8b949e" fontSize={10}>
              {item.label}
            </text>
          </g>
        ))}
      </g>
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Cross-Brain Analysis Results
// ---------------------------------------------------------------------------

function UniversalPatternCard({
  pattern,
}: {
  pattern: CrossLanguageReport["universal_patterns"][0];
}) {
  return (
    <Card>
      <div className="flex items-start justify-between mb-2">
        <h4 className="text-sm font-semibold text-foreground">
          {pattern.pattern_name}
        </h4>
        <span className="text-xs font-mono text-cam-blue ml-2 shrink-0">
          overlap: {(pattern.domain_overlap * 100).toFixed(0)}%
        </span>
      </div>
      <div className="space-y-1.5">
        {Object.entries(pattern.implementations).map(([brain, impl]) => (
          <div key={brain} className="flex items-start gap-2">
            <GanglionBadge name={brain} />
            <span className="text-xs text-muted leading-relaxed">{impl}</span>
          </div>
        ))}
      </div>
      {pattern.evidence_ids.length > 0 && (
        <div className="mt-2 text-xs text-muted-dark font-mono">
          Evidence: {pattern.evidence_ids.slice(0, 3).join(", ")}
          {pattern.evidence_ids.length > 3 &&
            ` +${pattern.evidence_ids.length - 3} more`}
        </div>
      )}
    </Card>
  );
}

function UniqueInnovationCard({
  innovation,
}: {
  innovation: CrossLanguageReport["unique_innovations"][0];
}) {
  return (
    <Card>
      <div className="flex items-center gap-2 mb-2">
        <GanglionBadge name={innovation.brain} />
        <span className="text-xs text-muted-dark font-mono truncate">
          {innovation.methodology_id}
        </span>
      </div>
      <p className="text-sm text-foreground mb-1">
        {innovation.problem_summary}
      </p>
      <p className="text-xs text-muted">{innovation.why_unique}</p>
    </Card>
  );
}

function TransferableInsightCard({
  insight,
}: {
  insight: CrossLanguageReport["transferable_insights"][0];
}) {
  return (
    <Card>
      <div className="flex items-center gap-2 mb-2">
        <GanglionBadge name={insight.source_brain} />
        <span className="text-accent text-sm font-bold">-&gt;</span>
        <GanglionBadge name={insight.target_brain} />
      </div>
      <p className="text-xs text-muted leading-relaxed">
        {insight.rationale}
      </p>
    </Card>
  );
}

function AnalysisResults({ report }: { report: CrossLanguageReport }) {
  return (
    <div className="space-y-6">
      {/* Query echo */}
      <div className="text-sm text-muted">
        Analysis for: <span className="text-foreground font-medium">{report.query}</span>
      </div>

      {/* Metrics summary if present */}
      {Object.keys(report.metrics).length > 0 && (
        <div className="flex flex-wrap gap-3">
          {Object.entries(report.metrics).map(([k, v]) => (
            <div
              key={k}
              className="px-3 py-1.5 bg-card-border rounded-lg text-xs"
            >
              <span className="text-muted">{k.replace(/_/g, " ")}: </span>
              <span className="text-foreground font-mono">
                {typeof v === "number" ? v.toLocaleString() : String(v)}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Universal Patterns */}
      {report.universal_patterns.length > 0 && (
        <section>
          <h3 className="text-sm font-semibold text-foreground mb-3">
            Universal Patterns
            <span className="text-muted font-normal ml-2">
              ({report.universal_patterns.length})
            </span>
          </h3>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {report.universal_patterns.map((p, i) => (
              <UniversalPatternCard key={i} pattern={p} />
            ))}
          </div>
        </section>
      )}

      {/* Unique Innovations */}
      {report.unique_innovations.length > 0 && (
        <section>
          <h3 className="text-sm font-semibold text-foreground mb-3">
            Unique Innovations
            <span className="text-muted font-normal ml-2">
              ({report.unique_innovations.length})
            </span>
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {report.unique_innovations.map((inn, i) => (
              <UniqueInnovationCard key={i} innovation={inn} />
            ))}
          </div>
        </section>
      )}

      {/* Transferable Insights */}
      {report.transferable_insights.length > 0 && (
        <section>
          <h3 className="text-sm font-semibold text-foreground mb-3">
            Transferable Insights
            <span className="text-muted font-normal ml-2">
              ({report.transferable_insights.length})
            </span>
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {report.transferable_insights.map((ins, i) => (
              <TransferableInsightCard key={i} insight={ins} />
            ))}
          </div>
        </section>
      )}

      {/* Empty state */}
      {report.universal_patterns.length === 0 &&
        report.unique_innovations.length === 0 &&
        report.transferable_insights.length === 0 && (
          <Card>
            <p className="text-muted text-sm">
              No patterns, innovations, or transferable insights found for this
              query. Try a broader topic like &quot;error handling&quot; or &quot;testing
              patterns&quot;.
            </p>
          </Card>
        )}
    </div>
  );
}

function FederationPacketCard({
  result,
}: {
  result: FederationPacketResponse["results"][0];
}) {
  const matchClass =
    result.match_type === "direct_fit"
      ? "text-cam-green border-cam-green/30 bg-cam-green/10"
      : "text-cam-blue border-cam-blue/30 bg-cam-blue/10";

  return (
    <Card>
      <div className="flex items-start justify-between gap-3 mb-2">
        <div>
          <h4 className="text-sm font-semibold text-foreground">{result.title}</h4>
          <div className="text-xs text-muted-dark font-mono">
            {result.source_instance} · {result.component_type}
          </div>
        </div>
        <div className={`px-2 py-1 rounded-md border text-xs font-medium ${matchClass}`}>
          {result.match_type === "direct_fit" ? "Direct Fit" : "Pattern Transfer"}
        </div>
      </div>
      <div className="space-y-1 text-xs text-muted">
        <div>
          <span className="text-muted-dark">Repo:</span> {result.repo}
        </div>
        <div>
          <span className="text-muted-dark">Path:</span> {result.file_path}
        </div>
        {result.symbol && (
          <div>
            <span className="text-muted-dark">Symbol:</span> {result.symbol}
          </div>
        )}
        <div className="flex flex-wrap gap-2 pt-1">
          {result.abstract_jobs.slice(0, 3).map((job) => (
            <span
              key={job}
              className="px-2 py-0.5 rounded-md bg-card-border/60 text-[11px] text-foreground"
            >
              {job}
            </span>
          ))}
        </div>
      </div>
      <div className="mt-3 flex items-center justify-between text-xs font-mono">
        <span className="text-muted-dark">{result.family_barcode}</span>
        <span className="text-foreground">
          score {Math.round(result.match_score * 100)} / rel {Math.round(result.relevance_score * 100)}
        </span>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function FederationPage() {
  const [topology, setTopology] = useState<{
    nodes: TopologyNode[];
    edges: TopologyEdge[];
    total_methodologies: number;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Analysis state
  const [query, setQuery] = useState("");
  const [analyzing, setAnalyzing] = useState(false);
  const [report, setReport] = useState<CrossLanguageReport | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [packetQuery, setPacketQuery] = useState("");
  const [packetLanguage, setPacketLanguage] = useState("");
  const [packetResults, setPacketResults] = useState<FederationPacketResponse | null>(null);
  const [packetLoading, setPacketLoading] = useState(false);
  const [packetError, setPacketError] = useState<string | null>(null);
  const [specialistQuery, setSpecialistQuery] = useState("");
  const [specialistAgent, setSpecialistAgent] = useState<SpecialistAgent | "">("");
  const [specialistExchange, setSpecialistExchange] = useState<SpecialistPacketExchangeResponse | null>(null);
  const [specialistLoading, setSpecialistLoading] = useState(false);
  const [specialistError, setSpecialistError] = useState<string | null>(null);
  const [externalExchanges, setExternalExchanges] = useState<ExternalSpecialistExchange[]>([]);
  const [externalExchangeLoading, setExternalExchangeLoading] = useState(false);
  const [externalExchangeError, setExternalExchangeError] = useState<string | null>(null);
  const [externalExportPath, setExternalExportPath] = useState<string | null>(null);
  const [externalImportResult, setExternalImportResult] = useState<ExternalSpecialistExchangeImportResponse | null>(null);

  const loadTopology = useCallback(() => {
    getFederationTopology()
      .then(setTopology)
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    loadTopology();
  }, [loadTopology]);

  const loadExternalExchanges = useCallback(async () => {
    setExternalExchangeLoading(true);
    setExternalExchangeError(null);

    try {
      const result = await getExternalSpecialistExchanges();
      setExternalExchanges(result.exchanges);
    } catch (e) {
      setExternalExchangeError(e instanceof Error ? e.message : String(e));
    } finally {
      setExternalExchangeLoading(false);
    }
  }, []);

  useEffect(() => {
    loadExternalExchanges();
  }, [loadExternalExchanges]);

  const handleAnalyze = useCallback(async () => {
    const trimmed = query.trim();
    if (!trimmed) return;

    setAnalyzing(true);
    setAnalysisError(null);
    setReport(null);

    try {
      const result = await analyzeFederation(trimmed);
      setReport(result);
    } catch (e) {
      setAnalysisError(e instanceof Error ? e.message : String(e));
    } finally {
      setAnalyzing(false);
    }
  }, [query]);

  const handlePacketSearch = useCallback(async () => {
    const trimmed = packetQuery.trim();
    if (!trimmed) return;

    setPacketLoading(true);
    setPacketError(null);
    setPacketResults(null);

    try {
      const result = await getFederationPackets(trimmed, {
        language: packetLanguage.trim() || undefined,
        limit: 8,
      });
      setPacketResults(result);
    } catch (e) {
      setPacketError(e instanceof Error ? e.message : String(e));
    } finally {
      setPacketLoading(false);
    }
  }, [packetLanguage, packetQuery]);

  const handleSpecialistExchange = useCallback(async () => {
    const trimmed = specialistQuery.trim();
    if (!trimmed) return;

    setSpecialistLoading(true);
    setSpecialistError(null);
    setSpecialistExchange(null);

    try {
      const result = await requestSpecialistPacketExchange({
        taskText: trimmed,
        preferredAgent: specialistAgent || undefined,
        limit: 6,
      });
      setSpecialistExchange(result);
    } catch (e) {
      setSpecialistError(e instanceof Error ? e.message : String(e));
    } finally {
      setSpecialistLoading(false);
    }
  }, [specialistAgent, specialistQuery]);

  const handleExternalExport = useCallback(async () => {
    const trimmed = specialistQuery.trim();
    if (!trimmed) return;

    setExternalExchangeLoading(true);
    setExternalExchangeError(null);
    setExternalExportPath(null);

    try {
      const result = await exportExternalSpecialistExchange({
        taskText: trimmed,
        preferredAgent: specialistAgent || undefined,
      });
      setExternalExportPath(result.request_path);
      setExternalExchanges((current) => [
        result.exchange,
        ...current.filter((exchange) => exchange.exchange_id !== result.exchange.exchange_id),
      ]);
    } catch (e) {
      setExternalExchangeError(e instanceof Error ? e.message : String(e));
    } finally {
      setExternalExchangeLoading(false);
    }
  }, [specialistAgent, specialistQuery]);

  const handleExternalImport = useCallback(async () => {
    setExternalExchangeLoading(true);
    setExternalExchangeError(null);
    setExternalImportResult(null);

    try {
      const result = await importExternalSpecialistExchanges();
      setExternalImportResult(result);
      await loadExternalExchanges();
    } catch (e) {
      setExternalExchangeError(e instanceof Error ? e.message : String(e));
    } finally {
      setExternalExchangeLoading(false);
    }
  }, [loadExternalExchanges]);

  if (error) {
    return (
      <ErrorBanner
        message="Failed to load federation topology"
        detail={error}
        onRetry={() => { setError(null); loadTopology(); }}
      />
    );
  }

  if (!topology) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-4 w-80" />
        <SkeletonCard />
        <SkeletonGrid count={3} />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-foreground">Federation Hub</h1>
        <p className="text-muted mt-1">
          Brain topology, cross-language patterns, and knowledge transfer
        </p>
      </div>

      {/* Total methodology count */}
      <div className="flex items-baseline gap-3">
        <span className="text-5xl font-bold text-accent font-mono">
          {topology.total_methodologies.toLocaleString()}
        </span>
        <span className="text-muted">
          total methodologies across all ganglia
        </span>
      </div>

      {/* Topology graph */}
      <Card>
        <CardTitle>Brain Topology</CardTitle>
        <TopologyGraph nodes={topology.nodes} edges={topology.edges} />
        {/* Node summary */}
        <div className="flex flex-wrap gap-3 mt-4 pt-4 border-t border-card-border">
          {topology.nodes.map((node) => (
            <div
              key={node.id}
              className="flex items-center gap-2 px-3 py-1.5 bg-card-border/50 rounded-lg"
            >
              <GanglionBadge name={node.id} />
              <span className="text-xs text-foreground font-mono">
                {node.methodology_count}
              </span>
              <span
                className={`text-xs ${
                  node.db_exists ? "text-cam-green" : "text-red-400"
                }`}
              >
                {node.db_exists ? "online" : "offline"}
              </span>
            </div>
          ))}
        </div>
      </Card>

      {/* Cross-brain analysis */}
      <Card>
        <CardTitle>Cross-Brain Analysis</CardTitle>
        <p className="text-xs text-muted mb-3">
          Query across all brains to discover universal patterns, unique
          innovations, and transferable insights.
        </p>
        <div className="flex gap-3">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !analyzing) handleAnalyze();
            }}
            placeholder="e.g. error handling, testing patterns, CLI design..."
            className="flex-1 bg-background border border-card-border rounded-lg px-4 py-2.5 text-sm text-foreground placeholder:text-muted-dark focus:outline-none focus:border-accent transition-colors"
          />
          <button
            onClick={handleAnalyze}
            disabled={analyzing || !query.trim()}
            className="px-5 py-2.5 bg-accent hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors shrink-0"
          >
            {analyzing ? "Analyzing..." : "Analyze"}
          </button>
        </div>
      </Card>

      <Card>
        <CardTitle>Component Packet Search</CardTitle>
        <p className="text-xs text-muted mb-3">
          Query cross-brain component packets with direct-fit versus pattern-transfer labeling.
        </p>
        <div className="flex flex-col lg:flex-row gap-3">
          <input
            type="text"
            value={packetQuery}
            onChange={(e) => setPacketQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !packetLoading) handlePacketSearch();
            }}
            placeholder="e.g. Add OAuth session handling with token refresh"
            className="flex-1 bg-background border border-card-border rounded-lg px-4 py-2.5 text-sm text-foreground placeholder:text-muted-dark focus:outline-none focus:border-accent transition-colors"
          />
          <input
            type="text"
            value={packetLanguage}
            onChange={(e) => setPacketLanguage(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !packetLoading) handlePacketSearch();
            }}
            placeholder="language (optional)"
            className="w-full lg:w-44 bg-background border border-card-border rounded-lg px-4 py-2.5 text-sm text-foreground placeholder:text-muted-dark focus:outline-none focus:border-accent transition-colors"
          />
          <button
            onClick={handlePacketSearch}
            disabled={packetLoading || !packetQuery.trim()}
            className="px-5 py-2.5 bg-accent hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors shrink-0"
          >
            {packetLoading ? "Searching..." : "Search Packets"}
          </button>
        </div>
        {packetResults && (
          <div className="mt-4 text-sm text-muted">
            <span className="text-foreground font-medium">{packetResults.task_archetype}</span>
            <span className="mx-2">·</span>
            confidence {(packetResults.archetype_confidence * 100).toFixed(0)}%
            {packetResults.slot && (
              <>
                <span className="mx-2">·</span>
                slot <span className="text-foreground font-medium">{packetResults.slot.name}</span>
              </>
            )}
          </div>
        )}
      </Card>

      <Card>
        <CardTitle>Specialist Packet Exchange</CardTitle>
        <p className="text-xs text-muted mb-3">
          Request a structured packet handoff for a specialist ganglion or agent using the same packet-ready federation surface.
        </p>
        <div className="flex flex-col lg:flex-row gap-3">
          <input
            type="text"
            value={specialistQuery}
            onChange={(e) => setSpecialistQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !specialistLoading) handleSpecialistExchange();
            }}
            placeholder="e.g. Fix token refresh races in the OAuth client"
            className="flex-1 bg-background border border-card-border rounded-lg px-4 py-2.5 text-sm text-foreground placeholder:text-muted-dark focus:outline-none focus:border-accent transition-colors"
          />
          <select
            value={specialistAgent}
            onChange={(e) => setSpecialistAgent(e.target.value as typeof specialistAgent)}
            className="w-full lg:w-44 bg-background border border-card-border rounded-lg px-4 py-2.5 text-sm text-foreground focus:outline-none focus:border-accent transition-colors"
          >
            <option value="">auto route</option>
            <option value="claude">claude</option>
            <option value="codex">codex</option>
            <option value="gemini">gemini</option>
            <option value="grok">grok</option>
          </select>
          <button
            onClick={handleSpecialistExchange}
            disabled={specialistLoading || !specialistQuery.trim()}
            className="px-5 py-2.5 bg-accent hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors shrink-0"
          >
            {specialistLoading ? "Requesting..." : "Request Specialist"}
          </button>
        </div>
        {specialistExchange && (
          <div className="mt-4 grid grid-cols-1 lg:grid-cols-3 gap-3 text-sm">
            <div className="rounded-lg bg-card-border/40 px-3 py-2">
              <div className="text-xs text-muted-dark mb-1">Selected Agent</div>
              <div className="text-foreground font-medium">{specialistExchange.selected_agent}</div>
            </div>
            <div className="rounded-lg bg-card-border/40 px-3 py-2">
              <div className="text-xs text-muted-dark mb-1">Archetype</div>
              <div className="text-foreground font-medium">{specialistExchange.task_archetype}</div>
            </div>
            <div className="rounded-lg bg-card-border/40 px-3 py-2">
              <div className="text-xs text-muted-dark mb-1">Review Required</div>
              <div className="text-foreground font-medium">{specialistExchange.review_required ? "yes" : "no"}</div>
            </div>
          </div>
        )}
        <div className="mt-4 pt-4 border-t border-card-border">
          <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3 mb-3">
            <div>
              <h3 className="text-sm font-semibold text-foreground">
                External Specialist Exchanges
                <span className="text-muted font-normal ml-2">
                  ({externalExchanges.length})
                </span>
              </h3>
              <p className="text-xs text-muted">
                Export handoffs and import replies for offline specialist review.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={handleExternalExport}
                disabled={externalExchangeLoading || !specialistQuery.trim()}
                className="px-3 py-2 bg-card-border/70 hover:bg-card-border disabled:opacity-40 disabled:cursor-not-allowed text-foreground text-xs font-medium rounded-lg transition-colors"
              >
                Export Handoff
              </button>
              <button
                onClick={handleExternalImport}
                disabled={externalExchangeLoading}
                className="px-3 py-2 bg-card-border/70 hover:bg-card-border disabled:opacity-40 disabled:cursor-not-allowed text-foreground text-xs font-medium rounded-lg transition-colors"
              >
                Import Replies
              </button>
              <button
                onClick={loadExternalExchanges}
                disabled={externalExchangeLoading}
                className="px-3 py-2 bg-card-border/40 hover:bg-card-border disabled:opacity-40 disabled:cursor-not-allowed text-muted text-xs font-medium rounded-lg transition-colors"
              >
                {externalExchangeLoading ? "Loading..." : "Refresh"}
              </button>
            </div>
          </div>
          {externalExportPath && (
            <div className="mb-3 rounded-lg bg-cam-blue/10 border border-cam-blue/20 px-3 py-2 text-xs text-cam-blue font-mono break-all">
              request {externalExportPath}
            </div>
          )}
          {externalImportResult && (
            <div className="mb-3 rounded-lg bg-card-border/40 px-3 py-2 text-xs text-muted">
              imported <span className="text-foreground font-mono">{externalImportResult.imported.length}</span>
              <span className="mx-2">·</span>
              rejected <span className="text-foreground font-mono">{externalImportResult.rejected.length}</span>
            </div>
          )}
          {externalExchangeError && (
            <div className="mb-3 rounded-lg border border-red-400/30 bg-red-400/10 px-3 py-2 text-xs text-red-300">
              {externalExchangeError}
            </div>
          )}
          {externalExchanges.length > 0 ? (
            <div className="divide-y divide-card-border rounded-lg border border-card-border overflow-hidden">
              {externalExchanges.slice(0, 5).map((exchange) => (
                <div
                  key={exchange.exchange_id}
                  className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_9rem_11rem] gap-2 px-3 py-2 text-xs bg-background/30"
                >
                  <div className="min-w-0">
                    <div className="text-foreground truncate">{exchange.task_text}</div>
                    <div className="text-muted-dark font-mono truncate">
                      {exchange.request_path || exchange.reply_path || exchange.exchange_id}
                    </div>
                  </div>
                  <div className="flex lg:block items-center gap-2">
                    <span className={`inline-flex px-2 py-0.5 rounded-md border font-medium ${exchangeStatusClass(exchange.status)}`}>
                      {exchange.status}
                    </span>
                  </div>
                  <div className="text-muted lg:text-right">
                    <div>{exchange.selected_agent || exchange.preferred_agent || "auto route"}</div>
                    <div className="text-muted-dark">
                      {formatExchangeTime(exchange.updated_at || exchange.imported_at || exchange.exported_at || exchange.created_at)}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-lg border border-card-border px-3 py-2 text-xs text-muted">
              No external specialist exchanges yet.
            </div>
          )}
        </div>
      </Card>

      {/* Analysis error */}
      {analysisError && (
        <ErrorBanner
          message="Analysis failed"
          detail={analysisError}
          onRetry={() => { setAnalysisError(null); handleAnalyze(); }}
        />
      )}

      {/* Analysis results */}
      {report && <AnalysisResults report={report} />}

      {packetError && (
        <ErrorBanner
          message="Federation packet search failed"
          detail={packetError}
          onRetry={() => {
            setPacketError(null);
            handlePacketSearch();
          }}
        />
      )}

      {packetResults && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-foreground">
              Packet Results
              <span className="text-muted font-normal ml-2">
                ({packetResults.results.length})
              </span>
            </h3>
          </div>
          {packetResults.results.length > 0 ? (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {packetResults.results.map((result) => (
                <FederationPacketCard
                  key={`${result.source_instance}:${result.component_id}`}
                  result={result}
                />
              ))}
            </div>
          ) : (
            <Card>
              <p className="text-sm text-muted">
                No component packets matched this query.
              </p>
            </Card>
          )}
        </div>
      )}

      {specialistError && (
        <ErrorBanner
          message="Specialist packet exchange failed"
          detail={specialistError}
          onRetry={() => {
            setSpecialistError(null);
            handleSpecialistExchange();
          }}
        />
      )}

      {specialistExchange && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-foreground">
              Specialist Packet Candidates
              <span className="text-muted font-normal ml-2">
                ({specialistExchange.results.length})
              </span>
            </h3>
            <div className="text-xs text-muted">
              route {specialistExchange.routing_method} · task type {specialistExchange.inferred_task_type}
            </div>
          </div>
          {specialistExchange.results.length > 0 ? (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {specialistExchange.results.map((result) => (
                <FederationPacketCard
                  key={`specialist:${result.source_instance}:${result.component_id}`}
                  result={result}
                />
              ))}
            </div>
          ) : (
            <Card>
              <p className="text-sm text-muted">
                No specialist packet candidates were available for this request.
              </p>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
