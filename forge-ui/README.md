# CAM_CAM Forge UI

The browser interface for CAM_CAM/CAM-PULSE. It is a Next.js App Router app backed by the FastAPI dashboard server in `src/claw/web/dashboard_server.py`.

Current launch evidence, verified 2026-06-19:

- 20 Next.js page files under `forge-ui/src/app`
- 91 FastAPI routes in the backend dashboard server
- `next@16.2.9`, `react@19.2.4`, `react-dom@19.2.4`
- Production build passes with `npm run build`
- `npm audit fix` resolved the prior high advisory and several transitive advisories
- Remaining audit item: 2 moderate advisories for Next's bundled PostCSS; npm's only automated fix is `npm audit fix --force`, which downgrades to `next@9.3.3`, so it is intentionally deferred and documented in `docs/LAUNCH_METRICS_2026-06-19.md`

## Quick Start

From the repo root:

```bash
PYTHONPATH=src python -m claw.cli dashboard
```

Then in this directory:

```bash
npm ci
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). The frontend reads the backend URL from `NEXT_PUBLIC_API_URL`, defaulting to `http://localhost:8420`.

## Production Build

```bash
npm ci
npm run build
```

## Pages

| Page | Route |
|---|---|
| Dashboard | `/` |
| Costs | `/costs` |
| Evolution Lab | `/evolution` |
| Evolution Run | `/evolution/run/[runId]` |
| Federation Hub | `/federation` |
| Brain Graph | `/forge` |
| Build Brain | `/forge/build` |
| Brain Detail | `/forge/brain/[name]` |
| Forge Run | `/forge/run/[id]` |
| Script Generator | `/forge/script` |
| Knowledge Explorer | `/knowledge` |
| Methodology Detail | `/knowledge/[id]` |
| Attribution | `/knowledge/attribution` |
| Components | `/knowledge/components` |
| Component Detail | `/knowledge/components/[componentId]` |
| Failure Knowledge | `/knowledge/failure` |
| Gap Heatmap | `/knowledge/gaps` |
| Mining Console | `/mining` |
| Playground | `/playground` |
| Playground Plan | `/playground/plan/[planId]` |

## Tech Stack

- Next.js 16 App Router with TypeScript
- Tailwind CSS
- Recharts for charts
- D3.js for force-directed graphs
- FastAPI backend at `localhost:8420`

## Backend Verification

Focused backend tests live in the parent repo:

```bash
cd ..
PYTHONPATH=src python -m pytest tests/test_dashboard_server.py tests/test_dashboard_playground.py tests/test_cli_ux.py tests/test_miner.py -q
```
