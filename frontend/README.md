# AgentShield web dashboard

React + TypeScript single-page app for the AgentShield AI-agent testing, benchmarking, anomaly-detection and
security-governance platform. Every number on screen comes from the FastAPI backend (`/api/v1/...`); there is
no mock or hard-coded data. Simulated latency/tokens, estimated costs and "signal, not proof" caveats are
labelled in the UI.

Stack (exact versions pinned in `package.json`): React 18.3.1, TypeScript 5.6.3, Vite 5.4.21,
Tailwind CSS 3.4.19, React Router 6.28.2, TanStack Query 5.62.16, Recharts 2.13.3.

## Development

Requires Node 20+ and the backend running on `http://localhost:8000`.

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173 ; /api and /health are proxied to :8000
```

Point the dev proxy at another backend with `AGENTSHIELD_API=http://host:8000 npm run dev`.

## Build

```bash
npm run build        # tsc --noEmit (type check) + vite build -> dist/
npm run preview      # serve dist/ locally on :4173 (no API proxy)
```

## Docker

```bash
docker build -t agentshield/frontend:0.1.0 frontend
```

Multi-stage image: `node:22-alpine` builds the app, `nginx:1.27-alpine` serves it on **port 80**.
`nginx.conf` serves the SPA with history fallback to `index.html` and proxies `/api/` and `/health` to
`http://backend:8000` (120 s read timeout - some analytics endpoints run several Trino queries). The backend
host is resolved at request time through Docker's embedded DNS (`127.0.0.11`), so the container must run on
the compose network next to a service named `backend`. Example compose service:

```yaml
frontend:
  image: agentshield/frontend:0.1.0
  build: ./frontend
  ports: ["3000:80"]
  depends_on: [backend]
```

## Pages

| Route | Page | Main endpoints |
|---|---|---|
| `/` | Overview - KPIs, hourly trend, pipeline status | `GET /overview`, `GET /pipeline/health` |
| `/testing` | Testing Lab - configure/launch/stop workloads, live run status, regression gate | `GET /scenarios`, `GET/POST /test-runs`, `GET /test-runs/{id}`, `POST /test-runs/{id}/stop`, `POST /regression-gate`, `GET /regression-gate/results`, `GET /agents` |
| `/runs` | Run Explorer - filters, sorting, pagination | `GET /runs` |
| `/runs/:id` | Trace view - waterfall, span attributes, evaluations, findings, alerts (`:id` = trace id or run id) | `GET /traces/{trace_id}`, `GET /runs/{run_id}` |
| `/performance` | Performance Analytics | `GET /analytics/performance` |
| `/quality` | Quality & RAG Evaluation | `GET /analytics/quality` |
| `/anomalies` | Anomaly Center - holdout detector evaluation, alerts, feedback | `GET /anomalies`, `GET /anomalies/summary`, `GET /anomalies/{id}`, `POST /anomalies/{id}/feedback` |
| `/security` | Security & Governance - summary, findings, policy-as-code | `GET /security/summary`, `GET /security/findings`, `GET /security/policy` |
| `/sql` | SQL Analytics - curated query gallery with parameters | `GET /analytics/sql-showcase`, `POST /analytics/sql-showcase/{name}/run` |
| `/compare` | Agent Comparison + regression cohorts | `GET /analytics/comparison`, `GET /analytics/regressions` |
| `/assistant` | AI Investigation Assistant | `POST /investigations`, `GET /investigations/examples`, `GET /investigations/history` |
| `/pipeline` | Pipeline Health (auto-refresh 10 s) + data quality | `GET /pipeline/health`, `GET /analytics/data-quality` |
| `/reports` | Report downloads (CSV / Markdown / JSON / printable HTML -> PDF) | `GET /test-runs`, `GET /reports/{id}?format=` |

The top bar's time range (1 / 7 / 30 / 90 days) is sent as `days` to every page that supports it (it is dimmed
on pages that are not time-filtered). Light/dark mode follows the OS; the top-bar button can pin a theme.

## Layout

```
src/
  api/        client.ts (fetch + error normalisation), types.ts (response shapes), hooks.ts (React Query)
  components/ layout/ (sidebar, top bar), ui/ (cards, tables, badges, states), charts/ (Recharts wrappers), trace/ (waterfall)
  lib/        formatting, time-range context, nav, safe Markdown renderer
  pages/      one file per page
```

Charts use a colour-vision-validated categorical palette and a blue ordinal ramp (light and dark steps), a
single y-axis per chart, and every chart has a table view.
