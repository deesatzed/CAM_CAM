"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import {
  getABTests,
  getRouting,
  getBanditArms,
  getGovernanceConflicts,
  getEvolutionFitness,
  getGovernancePolicies,
  getGovernanceTrends,
  getSecurityLaneStatus,
  getFederationPolicyRecommendations,
  getFederationTrends,
  promoteFederationPolicy,
  searchKnowledge,
  type FederationPolicyRecommendationsResponse,
  type FederationTrendsResponse,
  type GovernancePolicy,
  type GovernanceTrendsResponse,
  type RoutingEntry,
  type SecurityLaneStatus,
  type BanditArm,
  type FitnessTrajectoryEntry,
  updateGovernancePolicyStatus,
} from "@/lib/api";
import { Card, CardTitle } from "@/components/card";
import { Skeleton, SkeletonGrid } from "@/components/skeleton";
import { ErrorBanner } from "@/components/error-banner";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import type { Formatter } from "recharts/types/component/DefaultTooltipContent";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Tab = "ab-tests" | "routing" | "bandit" | "fitness";

// ---------------------------------------------------------------------------
// Color helpers
// ---------------------------------------------------------------------------

/** Interpolate from red (#f85149) at 0% through yellow at 50% to green (#3fb950) at 100%. */
function winRateColor(rate: number): string {
  const clamped = Math.max(0, Math.min(1, rate));
  if (clamped < 0.5) {
    // red -> yellow
    const t = clamped / 0.5;
    const r = Math.round(248 + (234 - 248) * t);
    const g = Math.round(81 + (179 - 81) * t);
    const b = Math.round(73 + (8 - 73) * t);
    return `rgb(${r},${g},${b})`;
  }
  // yellow -> green
  const t = (clamped - 0.5) / 0.5;
  const r = Math.round(234 + (63 - 234) * t);
  const g = Math.round(179 + (185 - 179) * t);
  const b = Math.round(8 + (80 - 8) * t);
  return `rgb(${r},${g},${b})`;
}

function winRateBg(rate: number, opacity = 0.15): string {
  const clamped = Math.max(0, Math.min(1, rate));
  if (clamped < 0.5) {
    const t = clamped / 0.5;
    const r = Math.round(248 + (234 - 248) * t);
    const g = Math.round(81 + (179 - 81) * t);
    const b = Math.round(73 + (8 - 73) * t);
    return `rgba(${r},${g},${b},${opacity})`;
  }
  const t = (clamped - 0.5) / 0.5;
  const r = Math.round(234 + (63 - 234) * t);
  const g = Math.round(179 + (185 - 179) * t);
  const b = Math.round(8 + (80 - 8) * t);
  return `rgba(${r},${g},${b},${opacity})`;
}

function governanceSeverityTone(severity: "low" | "medium" | "high" | string): string {
  if (severity === "high") return "border-red-400/30 bg-red-400/10 text-red-300";
  if (severity === "medium") return "border-amber-400/30 bg-amber-400/10 text-amber-200";
  return "border-cam-green/30 bg-cam-green/10 text-cam-green";
}

function laneStatusTone(status?: string): string {
  if (status === "ready") return "border-cam-green/30 bg-cam-green/10 text-cam-green";
  if (status === "blocking_unavailable") return "border-red-400/30 bg-red-400/10 text-red-300";
  if (status === "deferred") return "border-amber-400/30 bg-amber-400/10 text-amber-200";
  return "border-card-border bg-background text-muted";
}

// ---------------------------------------------------------------------------
// Tooltip formatter — typed to satisfy recharts v3 Formatter<ValueType, NameType>
// ---------------------------------------------------------------------------

const winRateTooltipFormatter: Formatter = (value, name) => {
  const label = name === "win_rate" ? "Win Rate" : String(name ?? "");
  return [`${value ?? 0}%`, label];
};

// ---------------------------------------------------------------------------
// Tab Button
// ---------------------------------------------------------------------------

function TabButton({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
        active
          ? "bg-accent text-white"
          : "bg-card-border text-muted hover:text-foreground hover:bg-card-hover"
      }`}
    >
      {label}
    </button>
  );
}

// ---------------------------------------------------------------------------
// A/B Tests Tab
// ---------------------------------------------------------------------------

function ABTestsPanel({ tests }: { tests: Record<string, unknown>[] }) {
  const columns = useMemo(() => {
    const keySet = new Set<string>();
    for (const t of tests) {
      for (const k of Object.keys(t)) keySet.add(k);
    }
    return Array.from(keySet);
  }, [tests]);

  if (tests.length === 0) {
    return (
      <Card>
        <p className="text-muted text-sm">No A/B tests found.</p>
      </Card>
    );
  }

  return (
    <Card>
      <CardTitle>A/B Test Results</CardTitle>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-card-border">
              {columns.map((col) => (
                <th
                  key={col}
                  className="text-left text-xs text-muted uppercase tracking-wider py-2 px-3 whitespace-nowrap"
                >
                  {col.replace(/_/g, " ")}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tests.map((test, idx) => (
              <tr
                key={idx}
                className="border-b border-card-border/50 hover:bg-card-hover/30 transition-colors"
              >
                {columns.map((col) => {
                  const val = test[col];
                  const display =
                    val === null || val === undefined
                      ? "-"
                      : typeof val === "object"
                        ? JSON.stringify(val)
                        : String(val);
                  return (
                    <td
                      key={col}
                      className="py-2 px-3 text-foreground whitespace-nowrap max-w-[300px] truncate"
                      title={display}
                    >
                      {display}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Routing Heatmap Tab
// ---------------------------------------------------------------------------

function RoutingHeatmap({ routing }: { routing: RoutingEntry[] }) {
  const { agents, taskTypes, lookup } = useMemo(() => {
    const agentTotals: Record<string, number> = {};
    const taskTypeSet = new Set<string>();
    const lk: Record<string, Record<string, RoutingEntry>> = {};

    for (const r of routing) {
      agentTotals[r.agent_id] = (agentTotals[r.agent_id] || 0) + r.total;
      taskTypeSet.add(r.task_type);
      if (!lk[r.agent_id]) lk[r.agent_id] = {};
      lk[r.agent_id][r.task_type] = r;
    }

    const sortedAgents = Object.entries(agentTotals)
      .sort(([, a], [, b]) => b - a)
      .map(([id]) => id);

    return {
      agents: sortedAgents,
      taskTypes: Array.from(taskTypeSet).sort(),
      lookup: lk,
    };
  }, [routing]);

  if (routing.length === 0) {
    return (
      <Card>
        <p className="text-muted text-sm">No routing data available.</p>
      </Card>
    );
  }

  return (
    <Card>
      <CardTitle>Agent Routing Heatmap</CardTitle>
      <p className="text-xs text-muted mb-4">
        Cell color = win rate (red 0% to green 100%). Number = total tasks routed.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr>
              <th className="text-left text-xs text-muted uppercase tracking-wider py-2 px-3 sticky left-0 bg-card z-10">
                Agent
              </th>
              {taskTypes.map((tt) => (
                <th
                  key={tt}
                  className="text-center text-xs text-muted uppercase tracking-wider py-2 px-3 whitespace-nowrap"
                >
                  {tt.replace(/_/g, " ")}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {agents.map((agentId) => (
              <tr key={agentId} className="border-t border-card-border/40">
                <td className="py-2 px-3 text-foreground font-mono text-xs whitespace-nowrap sticky left-0 bg-card z-10">
                  {agentId}
                </td>
                {taskTypes.map((tt) => {
                  const entry = lookup[agentId]?.[tt];
                  if (!entry) {
                    return (
                      <td
                        key={tt}
                        className="py-2 px-3 text-center text-muted-dark text-xs"
                      >
                        --
                      </td>
                    );
                  }
                  const winRate =
                    entry.total > 0 ? entry.wins / entry.total : 0;
                  return (
                    <td
                      key={tt}
                      className="py-2 px-3 text-center"
                      style={{ backgroundColor: winRateBg(winRate, 0.2) }}
                    >
                      <div
                        className="text-xs font-bold"
                        style={{ color: winRateColor(winRate) }}
                      >
                        {(winRate * 100).toFixed(0)}%
                      </div>
                      <div className="text-[10px] text-muted">
                        {entry.total} tasks
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Bandit Arms Tab
// ---------------------------------------------------------------------------

function BanditArmsPanel({
  arms,
  taskTypes,
}: {
  arms: BanditArm[];
  taskTypes: string[];
}) {
  const [selectedType, setSelectedType] = useState<string>("");

  const filtered = useMemo(() => {
    const list = selectedType
      ? arms.filter((a) => a.task_type === selectedType)
      : arms;
    return [...list].sort((a, b) => b.total - a.total);
  }, [arms, selectedType]);

  // Prepare chart data: top 15 arms by total
  const chartData = useMemo(() => {
    return filtered.slice(0, 15).map((a) => ({
      name: a.methodology_id.slice(0, 8),
      win_rate: Math.round(a.win_rate * 100),
      total: a.total,
    }));
  }, [filtered]);

  if (arms.length === 0) {
    return (
      <Card>
        <p className="text-muted text-sm">No bandit arm data available.</p>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {/* Filter */}
      <Card>
        <div className="flex items-center gap-3 flex-wrap">
          <label className="text-xs text-muted uppercase tracking-wider">
            Filter by task type
          </label>
          <select
            value={selectedType}
            onChange={(e) => setSelectedType(e.target.value)}
            className="bg-card-border border border-card-hover text-foreground text-sm rounded-lg px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-accent"
          >
            <option value="">All task types</option>
            {taskTypes.map((tt) => (
              <option key={tt} value={tt}>
                {tt}
              </option>
            ))}
          </select>
          <span className="text-xs text-muted">
            {filtered.length} arm{filtered.length !== 1 ? "s" : ""}
          </span>
        </div>
      </Card>

      {/* Chart */}
      {chartData.length > 0 && (
        <Card>
          <CardTitle>Win Rate by Methodology (top 15)</CardTitle>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={chartData}
                margin={{ top: 4, right: 16, bottom: 4, left: 0 }}
              >
                <XAxis
                  dataKey="name"
                  tick={{ fill: "#8b949e", fontSize: 11 }}
                  axisLine={{ stroke: "#21262d" }}
                  tickLine={false}
                />
                <YAxis
                  domain={[0, 100]}
                  tick={{ fill: "#8b949e", fontSize: 11 }}
                  axisLine={{ stroke: "#21262d" }}
                  tickLine={false}
                  tickFormatter={(v: number) => `${v}%`}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#161b22",
                    border: "1px solid #21262d",
                    borderRadius: "8px",
                    color: "#c9d1d9",
                    fontSize: "12px",
                  }}
                  formatter={winRateTooltipFormatter}
                />
                <Bar dataKey="win_rate" radius={[4, 4, 0, 0]}>
                  {chartData.map((entry, index) => (
                    <Cell
                      key={`cell-${index}`}
                      fill={winRateColor(entry.win_rate / 100)}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}

      {/* Table */}
      <Card>
        <CardTitle>Bandit Arms Detail</CardTitle>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-card-border">
                {[
                  "Methodology",
                  "Task Type",
                  "Successes",
                  "Failures",
                  "Total",
                  "Win Rate",
                  "Last Updated",
                ].map((h) => (
                  <th
                    key={h}
                    className="text-left text-xs text-muted uppercase tracking-wider py-2 px-3 whitespace-nowrap"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((arm) => {
                const pct = Math.round(arm.win_rate * 100);
                return (
                  <tr
                    key={`${arm.methodology_id}-${arm.task_type}`}
                    className="border-b border-card-border/50 hover:bg-card-hover/30 transition-colors"
                  >
                    <td className="py-2 px-3 font-mono text-foreground">
                      <span title={arm.methodology_id}>
                        {arm.methodology_id.slice(0, 8)}
                      </span>
                    </td>
                    <td className="py-2 px-3 text-muted whitespace-nowrap">
                      {arm.task_type}
                    </td>
                    <td className="py-2 px-3 text-cam-green">
                      {arm.successes}
                    </td>
                    <td className="py-2 px-3 text-red-400">{arm.failures}</td>
                    <td className="py-2 px-3 text-foreground font-medium">
                      {arm.total}
                    </td>
                    <td className="py-2 px-3">
                      <div className="flex items-center gap-2">
                        <div className="w-20 h-2 bg-card-border rounded-full overflow-hidden">
                          <div
                            className="h-full rounded-full transition-all"
                            style={{
                              width: `${pct}%`,
                              backgroundColor: winRateColor(arm.win_rate),
                            }}
                          />
                        </div>
                        <span
                          className="text-xs font-bold min-w-[36px]"
                          style={{ color: winRateColor(arm.win_rate) }}
                        >
                          {pct}%
                        </span>
                      </div>
                    </td>
                    <td className="py-2 px-3 text-muted text-xs whitespace-nowrap">
                      {arm.last_updated
                        ? new Date(arm.last_updated).toLocaleDateString()
                        : "-"}
                    </td>
                  </tr>
                );
              })}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={7} className="py-4 px-3 text-center text-muted">
                    No arms for the selected task type.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Fitness Trajectories Tab
// ---------------------------------------------------------------------------

function FitnessPanel() {
  const [query, setQuery] = useState("");
  const [methodologyIds, setMethodologyIds] = useState<
    Array<{ id: string; label: string }>
  >([]);
  const [searching, setSearching] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [trajectory, setTrajectory] = useState<FitnessTrajectoryEntry[] | null>(
    null,
  );
  const [loadingTrajectory, setLoadingTrajectory] = useState(false);
  const [fitnessError, setFitnessError] = useState<string | null>(null);

  // Search for methodologies to pick from
  const handleSearch = useCallback(async () => {
    if (!query.trim()) return;
    setSearching(true);
    setFitnessError(null);
    try {
      const data = await searchKnowledge(query, 10);
      setMethodologyIds(
        data.results.map((r) => ({
          id: r.id,
          label: r.problem.slice(0, 80) || r.id.slice(0, 8),
        })),
      );
    } catch (e) {
      setFitnessError(e instanceof Error ? e.message : String(e));
    } finally {
      setSearching(false);
    }
  }, [query]);

  // Load fitness trajectory for selected methodology
  const handleSelect = useCallback(async (id: string) => {
    setSelectedId(id);
    setLoadingTrajectory(true);
    setFitnessError(null);
    setTrajectory(null);
    try {
      const data = await getEvolutionFitness(id);
      setTrajectory(data.trajectory);
    } catch (e) {
      setFitnessError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoadingTrajectory(false);
    }
  }, []);

  // Chart data from trajectory
  const chartData = useMemo(() => {
    if (!trajectory) return [];
    return trajectory.map((entry, i) => ({
      index: i + 1,
      fitness: entry.fitness,
      event: entry.event,
      timestamp: new Date(entry.timestamp).toLocaleDateString(),
    }));
  }, [trajectory]);

  // Vector dimension breakdown for the latest entry
  const latestVector = useMemo(() => {
    if (!trajectory || trajectory.length === 0) return null;
    return trajectory[trajectory.length - 1].vector;
  }, [trajectory]);

  return (
    <div className="space-y-4">
      {/* Search for a methodology */}
      <Card>
        <CardTitle>Methodology Fitness Trajectory</CardTitle>
        <p className="text-xs text-muted mb-3">
          Search for a methodology and view its fitness score over time.
        </p>
        <div className="flex gap-2">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            placeholder="Search methodologies (e.g. retry, cache, error handling)"
            className="flex-1 px-3 py-2 bg-card-border border border-card-hover rounded-lg text-sm text-foreground placeholder:text-muted-dark focus:outline-none focus:ring-1 focus:ring-accent"
          />
          <button
            onClick={handleSearch}
            disabled={searching || !query.trim()}
            className="px-4 py-2 bg-accent hover:bg-accent-hover disabled:opacity-40 text-white text-sm font-medium rounded-lg transition-colors"
          >
            {searching ? "..." : "Search"}
          </button>
        </div>
      </Card>

      {fitnessError && (
        <ErrorBanner message={fitnessError} onRetry={() => setFitnessError(null)} />
      )}

      {/* Methodology picker */}
      {methodologyIds.length > 0 && (
        <Card>
          <CardTitle>Select Methodology</CardTitle>
          <div className="space-y-1 max-h-60 overflow-y-auto">
            {methodologyIds.map((m) => (
              <button
                key={m.id}
                onClick={() => handleSelect(m.id)}
                className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left text-sm transition-colors ${
                  selectedId === m.id
                    ? "bg-accent/10 border border-accent/40 text-accent"
                    : "hover:bg-card-hover/30 text-foreground"
                }`}
              >
                <span className="font-mono text-xs text-muted shrink-0">
                  {m.id.slice(0, 8)}
                </span>
                <span className="truncate">{m.label}</span>
              </button>
            ))}
          </div>
        </Card>
      )}

      {/* Loading */}
      {loadingTrajectory && (
        <Card>
          <Skeleton className="h-6 w-48 mb-4" />
          <Skeleton className="h-64 w-full" />
        </Card>
      )}

      {/* Trajectory chart */}
      {trajectory !== null && !loadingTrajectory && (
        <>
          {trajectory.length === 0 ? (
            <Card>
              <p className="text-muted text-sm">
                No fitness history for this methodology yet.
              </p>
            </Card>
          ) : (
            <>
              <Card>
                <CardTitle>
                  Fitness Over Time{" "}
                  <span className="text-xs text-muted font-normal ml-2">
                    {selectedId?.slice(0, 8)} — {trajectory.length} entries
                  </span>
                </CardTitle>
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart
                      data={chartData}
                      margin={{ top: 4, right: 16, bottom: 4, left: 0 }}
                    >
                      <XAxis
                        dataKey="timestamp"
                        tick={{ fill: "#8b949e", fontSize: 11 }}
                        axisLine={{ stroke: "#21262d" }}
                        tickLine={false}
                      />
                      <YAxis
                        tick={{ fill: "#8b949e", fontSize: 11 }}
                        axisLine={{ stroke: "#21262d" }}
                        tickLine={false}
                        domain={["auto", "auto"]}
                      />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: "#161b22",
                          border: "1px solid #21262d",
                          borderRadius: "8px",
                          color: "#c9d1d9",
                          fontSize: "12px",
                        }}
                        formatter={((value: unknown) => [
                          Number(value ?? 0).toFixed(3),
                          "Fitness",
                        ]) as Formatter}
                        labelFormatter={(label) => String(label)}
                      />
                      <Line
                        type="monotone"
                        dataKey="fitness"
                        stroke="#58a6ff"
                        strokeWidth={2}
                        dot={{ fill: "#58a6ff", r: 3 }}
                        activeDot={{ r: 5, fill: "#79c0ff" }}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </Card>

              {/* Vector breakdown */}
              {latestVector && Object.keys(latestVector).length > 0 && (
                <Card>
                  <CardTitle>Latest Fitness Vector</CardTitle>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    {Object.entries(latestVector)
                      .sort(([, a], [, b]) => b - a)
                      .map(([dim, val]) => (
                        <div
                          key={dim}
                          className="px-3 py-2 bg-card-border/30 rounded-lg"
                        >
                          <div className="text-xs text-muted capitalize">
                            {dim.replace(/_/g, " ")}
                          </div>
                          <div className="text-sm font-bold text-foreground">
                            {val.toFixed(3)}
                          </div>
                        </div>
                      ))}
                  </div>
                </Card>
              )}

              {/* Event log */}
              <Card>
                <CardTitle>Fitness Events</CardTitle>
                <div className="space-y-1 max-h-48 overflow-y-auto">
                  {trajectory.map((entry, i) => (
                    <div
                      key={i}
                      className="flex items-center gap-3 text-xs px-2 py-1.5 rounded hover:bg-card-hover/30"
                    >
                      <span className="text-muted w-16 shrink-0">
                        {new Date(entry.timestamp).toLocaleDateString()}
                      </span>
                      <span
                        className="font-bold min-w-[50px]"
                        style={{
                          color: winRateColor(
                            Math.max(0, Math.min(1, entry.fitness)),
                          ),
                        }}
                      >
                        {entry.fitness.toFixed(3)}
                      </span>
                      <span className="text-muted truncate">{entry.event}</span>
                    </div>
                  ))}
                </div>
              </Card>
            </>
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function EvolutionLab() {
  const [activeTab, setActiveTab] = useState<Tab>("ab-tests");
  const [error, setError] = useState<string | null>(null);
  const [governanceTrends, setGovernanceTrends] = useState<GovernanceTrendsResponse | null>(null);
  const [securityLaneStatus, setSecurityLaneStatus] = useState<SecurityLaneStatus | null>(null);
  const [federationTrends, setFederationTrends] = useState<FederationTrendsResponse | null>(null);
  const [federationPolicyRecommendations, setFederationPolicyRecommendations] = useState<FederationPolicyRecommendationsResponse | null>(null);
  const [governancePolicies, setGovernancePolicies] = useState<GovernancePolicy[] | null>(null);
  const [governanceConflicts, setGovernanceConflicts] = useState<Array<{
    policy_kind: string;
    task_archetype?: string | null;
    slot_id?: string | null;
    family_barcode?: string | null;
    conflict_reasons: string[];
  }> | null>(null);
  const [governanceFilters, setGovernanceFilters] = useState<{
    taskArchetype: string;
    familyBarcode: string;
    status: string;
  }>({
    taskArchetype: "",
    familyBarcode: "",
    status: "active",
  });
  const [governanceActionState, setGovernanceActionState] = useState<string | null>(null);

  // A/B tests state
  const [abTests, setAbTests] = useState<Record<string, unknown>[] | null>(
    null,
  );

  // Routing state
  const [routing, setRouting] = useState<RoutingEntry[] | null>(null);

  // Bandit state
  const [banditArms, setBanditArms] = useState<BanditArm[] | null>(null);
  const [banditTaskTypes, setBanditTaskTypes] = useState<string[]>([]);

  const loadABTests = useCallback(() => {
    if (abTests !== null) return;
    getABTests()
      .then((data) => setAbTests(data.tests))
      .catch((e) => setError(e.message));
  }, [abTests]);

  const loadRouting = useCallback(() => {
    if (routing !== null) return;
    getRouting()
      .then((data) => setRouting(data.routing))
      .catch((e) => setError(e.message));
  }, [routing]);

  const loadBandit = useCallback(() => {
    if (banditArms !== null) return;
    getBanditArms()
      .then((data) => {
        setBanditArms(data.arms);
        setBanditTaskTypes(data.task_types);
      })
      .catch((e) => setError(e.message));
  }, [banditArms]);

  // Load data for the active tab
  useEffect(() => {
    if (activeTab === "ab-tests") loadABTests();
    else if (activeTab === "routing") loadRouting();
    else if (activeTab === "bandit") loadBandit();
  }, [activeTab, loadABTests, loadRouting, loadBandit]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      getGovernanceTrends({
        limit: 10,
        task_archetype: governanceFilters.taskArchetype || undefined,
        family_barcode: governanceFilters.familyBarcode || undefined,
      }),
      getSecurityLaneStatus(),
      getFederationTrends({
        limit: 10,
        task_archetype: governanceFilters.taskArchetype || undefined,
        family_barcode: governanceFilters.familyBarcode || undefined,
      }),
      getFederationPolicyRecommendations({
        limit: 10,
        task_archetype: governanceFilters.taskArchetype || undefined,
        family_barcode: governanceFilters.familyBarcode || undefined,
      }),
      getGovernanceConflicts({
        task_archetype: governanceFilters.taskArchetype || undefined,
        active_only: governanceFilters.status === "active",
        limit: 20,
      }),
      getGovernancePolicies({
        active_only: governanceFilters.status === "active",
        status: governanceFilters.status === "all" ? undefined : governanceFilters.status,
        task_archetype: governanceFilters.taskArchetype || undefined,
        family_barcode: governanceFilters.familyBarcode || undefined,
        limit: 20,
      }),
    ])
      .then(([trends, securityLane, federation, federationPolicy, conflicts, policies]) => {
        if (cancelled) return;
        setGovernanceTrends(trends);
        setSecurityLaneStatus(securityLane);
        setFederationTrends(federation);
        setFederationPolicyRecommendations(federationPolicy);
        setGovernanceConflicts(conflicts.conflicts);
        setGovernancePolicies(policies.policies);
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [governanceFilters]);

  const retryCurrentTab = useCallback(() => {
    setError(null);
    if (activeTab === "ab-tests") { setAbTests(null); }
    else if (activeTab === "routing") { setRouting(null); }
    else if (activeTab === "bandit") { setBanditArms(null); }
  }, [activeTab]);

  const isLoading =
    (activeTab === "ab-tests" && abTests === null && !error) ||
    (activeTab === "routing" && routing === null && !error) ||
    (activeTab === "bandit" && banditArms === null && !error);

  return (
    <div>
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-foreground">Evolution Lab</h1>
        <p className="text-muted mt-1">
          A/B test results, agent routing heatmap, and bandit arm performance
        </p>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 mb-6">
        <Card>
          <CardTitle>Governance Trends</CardTitle>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4 text-sm">
            <input
              value={governanceFilters.taskArchetype}
              onChange={(e) => setGovernanceFilters((prev) => ({ ...prev, taskArchetype: e.target.value }))}
              placeholder="Filter archetype"
              className="bg-background border border-card-border rounded-lg px-3 py-2 text-foreground"
            />
            <input
              value={governanceFilters.familyBarcode}
              onChange={(e) => setGovernanceFilters((prev) => ({ ...prev, familyBarcode: e.target.value }))}
              placeholder="Filter family barcode"
              className="bg-background border border-card-border rounded-lg px-3 py-2 text-foreground"
            />
            <select
              value={governanceFilters.status}
              onChange={(e) => setGovernanceFilters((prev) => ({ ...prev, status: e.target.value }))}
              className="bg-background border border-card-border rounded-lg px-3 py-2 text-foreground"
            >
              <option value="active">Active policies</option>
              <option value="all">All statuses</option>
              <option value="inactive">Inactive</option>
              <option value="superseded">Superseded</option>
              <option value="waived">Waived</option>
            </select>
          </div>
          {!governanceTrends ? (
            <div className="text-sm text-muted">Loading governance trends...</div>
          ) : (
            <div className="space-y-4 text-sm">
              <div>
                <div className="text-xs text-muted uppercase tracking-wider mb-2">By Archetype</div>
                {governanceTrends.by_archetype.length === 0 ? (
                  <div className="text-sm text-muted">No cross-run governance data yet.</div>
                ) : (
                  <div className="space-y-3">
                    {governanceTrends.by_archetype.slice(0, 5).map((item) => (
                      <div key={item.task_archetype} className="border border-card-border rounded-lg p-3">
                        <div className="font-medium text-foreground">{item.task_archetype}</div>
                        <div className="text-xs text-muted mt-1">
                          runs {item.runs} · blocked wait {(item.blocked_wait_ms / 1000).toFixed(1)}s · family wait {(item.family_wait_ms / 1000).toFixed(1)}s
                        </div>
                        <div className="text-xs text-muted mt-1">
                          blocks {item.block_actions} · bans {item.ban_actions} · reverifies {item.reverify_actions}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div>
                <div className="text-xs text-muted uppercase tracking-wider mb-2">By Family Barcode</div>
                {governanceTrends.by_family.length === 0 ? (
                  <div className="text-sm text-muted">No family-level governance pressure yet.</div>
                ) : (
                  <div className="space-y-3">
                    {governanceTrends.by_family.slice(0, 5).map((item) => (
                      <div key={item.family_barcode} className="border border-card-border rounded-lg p-3">
                        <div className="font-medium text-foreground">{item.family_barcode}</div>
                        <div className="text-xs text-muted mt-1">
                          bans {item.ban_actions} · unbans {item.unban_actions} · waits {item.wait_events} · promoted policies {item.policy_count}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </Card>
        <Card>
          <CardTitle>Security Lane</CardTitle>
          {!securityLaneStatus ? (
            <div className="text-sm text-muted">Loading security lane status...</div>
          ) : (
            <div className="space-y-4 text-sm">
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-lg border border-card-border bg-background p-3">
                  <div className="text-xs text-muted uppercase tracking-wider">Proof Gates</div>
                  <div className="mt-1 text-lg font-semibold text-foreground">
                    {securityLaneStatus.enforcement.reviewed_run_proof_gates ? "On" : "Off"}
                  </div>
                </div>
                <div className="rounded-lg border border-card-border bg-background p-3">
                  <div className="text-xs text-muted uppercase tracking-wider">Pre-Write Block</div>
                  <div className="mt-1 text-lg font-semibold text-foreground">
                    {securityLaneStatus.enforcement.prewrite_blocking ? "On" : "Off"}
                  </div>
                </div>
              </div>
              <div className={`rounded-lg border p-3 ${laneStatusTone(securityLaneStatus.codeql.lane_status)}`}>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs uppercase tracking-wider">CodeQL</span>
                  <span className="rounded border border-current/30 px-2 py-0.5 text-[11px]">
                    {securityLaneStatus.codeql.mode}
                  </span>
                  <span className="rounded border border-current/30 px-2 py-0.5 text-[11px]">
                    {securityLaneStatus.codeql.lane_status || "unknown"}
                  </span>
                </div>
                <div className="mt-2 grid gap-1 text-xs">
                  <span>CLI {securityLaneStatus.codeql.cli_available ? "available" : "missing"}</span>
                  <span>database {securityLaneStatus.codeql.database_configured ? "configured" : "not configured"}</span>
                  <span>queries {securityLaneStatus.codeql.queries_configured ? "configured" : "not configured"}</span>
                </div>
              </div>
              <div className="rounded-lg border border-card-border bg-background p-3 text-xs text-muted">
                <div className="mb-2 text-xs uppercase tracking-wider text-muted-dark">Semgrep</div>
                <div className="grid gap-1">
                  <span>config {securityLaneStatus.semgrep.config_available ? "available" : "missing"}</span>
                  <span>CLI {securityLaneStatus.semgrep.cli_available ? "available" : "missing"}</span>
                  <span>Docker {securityLaneStatus.semgrep.docker_available ? "available" : "missing"}</span>
                  <span>Docker runner {securityLaneStatus.semgrep.docker_runner_available ? "available" : "missing"}</span>
                </div>
              </div>
            </div>
          )}
        </Card>
        <Card>
          <CardTitle>Federation Trends</CardTitle>
          {!federationTrends ? (
            <div className="text-sm text-muted">Loading federation trends...</div>
          ) : (
            <div className="space-y-4 text-sm">
              <div>
                <div className="text-xs text-muted uppercase tracking-wider mb-2">By Archetype</div>
                {federationTrends.by_archetype.length === 0 ? (
                  <div className="text-sm text-muted">No federation pressure recorded yet.</div>
                ) : (
                  <div className="space-y-3">
                    {federationTrends.by_archetype.slice(0, 5).map((item) => (
                      <div key={item.task_archetype} className="border border-card-border rounded-lg p-3">
                        <div className="font-medium text-foreground">{item.task_archetype}</div>
                        <div className="text-xs text-muted mt-1">
                          runs {item.runs} · direct {item.direct_fit} · pattern {item.pattern_transfer} · fallback {item.heuristic_fallback}
                        </div>
                        <div className="text-xs text-muted mt-1">
                          critical pattern transfer {item.critical_pattern_transfer} · success {item.successful_packets} · fail {item.failed_packets}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div>
                <div className="text-xs text-muted uppercase tracking-wider mb-2">By Family</div>
                {federationTrends.by_family.length === 0 ? (
                  <div className="text-sm text-muted">No family-level federation pressure yet.</div>
                ) : (
                  <div className="space-y-3">
                    {federationTrends.by_family.slice(0, 5).map((item) => (
                      <div key={item.family_barcode} className="border border-card-border rounded-lg p-3">
                        <div className="font-medium text-foreground">{item.family_barcode}</div>
                        <div className="text-xs text-muted mt-1">
                          direct {item.direct_fit} · pattern {item.pattern_transfer} · fallback {item.heuristic_fallback}
                        </div>
                        <div className="text-xs text-muted mt-1">
                          critical pattern transfer {item.critical_pattern_transfer} · success {item.successful_packets} · fail {item.failed_packets}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </Card>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 mb-6">
        <Card>
          <CardTitle>Federation Policy Recommendations</CardTitle>
          {!federationPolicyRecommendations ? (
            <div className="text-sm text-muted">Loading federation policy recommendations...</div>
          ) : federationPolicyRecommendations.recommendations.length === 0 ? (
            <div className="text-sm text-muted">No cross-run federation policy recommendations yet.</div>
          ) : (
            <div className="space-y-3 text-sm">
              {federationPolicyRecommendations.recommendations.slice(0, 8).map((item, idx) => (
                <div key={`${item.policy_kind}-${item.family_barcode || item.task_archetype || idx}`} className={`rounded-lg border p-3 ${governanceSeverityTone(item.severity)}`}>
                  <div className="flex items-center justify-between gap-3">
                    <div className="font-medium">{item.policy_kind}</div>
                    <div className="text-[11px] uppercase tracking-wider">{item.severity}{item.already_active ? " · active" : ""}</div>
                  </div>
                  <div className="text-xs mt-2 opacity-90">{item.reason}</div>
                  <div className="text-xs mt-2 opacity-90">{item.recommendation}</div>
                  <div className="text-[11px] mt-2 opacity-80">
                    {item.task_archetype ? `archetype ${item.task_archetype}` : "cross-run"}
                    {item.family_barcode ? ` · family ${item.family_barcode}` : ""}
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      type="button"
                      disabled={item.already_active || governanceActionState === `${item.policy_kind}-${idx}`}
                      onClick={async () => {
                        try {
                          setGovernanceActionState(`${item.policy_kind}-${idx}`);
                          const resp = await promoteFederationPolicy({
                            policy_kind: item.policy_kind,
                            severity: item.severity,
                            task_archetype: item.task_archetype || undefined,
                            slot_id: item.slot_id || undefined,
                            family_barcode: item.family_barcode || undefined,
                            reason: item.reason,
                            recommendation: item.recommendation,
                            evidence_json: item.evidence_json,
                            promoted_by: "operator",
                          });
                          setGovernancePolicies((prev) => [resp.policy, ...(prev || [])]);
                          setFederationPolicyRecommendations((prev) =>
                            prev
                              ? {
                                  ...prev,
                                  recommendations: prev.recommendations.map((rec, recIdx) =>
                                    recIdx === idx ? { ...rec, already_active: true } : rec
                                  ),
                                }
                              : prev
                          );
                        } catch (e) {
                          setError(e instanceof Error ? e.message : String(e));
                        } finally {
                          setGovernanceActionState(null);
                        }
                      }}
                      className="px-3 py-1 rounded border border-card-border text-xs text-foreground hover:bg-card-hover disabled:opacity-50"
                    >
                      Promote Policy
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 mb-6">
        <Card>
          <CardTitle>Governance Policies</CardTitle>
          {!governancePolicies ? (
            <div className="text-sm text-muted">Loading policies...</div>
          ) : governancePolicies.length === 0 ? (
            <div className="text-sm text-muted">No promoted governance policies yet.</div>
          ) : (
            <div className="space-y-3 text-sm">
              {governancePolicies.slice(0, 5).map((policy) => (
                <div key={policy.id} className={`rounded-lg border p-3 ${governanceSeverityTone(policy.severity)}`}>
                  <div className="flex items-center justify-between gap-3">
                    <div className="font-medium">{policy.policy_kind}</div>
                    <div className="text-[11px] uppercase tracking-wider">{policy.severity} · {policy.status}</div>
                  </div>
                  <div className="text-xs mt-2 opacity-90">{policy.reason}</div>
                  <div className="text-xs mt-2 opacity-90">{policy.recommendation}</div>
                  {policy.task_archetype ? (
                    <div className="text-[11px] mt-2 opacity-80">archetype {policy.task_archetype}</div>
                  ) : null}
                  {policy.run_id ? (
                    <div className="mt-2">
                      <a href={`/evolution/run/${policy.run_id}`} className="text-[11px] text-accent hover:text-accent-hover">
                        source run {policy.run_id}
                      </a>
                    </div>
                  ) : null}
                  {policy.family_barcode ? (
                    <div className="text-[11px] mt-2 opacity-80">family {policy.family_barcode}</div>
                  ) : null}
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      type="button"
                      disabled={governanceActionState === policy.id}
                      onClick={async () => {
                        try {
                          setGovernanceActionState(policy.id);
                          const resp = await updateGovernancePolicyStatus(policy.id, { status: "inactive", reason: "manual deactivation" });
                          setGovernancePolicies((prev) => (prev || []).map((item) => (item.id === policy.id ? resp.policy : item)));
                        } catch (e) {
                          setError(e instanceof Error ? e.message : String(e));
                        } finally {
                          setGovernanceActionState(null);
                        }
                      }}
                      className="px-3 py-1 rounded border border-card-border text-xs text-foreground hover:bg-card-hover disabled:opacity-50"
                    >
                      Deactivate
                    </button>
                    <button
                      type="button"
                      disabled={governanceActionState === policy.id}
                      onClick={async () => {
                        try {
                          setGovernanceActionState(policy.id);
                          const resp = await updateGovernancePolicyStatus(policy.id, { status: "superseded", reason: "superseded by newer governance policy" });
                          setGovernancePolicies((prev) => (prev || []).map((item) => (item.id === policy.id ? resp.policy : item)));
                        } catch (e) {
                          setError(e instanceof Error ? e.message : String(e));
                        } finally {
                          setGovernanceActionState(null);
                        }
                      }}
                      className="px-3 py-1 rounded border border-card-border text-xs text-foreground hover:bg-card-hover disabled:opacity-50"
                    >
                      Supersede
                    </button>
                    <button
                      type="button"
                      disabled={governanceActionState === policy.id}
                      onClick={async () => {
                        try {
                          setGovernanceActionState(policy.id);
                          const resp = await updateGovernancePolicyStatus(policy.id, { status: "waived", reason: "manual waiver", waiver_note: "accepted temporary exception" });
                          setGovernancePolicies((prev) => (prev || []).map((item) => (item.id === policy.id ? resp.policy : item)));
                        } catch (e) {
                          setError(e instanceof Error ? e.message : String(e));
                        } finally {
                          setGovernanceActionState(null);
                        }
                      }}
                      className="px-3 py-1 rounded border border-card-border text-xs text-foreground hover:bg-card-hover disabled:opacity-50"
                    >
                      Waive
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <Card>
        <CardTitle>Governance Conflicts</CardTitle>
        {!governanceConflicts ? (
          <div className="text-sm text-muted">Loading governance conflicts...</div>
        ) : governanceConflicts.length === 0 ? (
          <div className="text-sm text-muted">No policy conflicts detected.</div>
        ) : (
          <div className="space-y-3 text-sm">
            {governanceConflicts.slice(0, 10).map((conflict, idx) => (
              <div key={`${conflict.policy_kind}-${idx}`} className="border border-amber-400/30 bg-amber-400/10 rounded-lg p-3">
                <div className="font-medium text-foreground">{conflict.policy_kind}</div>
                <div className="text-xs text-muted mt-1">
                  {conflict.task_archetype ? `archetype ${conflict.task_archetype}` : "global"}
                  {conflict.family_barcode ? ` · family ${conflict.family_barcode}` : ""}
                  {conflict.slot_id ? ` · slot ${conflict.slot_id}` : ""}
                </div>
                <div className="text-xs mt-2 text-amber-200">{conflict.conflict_reasons.join(", ")}</div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Tabs */}
      <div className="flex gap-2 mb-6">
        <TabButton
          active={activeTab === "ab-tests"}
          label="A/B Tests"
          onClick={() => setActiveTab("ab-tests")}
        />
        <TabButton
          active={activeTab === "routing"}
          label="Agent Routing Heatmap"
          onClick={() => setActiveTab("routing")}
        />
        <TabButton
          active={activeTab === "fitness"}
          label="Fitness Trajectories"
          onClick={() => setActiveTab("fitness")}
        />
        <TabButton
          active={activeTab === "bandit"}
          label="Bandit Arms"
          onClick={() => setActiveTab("bandit")}
        />
      </div>

      {/* Error banner */}
      {error && (
        <div className="mb-4">
          <ErrorBanner
            message="Failed to load evolution data"
            detail={error}
            onRetry={retryCurrentTab}
          />
        </div>
      )}

      {/* Loading */}
      {isLoading && (
        <div className="space-y-4">
          <Skeleton className="h-6 w-48" />
          <SkeletonGrid count={3} />
        </div>
      )}

      {/* Tab content */}
      {activeTab === "ab-tests" && abTests !== null && (
        <ABTestsPanel tests={abTests} />
      )}

      {activeTab === "routing" && routing !== null && (
        <RoutingHeatmap routing={routing} />
      )}

      {activeTab === "fitness" && <FitnessPanel />}

      {activeTab === "bandit" && banditArms !== null && (
        <BanditArmsPanel arms={banditArms} taskTypes={banditTaskTypes} />
      )}
    </div>
  );
}
