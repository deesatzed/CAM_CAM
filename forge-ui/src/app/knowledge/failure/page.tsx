"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  getFailureKnowledge,
  resolveFailureKnowledge,
  type FailureKnowledgeEntry,
  type FailureKnowledgeResponse,
} from "@/lib/api";
import { Card, CardTitle, StatCard } from "@/components/card";
import { ErrorBanner } from "@/components/error-banner";
import { SkeletonGrid } from "@/components/skeleton";

function formatDate(value?: string): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function categoryTone(category: string): string {
  if (category === "camseq_negative_memory") {
    return "border-amber-400/30 bg-amber-400/10 text-amber-200";
  }
  if (category.includes("error")) {
    return "border-red-400/30 bg-red-400/10 text-red-300";
  }
  return "border-cam-blue/30 bg-cam-blue/10 text-cam-blue";
}

function resolvedTone(resolved: number): string {
  return resolved
    ? "border-cam-green/30 bg-cam-green/10 text-cam-green"
    : "border-amber-400/30 bg-amber-400/10 text-amber-200";
}

function uniqueCategories(items: FailureKnowledgeEntry[]): string[] {
  return Array.from(new Set(items.map((item) => item.error_category).filter(Boolean))).sort();
}

export default function FailureKnowledgePage() {
  const [data, setData] = useState<FailureKnowledgeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [taskType, setTaskType] = useState("");
  const [category, setCategory] = useState("");
  const [includeResolved, setIncludeResolved] = useState(false);
  const [resolving, setResolving] = useState<string | null>(null);
  const [resolutionText, setResolutionText] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await getFailureKnowledge({
        task_type: taskType.trim() || undefined,
        error_category: category || undefined,
        include_resolved: includeResolved,
        limit: 100,
      });
      setData(response);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [category, includeResolved, taskType]);

  useEffect(() => {
    load();
  }, [load]);

  const categories = useMemo(() => uniqueCategories(data?.items ?? []), [data]);

  async function handleResolve(entry: FailureKnowledgeEntry) {
    const text = resolutionText[entry.error_signature]?.trim();
    setResolving(entry.error_signature);
    try {
      await resolveFailureKnowledge({
        error_signature: entry.error_signature,
        resolution_approach: text || undefined,
      });
      setResolutionText((prev) => ({ ...prev, [entry.error_signature]: "" }));
      await load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setResolving(null);
    }
  }

  const items = data?.items ?? [];
  const groups = data?.groups ?? [];
  const summary = data?.summary;

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-foreground">Failure Knowledge</h1>
        <p className="text-muted mt-1">
          Durable negative memory and preventive failure patterns.
        </p>
      </div>

      {error && (
        <div className="mb-6">
          <ErrorBanner message={error} />
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-3 mb-6">
        <StatCard label="Unresolved" value={summary?.unresolved_count ?? 0} />
        <StatCard label="Resolved" value={summary?.resolved_count ?? 0} />
        <StatCard label="Groups" value={summary?.group_count ?? groups.length} />
      </div>

      <Card className="mb-6">
        <CardTitle>Review Filters</CardTitle>
        <div className="grid gap-3 md:grid-cols-[1fr_220px_auto_auto] items-end">
          <label className="block">
            <span className="block text-xs text-muted uppercase tracking-wider mb-1">Task Type</span>
            <input
              value={taskType}
              onChange={(event) => setTaskType(event.target.value)}
              placeholder="oauth_session_management"
              className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-dark focus:outline-none focus:border-accent/60 focus:ring-1 focus:ring-accent/30"
            />
          </label>
          <label className="block">
            <span className="block text-xs text-muted uppercase tracking-wider mb-1">Category</span>
            <select
              value={category}
              onChange={(event) => setCategory(event.target.value)}
              className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:border-accent/60 focus:ring-1 focus:ring-accent/30"
            >
              <option value="">All</option>
              {categories.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
              {category && !categories.includes(category) && (
                <option value={category}>{category}</option>
              )}
            </select>
          </label>
          <label className="flex items-center gap-2 rounded-lg border border-card-border bg-background px-3 py-2 text-sm text-muted">
            <input
              type="checkbox"
              checked={includeResolved}
              onChange={(event) => setIncludeResolved(event.target.checked)}
              className="h-4 w-4 accent-accent"
            />
            Resolved
          </label>
          <button
            type="button"
            onClick={load}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent-hover transition-colors"
          >
            Refresh
          </button>
        </div>
      </Card>

      {!loading && groups.length > 0 && (
        <section className="mb-6">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-muted">
              Related Failure Groups
            </h2>
            <span className="text-xs text-muted-dark">
              {Object.keys(summary?.category_counts ?? {}).length} categories
            </span>
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            {groups.slice(0, 6).map((group) => (
              <Card key={group.causal_key}>
                <div className="flex flex-wrap items-start gap-2 mb-3">
                  <span
                    className={`rounded border px-2 py-1 text-[11px] font-medium ${categoryTone(group.error_category)}`}
                  >
                    {group.error_category}
                  </span>
                  <span className="rounded border border-card-border bg-background px-2 py-1 text-[11px] text-muted">
                    {group.task_type || "global"}
                  </span>
                  <span className="text-xs text-muted font-mono ml-auto">
                    {group.occurrence_total} hits
                  </span>
                </div>
                <p className="mb-2 break-all font-mono text-xs text-muted-dark">
                  {group.causal_key}
                </p>
                <p className="mb-3 text-sm leading-relaxed text-foreground">
                  {group.diagnosis_samples[0] || "No diagnosis recorded."}
                </p>
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
                  <span>{group.entry_count} records</span>
                  <span>{group.unresolved_count} open</span>
                  <span>{group.resolved_count} resolved</span>
                  <span>updated: {formatDate(group.latest_updated_at || undefined)}</span>
                </div>
                {group.prevention_hints[0] && (
                  <div className="mt-3 rounded-lg border border-card-border bg-background p-3 text-xs leading-relaxed text-amber-100">
                    {group.prevention_hints[0]}
                  </div>
                )}
              </Card>
            ))}
          </div>
        </section>
      )}

      {loading ? (
        <SkeletonGrid count={6} />
      ) : items.length === 0 ? (
        <Card>
          <p className="text-muted text-sm">No failure knowledge records match the current filters.</p>
        </Card>
      ) : (
        <div className="space-y-4">
          {items.map((entry) => (
            <Card key={entry.id || entry.error_signature}>
              <div className="flex flex-wrap items-start gap-3 mb-3">
                <span
                  className={`rounded border px-2 py-1 text-[11px] font-medium ${categoryTone(entry.error_category)}`}
                >
                  {entry.error_category}
                </span>
                <span
                  className={`rounded border px-2 py-1 text-[11px] font-medium ${resolvedTone(entry.resolved)}`}
                >
                  {entry.resolved ? "resolved" : "open"}
                </span>
                <span className="text-xs text-muted font-mono ml-auto">
                  {entry.occurrence_count}x
                </span>
              </div>

              <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(280px,360px)]">
                <div className="min-w-0">
                  <p className="text-xs text-muted-dark font-mono break-all mb-3">
                    {entry.error_signature}
                  </p>
                  <p className="text-sm text-foreground leading-relaxed mb-3">
                    {entry.diagnosis}
                  </p>
                  <div className="rounded-lg border border-card-border bg-background p-3 text-sm text-amber-100 leading-relaxed">
                    {entry.prevention_hint}
                  </div>
                  <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
                    <span>task: {entry.task_type || "global"}</span>
                    <span>project: {entry.project_id || "global"}</span>
                    <span>source: {entry.source_task_id || "-"}</span>
                    <span>updated: {formatDate(entry.updated_at)}</span>
                  </div>
                </div>

                <div>
                  {entry.resolved ? (
                    <div className="rounded-lg border border-cam-green/20 bg-cam-green/5 p-3">
                      <div className="text-xs text-muted uppercase tracking-wider mb-2">
                        Resolution
                      </div>
                      <p className="text-sm text-foreground leading-relaxed">
                        {entry.resolution_approach || "Resolved"}
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      <textarea
                        value={resolutionText[entry.error_signature] ?? ""}
                        onChange={(event) =>
                          setResolutionText((prev) => ({
                            ...prev,
                            [entry.error_signature]: event.target.value,
                          }))
                        }
                        placeholder="Resolution approach"
                        rows={4}
                        className="w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-dark focus:outline-none focus:border-accent/60 focus:ring-1 focus:ring-accent/30 resize-none"
                      />
                      <button
                        type="button"
                        disabled={resolving === entry.error_signature}
                        onClick={() => handleResolve(entry)}
                        className="w-full rounded-lg border border-cam-green/40 bg-cam-green/10 px-4 py-2 text-sm font-semibold text-cam-green hover:bg-cam-green/15 transition-colors disabled:opacity-50"
                      >
                        {resolving === entry.error_signature ? "Resolving..." : "Resolve"}
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
