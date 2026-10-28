# AgentShield — MongoDB Integration & Architecture Guide (`MONGODB_README.md`)

> **Faculty Viva & Demo Quick Link:** For the comprehensive interactive query reference, copy-paste demonstration script, and Big Data viva defense notes, open:  
> 👉 [`docs/MONGODB_QUERY_REFERENCE.md`](file:///c:/Users/Tapan/Downloads/BigDataPR/docs/MONGODB_QUERY_REFERENCE.md)

Welcome to the **AgentShield MongoDB Guide**. This document explains **what** MongoDB stores in AgentShield, **why** our Big Data platform uses polyglot persistence, **where** the code lives, and **how** it operates alongside Kafka, Spark, Apache Iceberg, MinIO, Trino, and PostgreSQL.

---

## 1. Overview

### What is MongoDB in AgentShield?
MongoDB 7.0 is our operational NoSQL document database, configured with the WiredTiger storage engine and enforced via `$jsonSchema` validation. It manages two high-value operational collections:
1. **`security_cases`**: Operational security incident triage, collaborative timelines, polymorphic evidence bundles, and MTTR compliance.
2. **`investigation_sessions`**: AI Investigation Assistant conversational multi-turn session memory, lakehouse evidence references, and model evaluation feedback store.

### Why Polyglot Persistence?
1. **Academic & Big Data Curriculum Requirement:**
   Modern Big Data architectures require demonstrating **Polyglot Persistence**—pairing an analytical lakehouse (OLAP) with a document-oriented operational database (NoSQL) to handle different data velocities, access patterns, and mutation lifecycles.
2. **Operational Document Mutation vs. Columnar Lakehouse:**
   While Apache Iceberg stores raw, immutable telemetry at scale, analysts need sub-millisecond atomic document updates (`$set`, `$push`, `$inc`, `arrayFilters`) for incident management and multi-turn AI dialogues without triggering expensive Iceberg commit cycles.

---

## 2. Before vs. After MongoDB Integration

### Before MongoDB Integration
- AgentShield collected agent telemetry through Kafka, processed streams in Spark Structured Streaming, and committed immutable Parquet files to Apache Iceberg on MinIO.
- Security findings and investigation queries were queried via Trino or stored as flat historical logs in PostgreSQL.
- **Problem:** Security analysts had no way to conduct multi-turn investigations, save assistant conversation memory, submit turn-level evaluation feedback, or track remediation workflows in real-time.

### After MongoDB Integration
- Telemetry facts remain safely stored in Apache Iceberg for analytical integrity (Zero Data Duplication).
- Security findings can be escalated into **Operational Security Cases** (`security_cases`).
- Analysts conduct multi-turn troubleshooting with preserved context and evaluation feedback in **Investigation Sessions** (`investigation_sessions`).

### Capability Comparison Table

| Feature / Dimension | Before (Iceberg + Postgres Only) | After (Iceberg + MongoDB Integration) |
|---|---|---|
| **Storage Architecture** | OLAP Lakehouse + Relational DB | **Polyglot Persistence**: OLAP (Iceberg) + RDBMS (Postgres) + NoSQL (MongoDB 7.0) |
| **Security Finding Handling** | Read-only detection facts in lakehouse tables | Findings escalated into mutable operational cases |
| **AI Assistant Memory** | Stateless or single-turn flat Postgres rows | Persistent multi-turn dialogues in `investigation_sessions` |
| **Data Mutability** | Append-only batch commits | Sub-millisecond atomic document updates (`$set`, `$push`, `$inc`) |
| **Turn-Level Evaluation** | None | Surgical feedback ratings & verdicts using `arrayFilters` |
| **Operational Metrics** | SQL batch scans on lakehouse | Live MongoDB aggregation pipelines (`$facet`, `$bucket`, `$group`) |
| **Data Integrity** | Table schemas in Iceberg/Postgres | Document schema enforced by MongoDB engine `$jsonSchema` |

---

## 3. What MongoDB Does in AgentShield

MongoDB powers two operational capabilities:

### Capability 1: Operational Security Cases (`security_cases`)

1. **Security Case Management:**
   A case represents an active security investigation (e.g. unauthorized egress attempt or synthetic canary token leak). Cases maintain standardized IDs (e.g. `CASE-202610-0042`), titles, severities (`low`, `medium`, `high`, `critical`), and operational priorities (`P1`–`P4`).
2. **Lifecycle Transitions:**
   Cases move through formal operational states:
   $$\text{OPEN} \longrightarrow \text{TRIAGED} \longrightarrow \text{IN\_REVIEW} \longrightarrow \text{REMEDIATION\_PENDING} \longrightarrow \text{RESOLVED} \text{ (or DISMISSED)}$$
3. **Analyst Assignment & SLA Tracking:**
   Incidents can be assigned to specific analysts (e.g. `@sarah.chen`). The backend automatically computes SLA deadlines based on priority (e.g., P1 requires triage within 1 hour and resolution within 4 hours).
4. **Collaborative Investigation Timeline:**
   Analysts can record forensic observations, tool traces, and notes. Timeline entries are atomically appended to the document using MongoDB's `$push` operator, preserving an chronological audit trail with author attribution.
5. **Polymorphic Evidence Bundles:**
   Different attacks produce different evidence. MongoDB allows attaching varied evidence formats (canary leak buffers, policy denials, prompt-injection snippets) within an embedded array in the same document without modifying a rigid table schema.
6. **Remediation Tracking:**
   Tracks recommended policy actions (e.g., `DROP_TOOL_PERMISSIONS`, `REVOKE_EGRESS_CAPABILITY`), target tool names, and policy configuration files (`config/policies.yaml`). A case can be marked resolved only when remediation is verified.
7. **Telemetry Correlation (No Data Duplication):**
   Raw telemetry rows remain in Iceberg. MongoDB documents store references to `finding_id` and `trace_id`. The UI provides direct links back to the lakehouse trace waterfall (`/app/runs/{trace_id}`).

### Capability 2: AI Assistant Multi-Turn Session Memory & Evaluation Store (`investigation_sessions`)

1. **Stateful Multi-Turn Dialogues:**
   Maintains conversational memory across turns for specific security investigations. Sessions maintain persistent IDs (e.g. `SES-20261028-4A9B1C`), titles, assigned analysts, and scoped context (`test_run_id`, `trace_id`, `agent_id`).
2. **Atomic In-Place Append:**
   Follow-up questions and grounded answers are appended to the document's `turns` array using MongoDB's atomic `$push` and `$inc` operators without rewriting the conversation.
3. **Structured Lakehouse Evidence Referencing:**
   Each turn records structured evidence links pointing back to Iceberg lakehouse traces and SQL showcase queries without duplicating telemetry payloads.
4. **Surgical Turn Evaluation with `arrayFilters`:**
   Analysts submit 1–5 star ratings, verdicts (`accurate`, `hallucination`, `incomplete`, `irrelevant`, `misleading`), and forensic review notes. Updates target *only* the specific turn subdocument via MongoDB's `arrayFilters` operator (`$[elem]`).
5. **Real-Time Evaluation Analytics:**
   Multi-branch aggregation pipelines (`$facet`, `$bucket`, `$unwind`) aggregate model accuracy, groundedness ratio, and session depth distributions in a single database round-trip.

---

## 4. Architecture and Data Flow

### The Polyglot Persistence Architecture

```text
Deterministic Agent Workload Generator
                  │
                  ▼
          Apache Kafka (6 topics)
                  │
                  ▼
    Spark Structured Streaming (2 queries)
                  │
                  ▼
      Apache Iceberg (MinIO S3)  <─────────┐  (Read-only telemetry correlation)
                  │                        │
                  ▼                        │
          Trino SQL Engine                 │
                  │                        │
                  ▼                        │
       FastAPI Backend API  ───────────────┼──────────────┐
                  │                        │              │
                  │ (Lakehouse queries)    │              ▼
                  ▼                        │      MongoDB 7.0 (WiredTiger)
       React Web Dashboard ────────────────┘      - security_cases collection
       - Findings Tab (Lakehouse)                 - Mutable case documents
       - Investigation Cases Tab (MongoDB)        - Collaborative timelines
                                                  - Polymorphic evidence
```

### Why MongoDB Complements Rather Than Replaces Iceberg

1. **OLAP vs. OLTP / Operational Workloads:**
   - **Iceberg** is an analytical lakehouse format. It is designed to scan millions of rows across columnar Parquet files for aggregations, model evaluations, and trend analysis. Running single-record updates or appending short analyst comments in Iceberg would generate excessive small metadata files and snapshot churn.
   - **MongoDB** is an operational document store. It handles concurrent, low-latency, point-in-time reads and atomic updates to individual documents without snapshot rewrites.
2. **Zero Raw Event Duplication:**
   We do not duplicate millions of high-volume telemetry events inside MongoDB. Instead, raw events stay in Iceberg, and MongoDB stores only mutable incident documents that reference findings and traces by their IDs.
3. **Complementary Correlation:**
   A security engineer spots an exfiltration finding in Trino/Iceberg, clicks "Escalate", and creates a MongoDB incident document. The MongoDB document links the lakehouse `trace_id`. Anyone opening the case can click "View Trace" to load the complete span waterfall from the lakehouse.

---

## 5. Important Files and Folders

All MongoDB code adheres to the project's existing modular directory structure:

| File / Folder Path | Type | Purpose |
|---|---|---|
| [`infra/mongo/init-mongo.js`](file:///c:/Users/Tapan/Downloads/BigDataPR/infra/mongo/init-mongo.js) | JavaScript | Database bootstrap script. Runs automatically on container startup to create the `security_cases` collection, apply `$jsonSchema` validation, and create 7 indexes. |
| [`backend/app/mongo.py`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/app/mongo.py) | Python | Thread-safe MongoDB connection lifecycle. Manages client pooling (`maxPoolSize=10`), health check pinging, and graceful degradation during outages. |
| [`backend/app/routers/cases.py`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/app/routers/cases.py) | Python | FastAPI router (`/api/v1/cases`). Implements CRUD endpoints, finding escalation from lakehouse queries, and live aggregation pipelines. |
| [`scripts/inspect_mongo.py`](file:///c:/Users/Tapan/Downloads/BigDataPR/scripts/inspect_mongo.py) | Python | Command-line utility to inspect MongoDB document counts, table summaries, and full formatted JSON cases from the host terminal. |
| [`backend/tests/test_mongo_infra.py`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/tests/test_mongo_infra.py) | Python | 8 unit tests verifying client options, pool timeouts, schema definitions, indexes, and service degradation handling. |
| [`backend/tests/test_cases.py`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/tests/test_cases.py) | Python | 16 API tests verifying case creation, duplicate conflict rejection, lifecycle transitions, timeline push, evidence attachment, escalation, and aggregations. |
| [`frontend/src/components/cases/CaseManagement.tsx`](file:///c:/Users/Tapan/Downloads/BigDataPR/frontend/src/components/cases/CaseManagement.tsx) | TypeScript / React | Main frontend component: KPI cards, filter bar, master table, detail drawer, timeline view, evidence bundle, and create-case modal. |
| [`frontend/src/pages/Security.tsx`](file:///c:/Users/Tapan/Downloads/BigDataPR/frontend/src/pages/Security.tsx) | TypeScript / React | Security page integrating the **"Investigation Cases (MongoDB)"** tab and the **"Escalate"** button on findings rows. |
| [`frontend/src/api/hooks.ts`](file:///c:/Users/Tapan/Downloads/BigDataPR/frontend/src/api/hooks.ts) | TypeScript | React Query hooks (`useCases`, `useCase`, `useCaseAnalytics`, `useUpdateCase`, `useEscalateFinding`, etc.). |
| [`frontend/src/api/types.ts`](file:///c:/Users/Tapan/Downloads/BigDataPR/frontend/src/api/types.ts) | TypeScript | TypeScript interfaces matching backend models (`SecurityCase`, `TimelineEntry`, `CaseEvidenceItem`, `CaseAnalytics`). |
| [`docker-compose.yml`](file:///c:/Users/Tapan/Downloads/BigDataPR/docker-compose.yml) | YAML | Declares the `mongodb` service with container name `agentshield-mongodb`, port mapping `27017:27017`, memory limit `512m`, cache limit `0.25GB`, and volume `mongo-data`. |
| [`.env.example`](file:///c:/Users/Tapan/Downloads/BigDataPR/.env.example) | Configuration | Documents environment variables: `MONGO_USER`, `MONGO_PASSWORD`, `MONGO_DB`, `MONGO_HOST_PORT`. |

---

## 6. Database Structure

### Database and Collection Names
- **Database:** `agentshield`
- **Collection:** `security_cases`

### Document Structure & Validation Rules
The database uses MongoDB `$jsonSchema` validation configured in [`infra/mongo/init-mongo.js`](file:///c:/Users/Tapan/Downloads/BigDataPR/infra/mongo/init-mongo.js). Invalid writes are rejected at the database level.

```json
{
  "_id": "ObjectId('...')",
  "case_id": "CASE-202610-0042",
  "title": "Exfiltration sequence detected via curl_egress",
  "status": "OPEN",
  "severity": "critical",
  "priority": "P1",
  "target_agent": {
    "agent_id": "ops-tool-agent",
    "agent_version": "1.1.0",
    "workload_type": "tool",
    "model_name": "claude-3-5-sonnet"
  },
  "assigned_analyst": {
    "username": "sarah.chen",
    "email": "sarah.chen@agentshield.corp",
    "assigned_at": "ISODate('2026-10-26T10:15:00Z')"
  },
  "triage_deadline": "ISODate('2026-10-26T11:00:00Z')",
  "resolution_deadline": "ISODate('2026-10-26T14:00:00Z')",
  "linked_findings": [
    {
      "finding_id": "SEC-F-5555",
      "rule_id": "SEC-007",
      "rule_name": "exfiltration_sequence",
      "severity": "critical",
      "trace_id": "0192a7f3b89c71e2a0b3c4d5e6f70819",
      "span_id": "7f3a9c1e2b4d5a6b",
      "event_time": "ISODate('2026-10-26T09:58:12Z')"
    }
  ],
  "linked_anomaly_alerts": [],
  "evidence_bundle": [
    {
      "evidence_id": "EV-202610-0001",
      "kind": "canary_leak",
      "title": "Synthetic Canary Token in Egress Payload",
      "detail": "Token AGSH-CANARY-5F1E present in buffer",
      "ref": "span:7f3a9c1e2b4d5a6b",
      "metadata": { "bytes_matched": 18 },
      "attached_at": "ISODate('2026-10-26T10:05:00Z')",
      "attached_by": "triage_bot"
    }
  ],
  "timeline": [
    {
      "entry_id": "TL-0001",
      "timestamp": "ISODate('2026-10-26T10:00:00Z')",
      "author": "triage_bot",
      "action": "ESCALATED_FROM_FINDING",
      "notes": "Escalated automatically from finding SEC-F-5555"
    }
  ],
  "remediation": {
    "recommended_action": "DROP_TOOL_PERMISSIONS",
    "policy_file": "config/policies.yaml",
    "target_tool": "curl_egress",
    "requires_code_freeze": false,
    "completed": false,
    "completed_at": null,
    "completed_by": null
  },
  "tags": ["exfiltration", "p1-blocker", "tool-abuse"],
  "created_by": "triage_bot",
  "created_at": "ISODate('2026-10-26T10:00:00Z')",
  "updated_at": "ISODate('2026-10-26T10:15:00Z')"
}
```

### Collection Indexes

| Index Name | Indexed Fields | Key Advantage |
|---|---|---|
| `idx_case_id_unique` | `{ case_id: 1 }` (unique) | Enforces unique business IDs; enables $O(1)$ lookups. |
| `idx_cases_triage_sla` | `{ status: 1, severity: 1, priority: 1, created_at: -1 }` | Fast filtering for active triage queues and SLA-breach monitoring. |
| `idx_cases_target_agent` | `{ "target_agent.agent_id": 1, "target_agent.agent_version": 1 }` | Accelerates per-agent incident grouping and regressions. |
| `idx_multikey_findings_finding_id` | `{ "linked_findings.finding_id": 1 }` | **Multikey Index**: fast check if a finding is already linked to a case. |
| `idx_multikey_findings_trace_id` | `{ "linked_findings.trace_id": 1 }` | **Multikey Index**: correlates trace IDs from lakehouse waterfall. |
| `idx_multikey_alerts_alert_id` | `{ "linked_anomaly_alerts.alert_id": 1 }` | **Multikey Index**: correlates ML anomaly alerts with open cases. |
| `idx_text_title_notes` | `{ title: "text", "timeline.notes": "text" }` | **Full-Text Index**: fast keyword search across titles and timeline notes. |

---

## 7. How to Run and Interact with MongoDB

All commands below are tailored for **Windows PowerShell** in the project root directory.

### 7.1 Starting the Service
Start MongoDB along with the core stack:
```powershell
# Start MongoDB in the background
docker compose up -d mongodb

# Or start the entire AgentShield core stack
docker compose up -d
```

### 7.2 Checking Container & MongoDB Health
Check that the container is healthy:
```powershell
docker ps --filter "name=agentshield-mongodb"
```

Verify via the backend pipeline health API:
```powershell
curl http://localhost:8000/api/v1/pipeline/health
```
*(Look for `"mongodb": {"status": "ok"}` in the JSON response).*

### 7.3 Accessing the Interactive Mongo Shell (`mongosh`)
Run `mongosh` inside the container using the credentials specified in your `.env`:
```powershell
docker exec -it agentshield-mongodb mongosh -u agentshield -p agentshield-mongo-secret --authenticationDatabase admin agentshield
```

### 7.4 Running the Host Python Inspection Script
We built a standalone CLI script to inspect the database from your host environment:
```powershell
# View summary table of cases and document counts
.\.venv\Scripts\python scripts/inspect_mongo.py

# Print the most recent case in full formatted JSON
.\.venv\Scripts\python scripts/inspect_mongo.py -v

# Inspect a specific case document by ID
.\.venv\Scripts\python scripts/inspect_mongo.py --case-id CASE-202610-0042
```

### 7.5 Accessing the Web Dashboard
Open your browser to:
- **Dashboard URL:** `http://localhost:3000`
- Navigate to: **Security & Governance** → **Investigation Cases (MongoDB)** tab.

---

## 8. Useful MongoDB Queries (`mongosh`)

You can run these safe, verified queries directly inside the `mongosh` prompt:

### Count Total Cases
```javascript
db.security_cases.countDocuments();
```

### View Summary List of Cases
```javascript
db.security_cases.find(
  {},
  { case_id: 1, title: 1, status: 1, severity: 1, priority: 1, "target_agent.agent_id": 1, updated_at: 1 }
).sort({ created_at: -1 }).pretty();
```

### Filter Active P1 or Critical Cases
```javascript
db.security_cases.find({
  status: { $in: ["OPEN", "TRIAGED", "IN_REVIEW"] },
  $or: [{ severity: "critical" }, { priority: "P1" }]
}, { case_id: 1, title: 1, severity: 1, priority: 1, status: 1 }).pretty();
```

### Filter Cases by Target Agent
```javascript
db.security_cases.find({
  "target_agent.agent_id": "ops-tool-agent",
  status: { $ne: "RESOLVED" }
}).pretty();
```

### Find Case by Linked Finding ID (Uses Multikey Index)
```javascript
db.security_cases.find({
  "linked_findings.finding_id": "SEC-F-5555"
}).pretty();
```

### Full-Text Search Across Titles and Notes
```javascript
db.security_cases.find(
  { $text: { $search: "exfiltration canary" } },
  { score: { $meta: "textScore" }, case_id: 1, title: 1 }
).sort({ score: { $meta: "textScore" } }).pretty();
```

### Transition Status & Assign Analyst
```javascript
db.security_cases.updateOne(
  { case_id: "CASE-202610-0042" },
  {
    $set: {
      status: "IN_REVIEW",
      assigned_analyst: {
        username: "sarah.chen",
        email: "sarah.chen@agentshield.corp",
        assigned_at: new Date()
      },
      updated_at: new Date()
    }
  }
);
```

### Append an Observation Note to the Collaborative Timeline (`$push`)
```javascript
db.security_cases.updateOne(
  { case_id: "CASE-202610-0042" },
  {
    $push: {
      timeline: {
        timestamp: new Date(),
        author: "sarah.chen",
        action: "FORENSIC_ANALYSIS",
        notes: "Waterfall inspection confirms synthetic canary was caught by guardrail."
      }
    },
    $set: { updated_at: new Date() }
  }
);
```

### Complete Remediation and Resolve Case
```javascript
db.security_cases.updateOne(
  { case_id: "CASE-202610-0042" },
  {
    $set: {
      status: "RESOLVED",
      "remediation.completed": true,
      "remediation.completed_at": new Date(),
      "remediation.completed_by": "sarah.chen",
      updated_at: new Date()
    }
  }
);
```

### Aggregation: Live Caseload by Status
```javascript
db.security_cases.aggregate([
  { $group: { _id: "$status", count: { $sum: 1 } } },
  { $sort: { count: -1 } }
]);
```

### Aggregation: Mean Time to Remediation (MTTR) in Hours
```javascript
db.security_cases.aggregate([
  { $match: { status: "RESOLVED", "remediation.completed": true } },
  {
    $project: {
      severity: 1,
      duration_hours: {
        $divide: [{ $subtract: ["$updated_at", "$created_at"] }, 3600000]
      }
    }
  },
  {
    $group: {
      _id: "$severity",
      resolved_cases: { $sum: 1 },
      avg_hours: { $avg: "$duration_hours" }
    }
  }
]);
```

### Inspect Index Usage with `explain("executionStats")`
```javascript
db.security_cases.find({ "linked_findings.finding_id": "SEC-F-5555" })
  .explain("executionStats");
```
*(Verify that `winningPlan.inputStage.stage` shows `IXSCAN` using `idx_multikey_findings_finding_id`).*

---

## 9. API and UI Integration

### 9.1 FastAPI REST Endpoints (`/api/v1/cases`)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/cases` | Filtered, paginated list of cases with sorting and free-text search. |
| `POST` | `/api/v1/cases` | Create a new case; computes SLA deadlines and enforces schema validation. |
| `GET` | `/api/v1/cases/summary/analytics` | Aggregation pipeline computing caseload, P1 count, unassigned queue, and MTTR. |
| `POST` | `/api/v1/cases/escalate-finding` | Promotes an Iceberg finding into a MongoDB case. |
| `GET` | `/api/v1/cases/{case_id}` | Fetches full document with findings, evidence, and timeline. |
| `PATCH` | `/api/v1/cases/{case_id}` | Updates status, assignee, priority, tags, or remediation completion. |
| `POST` | `/api/v1/cases/{case_id}/timeline` | Atomically appends an analyst observation note via `$push`. |
| `POST` | `/api/v1/cases/{case_id}/findings` | Idempotently links a security finding via `$addToSet`. |
| `POST` | `/api/v1/cases/{case_id}/evidence` | Attaches a polymorphic evidence item via `$push`. |
| `DELETE` | `/api/v1/cases/{case_id}` | Deletes a case document. |

### 9.2 Dashboard UI Overview
In the React workbench at `http://localhost:3000`:
1. **Security & Governance → Findings Tab:**
   Every finding row contains an **"Escalate"** button. Clicking it calls `/api/v1/cases/escalate-finding` and displays a banner with a direct link to the new case.
2. **Security & Governance → Investigation Cases (MongoDB) Tab:**
   - **5 Live KPI Tiles:** Total Open Cases, P1/Critical Incidents, Unassigned Cases, Breached SLAs, and MTTR in hours.
   - **Filter Bar:** Filter cases by status, severity, priority, target agent, or free-text search.
   - **New Case Button:** Opens a modal to create cases manually.
   - **Interactive Detail Drawer:** Clicking any case opens a side drawer to:
     - Change status (`OPEN` → `TRIAGED` → `IN_REVIEW` → `REMEDIATION_PENDING` → `RESOLVED`).
     - Assign an analyst handle.
     - Toggle remediation completion (`DROP_TOOL_PERMISSIONS`, etc.).
     - View the chronological timeline and post new notes.
     - Inspect and attach polymorphic evidence items.
     - Jump directly to the linked trace waterfall in the lakehouse (`/app/runs/{trace_id}`).

---

## 10. Impact and Benefits

### Implemented Operational Capabilities
- **Collaborative Incident Management:** Security teams can track, discuss, and resolve vulnerabilities discovered in autonomous agent executions without leaving the platform.
- **Traceability:** Links immutable analytical lakehouse traces to human operational actions (e.g. which engineer approved dropping tool permissions and when).
- **Audit-Ready History:** Chronological timeline entries provide forensic accountability for each investigation.
- **Operational Metrics:** Live aggregation pipelines calculate real Mean Time to Remediation (MTTR) and SLA breach counts.

### Realistic Clarifications
- **No Claims of "Faster Kafka/Spark Ingestion":** MongoDB does *not* speed up Kafka or Spark streaming. Streaming ingestion performance is governed by Kafka partitions and Spark micro-batch triggers.
- **No Replacement of the Lakehouse:** MongoDB does not replace Iceberg. Storing millions of raw telemetry events in MongoDB would be inefficient for OLAP scans. The two engines serve distinct, complementary roles.

---

## 11. Testing and Verification

All backend code, schema definitions, and frontend components were verified using automated tests:

### Automated Test Suite Results
- **MongoDB Infrastructure Tests (`backend/tests/test_mongo_infra.py`):**
  - **8 passed in 0.23s**: Verifies connection options, pool sizing (`maxPoolSize=10`), connect timeouts (2.0s), schema validation models, all 7 index definitions, and graceful degradation during simulated MongoDB outages (returns HTTP 503 instead of crashing).
- **Case Management API Tests (`backend/tests/test_cases.py`):**
  - **16 passed in 3.45s**: Verifies case creation, duplicate `case_id` 409 conflicts, validation rules, status filtering, analyst assignment, atomic `$push` timeline notes, idempotent `$addToSet` finding links, polymorphic evidence attachment, finding escalation, MTTR aggregations, and MongoDB outage recovery.
- **Full Backend Regression Suite (`backend/tests/`):**
  - **40 passed in 3.40s**.
- **Project Unit Tests (`tests/unit/`):**
  - **85 passed in 10.87s**: Verifies Pydantic event contracts, Spark parsing DDL alignment, evaluators, and detectors.
- **Frontend Production Build (`npm run build`):**
  - **TypeScript check (`tsc --noEmit`) and Vite bundling passed cleanly** without errors (`Security-5wTe1Glg.js` compiled to production bundle).

---

## 12. Limitations and Important Operational Notes

1. **Volume Persistence vs. Container Restarts:**
   Data is stored in the Docker named volume `mongo-data`. As long as the volume is preserved (`docker compose down`), cases remain persistent across container restarts. Running `docker compose down -v` will delete the volume and clear all stored cases.
2. **First-Boot Initialization Script:**
   [`infra/mongo/init-mongo.js`](file:///c:/Users/Tapan/Downloads/BigDataPR/infra/mongo/init-mongo.js) executes only when the database is initialized for the first time. If you modify schema rules later, you must either update the collection validator using `collMod` or remove the volume to re-run the initialization script.
3. **Investigation Timeline vs. Cryptographic Tamper-Proof Audit:**
   Our collaborative timeline uses append-only `$push` updates at the application level to preserve an audit trail. While it enforces operational accountability, it is **not** a cryptographically sealed, immutable ledger (like a blockchain or write-once-read-many storage). A database administrator with root credentials could technically modify documents.
4. **Credential Security:**
   Never commit `.env` or hard-code database passwords into Git. Use `.env.example` as a template and provide passwords via environment variables.

---

## 13. Quick Demo Walkthrough (5 Minutes)

Follow this sequence during an evaluation or college presentation:

1. **Step 1: Show Architecture (1 min)**
   Open [`docs/ARCHITECTURE.md`](file:///c:/Users/Tapan/Downloads/BigDataPR/docs/ARCHITECTURE.md). Explain that AgentShield uses **Polyglot Persistence**: Apache Iceberg stores raw analytical telemetry at scale, while MongoDB stores mutable collaborative security cases.
2. **Step 2: Escalate a Finding from the Lakehouse (1 min)**
   - In the browser (`http://localhost:3000`), open **Security & Governance** → **Findings** tab.
   - Point out an `SEC-007` exfiltration finding detected in agent execution.
   - Click the **"Escalate"** button on the row.
   - Show the success banner: *"Finding escalated to MongoDB case CASE-..."*. Click **"View Case →"**.
3. **Step 3: Triage the Case in the UI (1.5 min)**
   - In the **Investigation Cases (MongoDB)** tab, point out the live KPI tiles (Total Open, P1/Critical, Unassigned, MTTR).
   - In the detail drawer, change status from `OPEN` to `IN_REVIEW`.
   - Assign the case to `@sarah.chen`.
   - Under **Analyst Collaboration Timeline**, post a forensic observation: *"Waterfall inspection confirms restricted file read before blocked curl egress."*
   - Show that the timeline appends atomically with the analyst signature and timestamp.
4. **Step 4: Verify Direct Storage in MongoDB (1 min)**
   Switch to PowerShell and run the inspection script:
   ```powershell
   .\.venv\Scripts\python scripts/inspect_mongo.py -v
   ```
   Show the faculty that the document, updated status, and timeline note exist directly inside the `agentshield.security_cases` MongoDB collection.
5. **Step 5: Resolve Remediation (0.5 min)**
   - Click **"Mark Remediation Complete"** in the UI drawer.
   - Show that the case status changes to `RESOLVED`, recording the verification timestamp.
   - Conclude by highlighting the clean separation between immutable big data telemetry and operational incident management.
