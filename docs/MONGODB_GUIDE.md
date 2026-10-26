# AgentShield — MongoDB Practical Guide & Presentation Handbook

A comprehensive, beginner-friendly operational guide for inspecting, querying, and presenting MongoDB in the **AgentShield Big Data Platform**.

---

## 1. Architecture & Storage Overview

### 1.1 The Polyglot Persistence Architecture
AgentShield processes high-volume telemetry from deterministic AI agent workloads. Different data shapes and access patterns require specialized storage engines:

```
[Agent Workload Telemetry]
           │
           ▼
     Apache Kafka (6 Topics)
           │
           ▼
 Apache Spark Structured Streaming
           │
     ┌─────┴────────────────────────┐
     ▼                              ▼
Apache Iceberg (MinIO)       MongoDB 7.0 (Doc Store)
- Parquet format             - Mutable Security Cases
- Immutable OLAP facts       - Polymorphic Evidence
- Spans, Traces, Metrics     - Collaborative Timelines
- Trino SQL Analytics        - Remediation Action Plans
     │                              │
     └──────────────┬───────────────┘
                    ▼
          FastAPI & React Workbench
```

| Engine | Storage Medium | Primary Role in AgentShield | Mutation Characteristic |
|---|---|---|---|
| **Apache Iceberg** | Parquet on MinIO (S3) | Analytical telemetry lakehouse (runs, spans, evals, raw findings) | Immutable, append-only, batch-compacted |
| **PostgreSQL 16** | Local disk | Iceberg JDBC catalog, test-run queue, Airflow metadata | ACID relational tables |
| **MongoDB 7.0** | WiredTiger on Docker volume | Operational security findings, incident investigation cases, collaborative analyst notes, and remediation tracking | Mutable documents, atomic `$push` arrays, polymorphic sub-documents |

### 1.2 Physical Storage & Memory Budget
- **Docker Service**: `mongodb` (`image: mongo:7.0-jammy`)
- **Named Volume**: `mongo-data` mounted at `/data/db` inside the container.
- **Port Mapping**: Host port `27017` mapped to container `27017`.
- **Single-Machine Resource Budget**:
  - Container RAM limit: `mem_limit: 512m`
  - WiredTiger Cache limit: `--wiredTigerCacheSizeGB 0.25` (256 MB)
  - This ensures MongoDB runs reliably alongside Kafka, Spark, and Trino on a single 16 GB laptop without memory thrashing.

---

## 2. Repository Files, Schema Validation & Indexes

### 2.1 File Map
| File | Role |
|---|---|
| [`infra/mongo/init-mongo.js`](file:///c:/Users/Tapan/Downloads/BigDataPR/infra/mongo/init-mongo.js) | Container startup script: creates `agentshield` database, `$jsonSchema` validation, and 7 indexes. |
| [`backend/app/mongo.py`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/app/mongo.py) | Python PyMongo connection manager: connection pooling (`maxPoolSize=10`), health check, and graceful degradation. |
| [`backend/app/routers/cases.py`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/app/routers/cases.py) | FastAPI router: implements `/api/v1/cases` CRUD, finding escalation, and aggregation pipelines. |
| [`scripts/inspect_mongo.py`](file:///c:/Users/Tapan/Downloads/BigDataPR/scripts/inspect_mongo.py) | Host CLI tool for inspecting MongoDB document counts, table listings, and full JSON payloads. |
| [`docker-compose.yml`](file:///c:/Users/Tapan/Downloads/BigDataPR/docker-compose.yml) | Docker Compose specification for `mongodb` container service and dependencies. |
| [`.env.example`](file:///c:/Users/Tapan/Downloads/BigDataPR/.env.example) | Template for connection environment variables. |

### 2.2 Collection Schema & JSON Schema Validation
All operational incident cases live in the `security_cases` collection under database `agentshield`.

MongoDB enforces validation on every write via `$jsonSchema`:
- **Required Fields**: `case_id`, `title`, `status`, `severity`, `target_agent`, `created_at`.
- **`case_id` Format**: Regex pattern `^CASE-[0-9]{6}-[0-9a-fA-F]{4,8}$` (e.g. `CASE-202610-0042`).
- **Enums**:
  - `status`: `["OPEN", "TRIAGED", "IN_REVIEW", "REMEDIATION_PENDING", "RESOLVED", "DISMISSED"]`
  - `severity`: `["low", "medium", "high", "critical"]`
  - `priority`: `["P1", "P2", "P3", "P4"]`
- **Embedded Structures**:
  - `target_agent`: `{ agent_id, agent_version, workload_type, model_name }`
  - `linked_findings`: Array of `{ finding_id, rule_id, rule_name, severity, trace_id, span_id, event_time }`
  - `evidence_bundle`: Array of `{ evidence_id, kind, title, detail, ref, metadata }`
  - `timeline`: Array of `{ timestamp, author, action, notes }`
  - `remediation`: `{ recommended_action, policy_file, target_tool, completed, completed_at, completed_by }`

### 2.3 Indexes
| Index Name | Key Definition | Purpose |
|---|---|---|
| `idx_case_id_unique` | `{ case_id: 1 }` (unique) | Guarantees uniqueness of case IDs and O(1) lookup. |
| `idx_cases_triage_sla` | `{ status: 1, severity: 1, priority: 1, created_at: -1 }` | Compound index for triage queues and SLA sorting. |
| `idx_cases_target_agent` | `{ "target_agent.agent_id": 1, "target_agent.agent_version": 1 }` | Fast filtering by affected AI agent and version. |
| `idx_multikey_findings_finding_id` | `{ "linked_findings.finding_id": 1 }` | Multikey index: connects lakehouse security findings to open cases. |
| `idx_multikey_findings_trace_id` | `{ "linked_findings.trace_id": 1 }` | Multikey index: correlates Lakehouse trace waterfall with investigation cases. |
| `idx_multikey_alerts_alert_id` | `{ "linked_anomaly_alerts.alert_id": 1 }` | Multikey index: links ML anomaly alerts to cases. |
| `idx_text_title_notes` | `{ title: "text", "timeline.notes": "text" }` | Full-text search across titles and collaborative notes. |

---

## 3. How to Connect to MongoDB

### Option A: Interactive Docker Shell (`mongosh`)
Run this in PowerShell or terminal when Docker is running:
```bash
docker exec -it agentshield-mongodb mongosh -u agentshield -p agentshield-mongo-secret --authenticationDatabase admin agentshield
```

> [!NOTE]
> All `mongosh` commands below are intended to be run inside the `mongosh` prompt (`agentshield>`).

### Option B: Host Python Inspection Script
If you prefer running from the project root on the host machine:
```bash
# Print summary table and total document counts
.\.venv\Scripts\python scripts/inspect_mongo.py

# Print the most recent case in full JSON format
.\.venv\Scripts\python scripts/inspect_mongo.py -v

# Inspect a specific case document
.\.venv\Scripts\python scripts/inspect_mongo.py --case-id CASE-202610-0042
```

---

## 4. Ready-to-Run `mongosh` Queries

### 4.1 Viewing & Counting Data

#### Count all documents in the collection
```javascript
db.security_cases.countDocuments();
```

#### View summary list of all cases (projection of key fields)
```javascript
db.security_cases.find(
  {},
  {
    case_id: 1,
    title: 1,
    status: 1,
    severity: 1,
    priority: 1,
    "target_agent.agent_id": 1,
    "assigned_analyst.username": 1,
    updated_at: 1
  }
).sort({ created_at: -1 }).pretty();
```

#### Find a single case by its unique business ID
```javascript
db.security_cases.findOne({ case_id: "CASE-202610-0042" });
```

---

### 4.2 Filtering & Querying

#### Filter active P1 / Critical cases
```javascript
db.security_cases.find({
  status: { $in: ["OPEN", "TRIAGED", "IN_REVIEW"] },
  $or: [{ severity: "critical" }, { priority: "P1" }]
}, { case_id: 1, title: 1, severity: 1, priority: 1, status: 1 }).pretty();
```

#### Filter cases affecting a specific AI agent
```javascript
db.security_cases.find({
  "target_agent.agent_id": "ops-tool-agent",
  status: { $ne: "RESOLVED" }
}).pretty();
```

#### Find cases linking a specific Lakehouse finding (Multikey Index Query)
```javascript
db.security_cases.find({
  "linked_findings.finding_id": "SEC-F-5555"
}).pretty();
```

#### Find cases linking an execution trace ID
```javascript
db.security_cases.find({
  "linked_findings.trace_id": "0192a7f3b89c71e2a0b3c4d5e6f70819"
}).pretty();
```

#### Full-Text Search across case titles and timeline notes
```javascript
db.security_cases.find(
  { $text: { $search: "exfiltration canary" } },
  { score: { $meta: "textScore" }, case_id: 1, title: 1 }
).sort({ score: { $meta: "textScore" } }).pretty();
```

---

### 4.3 Inserting Sample Data

#### Insert a new investigation case (conforms to schema validation)
```javascript
db.security_cases.insertOne({
  case_id: "CASE-202610-0042",
  title: "Exfiltration sequence detected via curl_egress",
  status: "OPEN",
  severity: "critical",
  priority: "P1",
  target_agent: {
    agent_id: "ops-tool-agent",
    agent_version: "1.1.0",
    workload_type: "tool",
    model_name: "claude-3-5-sonnet"
  },
  assigned_analyst: null,
  linked_findings: [
    {
      finding_id: "SEC-F-5555",
      rule_id: "SEC-007",
      rule_name: "exfiltration_sequence",
      severity: "critical",
      trace_id: "0192a7f3b89c71e2a0b3c4d5e6f70819",
      span_id: "7f3a9c1e2b4d5a6b",
      event_time: new Date()
    }
  ],
  linked_anomaly_alerts: [],
  evidence_bundle: [
    {
      evidence_id: "EV-202610-0001",
      kind: "canary_leak",
      title: "Synthetic Canary Token in Egress Payload",
      detail: "Token AGSH-CANARY-5F1E present in buffer",
      ref: "span:7f3a9c1e2b4d5a6b",
      metadata: { bytes_matched: 18 }
    }
  ],
  timeline: [
    {
      timestamp: new Date(),
      author: "triage_bot",
      action: "ESCALATED_FROM_FINDING",
      notes: "Escalated automatically from finding SEC-F-5555"
    }
  ],
  remediation: {
    recommended_action: "DROP_TOOL_PERMISSIONS",
    policy_file: "config/policies.yaml",
    target_tool: "curl_egress",
    requires_code_freeze: false,
    completed: false,
    completed_at: null,
    completed_by: null
  },
  tags: ["exfiltration", "p1-blocker", "tool-abuse"],
  created_at: new Date(),
  updated_at: new Date()
});
```

---

### 4.4 Updating & Collaborative Workflows

#### 1. Transition Status and Assign Analyst
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

#### 2. Atomically Push a Collaborative Note to the Timeline (`$push`)
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

#### 3. Attach a Polymorphic Evidence Item (`$push`)
```javascript
db.security_cases.updateOne(
  { case_id: "CASE-202610-0042" },
  {
    $push: {
      evidence_bundle: {
        evidence_id: "EV-202610-0002",
        kind: "tool_trace",
        title: "Egress Socket Dump",
        detail: "Socket send blocked with HTTP 403 Forbidden.",
        ref: "span:7f3a9c1e2b4d5a6b",
        metadata: { return_code: 403 }
      }
    },
    $set: { updated_at: new Date() }
  }
);
```

#### 4. Complete Remediation and Resolve Case
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

---

### 4.5 Aggregation Pipelines (Live Operational Analytics)

#### Pipeline 1: Caseload Breakdown by Status
```javascript
db.security_cases.aggregate([
  { $group: { _id: "$status", count: { $sum: 1 } } },
  { $sort: { count: -1 } }
]);
```

#### Pipeline 2: Unresolved Cases Grouped by Target AI Agent
```javascript
db.security_cases.aggregate([
  { $match: { status: { $in: ["OPEN", "TRIAGED", "IN_REVIEW", "REMEDIATION_PENDING"] } } },
  {
    $group: {
      _id: {
        agent_id: "$target_agent.agent_id",
        agent_version: "$target_agent.agent_version"
      },
      unresolved_cases: { $sum: 1 },
      critical_cases: {
        $sum: { $cond: [{ $eq: ["$severity", "critical"] }, 1, 0] }
      }
    }
  },
  {
    $project: {
      agent_id: "$_id.agent_id",
      agent_version: "$_id.agent_version",
      unresolved_cases: 1,
      critical_cases: 1,
      _id: 0
    }
  },
  { $sort: { critical_cases: -1, unresolved_cases: -1 } }
]);
```

#### Pipeline 3: Mean Time to Remediation (MTTR) in Hours
Calculates the average duration from creation to resolution for resolved cases:
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

#### Pipeline 4: Most Frequently Breached Policy Rules Across Cases
```javascript
db.security_cases.aggregate([
  { $unwind: "$linked_findings" },
  {
    $group: {
      _id: "$linked_findings.rule_id",
      rule_name: { $first: "$linked_findings.rule_name" },
      breach_count: { $sum: 1 }
    }
  },
  { $sort: { breach_count: -1 } },
  { $limit: 5 }
]);
```

---

### 4.6 Destructive Operations (Marked)

> [!CAUTION]
> The following operations delete records permanently. Only use with test IDs during testing/demonstrations.

#### Delete a single test case
```javascript
db.security_cases.deleteOne({ case_id: "CASE-202610-0042" });
```

#### Delete all test cases created by a test analyst
```javascript
db.security_cases.deleteMany({ created_by: "test_analyst" });
```

#### Drop collection (Full Reset)
```javascript
// WARNING: Drops collection, schema validator, and all 7 indexes!
db.security_cases.drop();
```

---

## 5. Index Inspection & Performance Troubleshooting

### 5.1 Inspect Collection Indexes
```javascript
db.security_cases.getIndexes();
```

### 5.2 Measure Query Performance with `explain("executionStats")`
Verify that MongoDB uses an **Index Scan (`IXSCAN`)** rather than a **Collection Scan (`COLLSCAN`)**:

```javascript
db.security_cases.find({ "linked_findings.finding_id": "SEC-F-5555" })
  .explain("executionStats");
```
**What to look for in output**:
- `stage: "IXSCAN"`: Indicates the query used `idx_multikey_findings_finding_id`.
- `totalDocsExamined`: Should match the number of returned documents, not the total collection count.

### 5.3 Database Stats & Storage
```javascript
// Storage stats for security_cases
db.security_cases.stats();

// Server memory and connection stats
db.serverStatus().wiredTiger.cache;
```

### 5.4 Common Troubleshooting Scenarios

| Issue | Cause | Fix |
|---|---|---|
| `Document failed validation` | Write violation of `$jsonSchema` (e.g. invalid status enum or missing `case_id` pattern). | Ensure `case_id` matches `^CASE-[0-9]{6}-[0-9a-fA-F]{4,8}$` and `status` is one of the 6 allowed enums. |
| `E11000 duplicate key error` | Duplicate `case_id` violating unique index `idx_case_id_unique`. | Use a fresh case ID or allow the backend `_gen_case_id()` to generate a unique ID. |
| `MongoNetworkError / Connection refused` | Container stopped or port `27017` not bound. | Run `docker compose up -d mongodb` and verify with `docker ps`. |
| Out of memory / container killed | Exceeded 512 MB memory limit. | WiredTiger cache is capped at `0.25GB` (`docker-compose.yml`). Avoid unbounded aggregations without `$limit`. |

---

## 6. Faculty Viva Questions & Answers

### Q1: Why introduce MongoDB when AgentShield already has Apache Iceberg and PostgreSQL?
**Answer:** This demonstrates **Polyglot Persistence**. Iceberg on MinIO is an OLAP engine optimized for high-throughput, immutable append of millions of analytical telemetry events (spans, evals, metrics). It cannot perform sub-millisecond, low-latency row mutations. PostgreSQL manages relational catalog and orchestration state. MongoDB provides a document store for **rapidly mutating, collaborative incident records** where schema flexibility is needed for polymorphic evidence bundles and atomic timeline appends.

### Q2: Why apply schema validation (`$jsonSchema`) in a NoSQL database?
**Answer:** In operational cybersecurity, unregulated schemaless writes lead to data corruption (e.g. invalid status codes or missing audit timestamps). MongoDB's `$jsonSchema` combines the benefits of document flexibility (polymorphic arrays of evidence and notes) with strict schema governance on mission-critical fields (`case_id`, `status`, `target_agent`).

### Q3: What is a Multikey Index and where is it used?
**Answer:** A multikey index indexes elements inside an array. In AgentShield, `linked_findings` is an array of objects inside each case document. We index `linked_findings.finding_id` and `linked_findings.trace_id`. When an engineer views a trace in the lakehouse, this index allows an instant $O(\log N)$ lookup to determine if the trace is already part of an active security investigation case.

### Q4: How does MongoDB prevent race conditions when multiple analysts annotate a case?
**Answer:** MongoDB document writes are atomic at the document level. By using the `$push` operator on the `timeline` and `evidence_bundle` arrays, multiple analysts can post forensic notes concurrently without overwriting each other's updates, eliminating the need for complex distributed locking.

### Q5: How is Mean Time to Remediation (MTTR) calculated?
**Answer:** Via a MongoDB aggregation pipeline matching cases with `status: "RESOLVED"` and `remediation.completed: true`. It subtracts `created_at` from `updated_at`, divides by `3,600,000` to convert milliseconds to hours, and computes the `$avg` grouped by case severity.

---

## 7. 5–7 Minute Presentation Demo Script

### Minute 0–1: Problem Statement & Architecture Diagram
- Show the architecture diagram from [`docs/ARCHITECTURE.md`](file:///c:/Users/Tapan/Downloads/BigDataPR/docs/ARCHITECTURE.md).
- Explain: *"When our streaming detectors flag a security breach or canary leak in Iceberg, analysts need a mutable workspace to collaborate, attach forensic artifacts, and track policy remediation. That's why we added MongoDB."*

### Minute 1–2: Live Escalation from the Dashboard
- Open the Dashboard at `http://localhost:3000`.
- Navigate to **Security & Governance** → **Findings** tab.
- Click **"Escalate"** on an `SEC-007` finding.
- Show the confirmation notification: *"Finding escalated to MongoDB case CASE-..."*.
- Click **"View Case →"**.

### Minute 2–4: Operational Case Management & Triage
- Show the **Investigation Cases (MongoDB)** tab:
  - Highlight the 5 live KPI tiles: Total Open, P1/Critical, Unassigned, SLA Breached, and MTTR.
  - Open the newly created case in the detail drawer.
  - Change status from `OPEN` to `IN_REVIEW`.
  - Assign the case to `@sarah.chen`.
  - In **Collaborative Timeline**, post a note: *"Trace inspection confirms restricted file read before blocked curl egress."*
  - Show the atomic timeline update.

### Minute 4–5: Direct MongoDB Shell Inspection
- Switch to terminal and run the inspection script:
  ```bash
  .\.venv\Scripts\python scripts/inspect_mongo.py -v
  ```
- Point out the newly created case, status, and timeline entry stored directly in MongoDB.

### Minute 5–7: Aggregation & Remediation Resolution
- In the detail drawer, click **"Mark Remediation Complete"**.
- Explain that the case transitions to `RESOLVED` and updates `remediation.completed_at`.
- Run the MTTR aggregation in `mongosh` or show the updated MTTR tile on screen.
- Conclude: *"Iceberg stores analytical telemetry at big data scale; MongoDB handles human-in-the-loop governance and remediation."*
