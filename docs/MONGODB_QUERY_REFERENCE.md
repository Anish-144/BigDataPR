# AgentShield — MongoDB Unified Query Reference & Faculty Demonstration Guide

> **Official Faculty Viva & Technical Demonstration Reference**  
> **Repository:** AgentShield (Autonomous AI Agent Governance & Big Data Platform)  
> **MongoDB Deployment:** MongoDB 7.0 (WiredTiger Storage Engine)  
> **Primary Collections:** `security_cases` (Operational Incident Management) and `investigation_sessions` (AI Assistant Conversational Memory & Evaluation Store)

---

## Table of Contents

1. [Section A — Polyglot Database Architecture & Rationale](#section-a--polyglot-database-architecture--rationale)
2. [Section B — Existing Feature Reference: `security_cases`](#section-b--existing-feature-reference-security_cases)
3. [Section C — New Feature Reference: `investigation_sessions`](#section-c--new-feature-reference-investigation_sessions)
4. [Section D — Faculty Demonstration Sequence (10-Step Interactive Script)](#section-d--faculty-demonstration-sequence-10-step-interactive-script)
5. [Section E — Comprehensive MongoDB Concept & Operator Mapping](#section-e--comprehensive-mongodb-concept--operator-mapping)
6. [Section F — File-by-File Implementation Reference](#section-f--file-by-file-implementation-reference)
7. [Section G — Presentation Notes & Faculty Viva Defense Q&A](#section-g--presentation-notes--faculty-viva-defense-qa)

---

## Section A — Polyglot Database Architecture & Rationale

### 1. Why AgentShield Employs Polyglot Persistence

In enterprise Big Data architectures, a single database engine cannot optimally support high-throughput analytical scans, transactional state machines, and flexible semi-structured collaboration. AgentShield implements **Polyglot Persistence**, assigning each storage tier to its natural domain:

```text
+---------------------------------------------------------------------------------------------------+
|                                  AGENTSHIELD STORAGE ARCHITECTURE                                 |
+---------------------------------------------------------------------------------------------------+
|  Storage Layer             | Engine                  | Primary Responsibility                     |
|----------------------------+-------------------------+--------------------------------------------|
|  1. Event Streaming        | Apache Kafka            | High-velocity telemetry event ingestion    |
|  2. Stream Processing      | Apache Spark Streaming  | Micro-batch aggregation & anomaly scoring  |
|  3. Analytical Lakehouse   | Apache Iceberg + MinIO  | Immutable historical runs, spans, traces   |
|  4. SQL Query Engine       | Trino                   | High-performance distributed OLAP queries  |
|  5. Relational Store       | PostgreSQL 16           | Iceberg JDBC catalog, Airflow, agent locks |
|  6. Operational Document   | MongoDB 7.0             | Security cases, multi-turn session memory  |
+---------------------------------------------------------------------------------------------------+
```

### 2. Architecture & Data Flow Diagram

```text
   Autonomous AI Agent Fleet (Run Telemetry, Tool Calls, Injected Faults)
                                    │
                                    ▼
                         Apache Kafka (6 topics)
                                    │
                                    ▼
                    Spark Structured Streaming (OLAP Sink)
                                    │
                                    ▼
                     Apache Iceberg Tables (MinIO S3)
                     [runs, spans, evaluations, findings]
                                    │
                                    ▼
                         Trino Distributed SQL
                                    │
                                    ▼
    +───────────────────────────────────────────────────────────────+
    |                     FastAPI Backend Services                  |
    |                                                               |
    |   Relational Coordination             Document Store          |
    |   (PostgreSQL 16)                     (MongoDB 7.0)           |
    |   - Iceberg Catalog                   - security_cases        |
    |   - Airflow DAG metadata              - investigation_sessions|
    |   - Agent Registry & Execution Lock   - Turn Memory & Feedback|
    +───────────────────────────────────────────────────────────────+
                                    │
                                    ▼
                     React 18 Dashboard UI (Vite)
                     - Lakehouse Telemetry & Waterfalls
                     - Operational Case Management
                     - AI Multi-Turn Assistant & Evaluation
```

### 3. Operational NoSQL vs. Large-Scale Analytical Lakehouse

| Dimension | Analytical Lakehouse (Iceberg + Parquet + MinIO) | Operational Document Store (MongoDB 7.0) |
|:---|:---|:---|
| **Primary Data** | Raw trace events, model token counts, latency profiles | Incident cases, collaborative notes, multi-turn assistant turns |
| **Write Pattern** | Append-only bulk Parquet commits via Spark micro-batches | Low-latency, sub-millisecond atomic document updates |
| **Schema Paradigm** | Rigid columnar schema enforced by Iceberg metadata | Polymorphic BSON documents validated via `$jsonSchema` |
| **Mutation Style** | Expensive metadata rewrites (copy-on-write / merge-on-read) | In-place atomic field & array operators (`$set`, `$push`, `$inc`) |
| **Telemetry Policy** | Stores full multi-gigabyte analytical event payloads | Stores lightweight **references** (`finding_id`, `trace_id`) |

### 4. Why Investigation Sessions Belong in MongoDB

Legacy AgentShield stored single-turn investigation Q&A in PostgreSQL as flat text or stringified JSON rows. This approach breaks down for multi-turn AI assistants:
1. **Unbounded Context Chains:** Follow-up questions require reading and appending structured turns (question, answer, evidence links, suggested questions, analyst feedback). Storing this in relational columns requires either complex join cascades across 3 tables or opaque JSON strings that cannot be atomically updated.
2. **Atomic In-Document Updates:** With MongoDB, appending Turn #2 to an ongoing session is a single atomic `$push` and `$inc` operation.
3. **Surgical Evaluation Feedback:** When an analyst marks Turn #1 as `accurate` (Rating: 5) while Turn #2 is flagged as `hallucination` (Rating: 1), MongoDB's `arrayFilters` updates *only* that nested turn element without rewriting the session document.

---

## Section B — Existing Feature Reference: `security_cases`

The `security_cases` collection manages security incidents escalated from Iceberg policy findings or anomaly detector alerts.

### 1. Collection Inspection & Schema Validation

```javascript
// Switch to AgentShield database
use agentshield;

// Inspect collection names
db.getCollectionNames();

// Inspect $jsonSchema validation rules
db.getCollectionInfos({ name: "security_cases" })[0].options.validator;
```
* **Purpose:** Verifies that MongoDB enforces strict document structure at the database engine level.
* **Concept:** MongoDB Schema Validation (`$jsonSchema`).
* **Expected Result:** A BSON validation document requiring `case_id`, `title`, `status`, `severity`, `priority`, and nested `target_agent`.

---

### 2. Escalating an Iceberg Finding into a Security Case (Create)

```javascript
db.security_cases.insertOne({
  case_id: "CASE-202610-0088",
  title: "Synthetic Canary Token Leak detected in summarizer-agent",
  status: "OPEN",
  severity: "critical",
  priority: "P1",
  target_agent: {
    agent_id: "summarizer-agent",
    agent_version: "1.2.0",
    workload_type: "text_summarization",
    model_name: "gpt-4o-mini"
  },
  assigned_analyst: null,
  created_by: "analyst_sec",
  created_at: new Date("2026-10-28T09:15:00Z"),
  updated_at: new Date("2026-10-28T09:15:00Z"),
  resolved_at: null,
  triage_deadline: new Date("2026-10-28T10:15:00Z"),
  resolution_deadline: new Date("2026-10-28T13:15:00Z"),
  linked_findings: [
    {
      finding_id: "FND-992144",
      rule_id: "SEC-POL-003",
      rule_name: "canary_leak_protection",
      severity: "critical",
      trace_id: "4c7a6e1189d248b6b7a91176219800a1",
      span_id: "span_exec_004",
      event_time: "2026-10-28T09:14:52Z"
    }
  ],
  linked_anomaly_alerts: [],
  evidence_bundle: [
    {
      evidence_id: "EVD-001",
      kind: "canary_leak",
      title: "Canary token emitted in response payload",
      detail: "Detected secret canary prefix AS-CANARY-99X in outgoing tool invocation buffer",
      ref: "4c7a6e1189d248b6b7a91176219800a1",
      attached_at: new Date("2026-10-28T09:15:00Z"),
      attached_by: "system_detector"
    }
  ],
  timeline: [
    {
      entry_id: "TL-001",
      timestamp: new Date("2026-10-28T09:15:00Z"),
      author: "system_detector",
      action: "CASE_CREATED",
      notes: "Auto-escalated from Iceberg security finding FND-992144"
    }
  ],
  remediation: {
    recommended_action: "DROP_TOOL_PERMISSIONS",
    policy_file: "config/policies.yaml",
    target_tool: "egress_http",
    requires_code_freeze: true,
    completed: false
  },
  tags: ["canary_leak", "critical_priority", "iceberg_escalated"]
});
```
* **Purpose:** Creates a security case document linking lakehouse findings to an actionable remediation workflow.
* **Concept:** Single document insert (`insertOne`) with embedded polymorphic evidence and timeline arrays.

---

### 3. Case Triage & Analyst Assignment (Atomic Update)

```javascript
db.security_cases.updateOne(
  { case_id: "CASE-202610-0088", status: "OPEN" },
  {
    $set: {
      status: "TRIAGED",
      assigned_analyst: { username: "sarah_chen", email: "sarah.chen@agentshield.corp" },
      updated_at: new Date()
    },
    $push: {
      timeline: {
        entry_id: "TL-002",
        timestamp: new Date(),
        author: "sarah_chen",
        action: "STATUS_CHANGED",
        notes: "Acknowledged incident. Quarantining agent credentials."
      }
    }
  }
);
```
* **Purpose:** Transitions case state and atomically appends an entry to the collaborative timeline in a single transaction.
* **Operators:** `$set` (mutates scalar fields) and `$push` (atomically appends to an array).

---

### 4. Attaching Polymorphic Evidence Item (`$push`)

```javascript
db.security_cases.updateOne(
  { case_id: "CASE-202610-0088" },
  {
    $push: {
      evidence_bundle: {
        evidence_id: "EVD-002",
        kind: "tool_trace",
        title: "Egress Socket Blocked Dump",
        detail: "Raw socket connection blocked with HTTP 403 Forbidden by AgentShield runtime egress guardrail.",
        ref: "span_exec_005",
        metadata: { return_code: 403, bytes_sent: 0 },
        attached_at: new Date(),
        attached_by: "sarah_chen"
      }
    },
    $set: { updated_at: new Date() }
  }
);
```
* **Purpose:** Dynamically appends an additional forensic evidence artifact without altering the schema or restarting any services.
* **Operator:** `$push` (array append), `$set` (timestamp update).

---

### 5. Completing Remediation and Resolving Case (`$set`)

```javascript
db.security_cases.updateOne(
  { case_id: "CASE-202610-0088" },
  {
    $set: {
      status: "RESOLVED",
      resolved_at: new Date(),
      "remediation.completed": true,
      "remediation.completed_at": new Date(),
      "remediation.completed_by": "sarah_chen",
      updated_at: new Date()
    },
    $push: {
      timeline: {
        entry_id: "TL-003",
        timestamp: new Date(),
        author: "sarah_chen",
        action: "REMEDIATION_VERIFIED",
        notes: "Applied tool permission restriction in config/policies.yaml. Regression test re-run passed."
      }
    }
  }
);
```
* **Purpose:** Formally closes the incident lifecycle after remediation verification.
* **Operators:** Nested field `$set` (`remediation.completed`), `$push` (timeline entry).

---

### 6. Finding Cases via Multikey Index (`linked_findings.finding_id` & `trace_id`)

```javascript
// Query 1: Find case by Lakehouse Finding ID
db.security_cases.find({
  "linked_findings.finding_id": "FND-992144"
}, { case_id: 1, title: 1, severity: 1, status: 1 }).pretty();

// Query 2: Find case by Trace ID (Correlating with Lakehouse Trace Waterfall)
db.security_cases.find({
  "linked_findings.trace_id": "4c7a6e1189d248b6b7a91176219800a1"
}).pretty();
```
* **Purpose:** Correlates Lakehouse analytical telemetry with operational incident records without duplicating trace payloads.
* **Concept:** MongoDB Multikey Indexing on array of nested objects.

---

### 7. Full-Text Search across Case Titles and Timeline Notes

```javascript
db.security_cases.find(
  { $text: { $search: "canary leak egress" } },
  { score: { $meta: "textScore" }, case_id: 1, title: 1, severity: 1 }
).sort(
  { score: { $meta: "textScore" } }
).pretty();
```
* **Purpose:** Rapid incident search across titles and free-form analyst investigation notes.
* **Operators:** `$text`, `$search`, and `$meta: "textScore"`.

---

### 8. Aggregation Pipeline 1: Caseload Breakdown by Status

```javascript
db.security_cases.aggregate([
  { $group: { _id: "$status", count: { $sum: 1 } } },
  { $sort: { count: -1 } }
]);
```
* **Purpose:** Real-time caseload distribution across lifecycle phases (`OPEN`, `TRIAGED`, `IN_REVIEW`, `RESOLVED`).
* **Operators:** `$group`, `$sum`, `$sort`.

---

### 9. Aggregation Pipeline 2: Unresolved Cases Grouped by Target AI Agent

```javascript
db.security_cases.aggregate([
  {
    $match: {
      status: { $in: ["OPEN", "TRIAGED", "IN_REVIEW", "REMEDIATION_PENDING"] }
    }
  },
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
* **Purpose:** Identifies which AI agents have the highest count of unresolved security risks.
* **Operators:** `$match`, `$group`, `$cond` (conditional sum), `$project`, `$sort`.

---

### 10. Aggregation Pipeline 3: Mean Time to Remediation (MTTR)

```javascript
db.security_cases.aggregate([
  {
    $match: {
      status: "RESOLVED",
      resolved_at: { $exists: true, $ne: null }
    }
  },
  {
    $project: {
      severity: 1,
      duration_hours: {
        $divide: [
          { $subtract: ["$resolved_at", "$created_at"] },
          3600000 // Convert milliseconds to hours
        ]
      }
    }
  },
  {
    $group: {
      _id: "$severity",
      resolved_cases: { $sum: 1 },
      avg_mttr_hours: { $avg: "$duration_hours" },
      min_hours: { $min: "$duration_hours" },
      max_hours: { $max: "$duration_hours" }
    }
  },
  { $sort: { avg_mttr_hours: 1 } }
]);
```
* **Purpose:** Computes operational security SLA compliance and resolution speed by severity tier.
* **Operators:** `$match`, `$project`, `$subtract`, `$divide`, `$group`, `$avg`, `$min`, `$max`, `$sort`.

---

### 11. Aggregation Pipeline 4: Top Breached Policy Rules Across Cases

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
* **Purpose:** Surfaces the most frequently violated security guardrails across the agent fleet.
* **Operators:** `$unwind` (flattens embedded array), `$group`, `$first`, `$sort`, `$limit`.

---

### 12. Query Performance Profiling with `explain("executionStats")`

```javascript
// Verify that the query uses an Index Scan (IXSCAN) instead of a Collection Scan (COLLSCAN)
db.security_cases.find({ "linked_findings.finding_id": "FND-992144" })
  .explain("executionStats");
```
* **Purpose:** Proves query optimization to faculty by demonstrating `stage: "IXSCAN"` utilizing `idx_multikey_findings_finding_id`.

---

### 13. Case Deletion / Cleanup (Destructive Operations — Labeled)

```javascript
// Delete a specific test case by ID
db.security_cases.deleteOne({ case_id: "CASE-202610-0088" });

// Delete all test cases created by a test runner
db.security_cases.deleteMany({ created_by: "test_analyst" });
```
* **Caution:** These operations permanently delete records; use only with demo or test IDs.

---

## Section C — New Feature Reference: `investigation_sessions`

The `investigation_sessions` collection provides multi-turn memory, grounded evidence links, and evaluation scoring for the AI Investigation Assistant.

### 1. Document Structure & Schema Validation

Every document in `investigation_sessions` conforms to the following BSON structure:

```javascript
{
  "_id": ObjectId("671f..."),
  "session_id": "SES-20261028-4A9B1C",          // Unique indexed identifier
  "title": "Investigation: summarizer-agent (Oct 28)",
  "analyst": "analyst_sec",
  "scope_context": {                            // Scope inherited by all conversation turns
    "test_run_id": "TR-20261028-001",
    "run_id": null,
    "trace_id": "4c7a6e1189d248b6b7a91176219800a1",
    "agent_id": "summarizer-agent",
    "agent_version": "1.2.0",
    "baseline_version": "1.0.0"
  },
  "status": "ACTIVE",                           // ACTIVE | ARCHIVED | CLOSED
  "turn_count": 2,                              // Atomically updated counter
  "turns": [
    {
      "turn_id": 1,
      "question": "Why did latency spike during test run TR-20261028-001?",
      "intent": "latency_investigation",
      "mode": "deterministic",                  // deterministic | llm
      "grounded": true,
      "answer": "P95 latency spiked to 2,840ms due to downstream token retry loops.",
      "evidence": [
        {
          "kind": "trace",
          "ref": "4c7a6e1189d248b6b7a91176219800a1",
          "title": "Downstream retry loop in summarizer span",
          "detail": "Tool timeout occurred at step 3, triggering 4 exponential backoff retries."
        }
      ],
      "suggested_questions": ["What tools timed out?", "Compare error rate against 1.0.0 baseline"],
      "feedback": {                             // Embedded analyst feedback (updated via arrayFilters)
        "rating": 5,
        "verdict": "accurate",
        "notes": "Verified against Iceberg spans table.",
        "submitted_at": ISODate("2026-10-28T09:20:00Z"),
        "submitted_by": "analyst_sec"
      },
      "created_at": ISODate("2026-10-28T09:18:00Z")
    }
  ],
  "tags": ["performance", "summarizer-agent", "latency_regression"],
  "created_at": ISODate("2026-10-28T09:18:00Z"),
  "updated_at": ISODate("2026-10-28T09:20:00Z")
}
```

---

### 2. Creating a Session (`insertOne`)

```javascript
db.investigation_sessions.insertOne({
  session_id: "SES-20261028-4A9B1C",
  title: "Latency Regression in summarizer-agent 1.2.0",
  analyst: "analyst_sec",
  scope_context: {
    test_run_id: "TR-20261028-001",
    run_id: null,
    trace_id: "4c7a6e1189d248b6b7a91176219800a1",
    agent_id: "summarizer-agent",
    agent_version: "1.2.0",
    baseline_version: "1.0.0"
  },
  status: "ACTIVE",
  turn_count: 0,
  turns: [],
  tags: ["latency", "summarizer-agent"],
  created_at: new Date(),
  updated_at: new Date()
});
```
* **Purpose:** Initializes an active session document with scoped telemetry context.
* **Backend Function:** [`create_session`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/app/routers/investigations.py#L499).

---

### 3. Appending a Conversation Turn (`$push`, `$inc`, `$set`)

```javascript
db.investigation_sessions.findOneAndUpdate(
  { session_id: "SES-20261028-4A9B1C", status: "ACTIVE" },
  {
    $push: {
      turns: {
        turn_id: 1,
        question: "Why did latency spike during test run TR-20261028-001?",
        intent: "performance_regression",
        mode: "deterministic",
        grounded: true,
        answer: "P95 latency increased by 1,420ms compared to baseline 1.0.0. The bottleneck originated from 3 consecutive retry attempts on tool `document_parser`.",
        evidence: [
          {
            kind: "trace",
            ref: "4c7a6e1189d248b6b7a91176219800a1",
            title: "Traced execution span for document_parser",
            detail: "HTTP 504 Gateway Timeout observed after 1,000ms threshold."
          }
        ],
        suggested_questions: [
          "Check error rate of document_parser",
          "View security findings for this run"
        ],
        feedback: null,
        created_at: new Date()
      }
    },
    $inc: { turn_count: 1 },
    $set: { updated_at: new Date() }
  },
  { returnDocument: "after" }
);
```
* **Purpose:** Concurrency-safe atomic turn append without rewriting existing conversation history.
* **Operators Demonstrated:**
  - `$push`: Appends the new turn document to the `turns` array.
  - `$inc`: Increments the session turn counter atomically (`turn_count: turn_count + 1`).
  - `$set`: Refreshes the session's `updated_at` timestamp.
* **Backend Function:** [`add_turn`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/app/routers/investigations.py#L585).

---

### 4. Surgical Evaluation Feedback with `arrayFilters`

```javascript
db.investigation_sessions.findOneAndUpdate(
  { session_id: "SES-20261028-4A9B1C", "turns.turn_id": 1 },
  {
    $set: {
      "turns.$[elem].feedback": {
        rating: 5,
        verdict: "accurate",
        notes: "Grounded answer matches traces in Iceberg Lakehouse.",
        submitted_at: new Date(),
        submitted_by: "analyst_sec"
      },
      updated_at: new Date()
    }
  },
  {
    arrayFilters: [{ "elem.turn_id": 1 }],
    returnDocument: "after"
  }
);
```
* **Purpose:** Updates *only* Turn #1's feedback without touching other turns or rewriting the whole array.
* **Key Concept Demonstrated:** **`arrayFilters` (`$[elem]`)**. This allows surgical in-place modification of a specific matched subdocument inside an array.
* **Backend Function:** [`submit_turn_feedback`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/app/routers/investigations.py#L680).

---

### 5. Multi-Faceted Evaluation Analytics Aggregation Pipeline

```javascript
db.investigation_sessions.aggregate([
  {
    $facet: {
      // Branch 1: Evaluation ratings summary
      ratings_summary: [
        { $unwind: "$turns" },
        { $match: { "turns.feedback.rating": { $exists: true, $ne: null } } },
        {
          $group: {
            _id: null,
            avg_rating: { $avg: "$turns.feedback.rating" },
            ratings_count: { $sum: 1 },
            min_rating: { $min: "$turns.feedback.rating" },
            max_rating: { $max: "$turns.feedback.rating" }
          }
        }
      ],
      // Branch 2: Breakdown of analyst verdicts (accurate vs hallucination)
      verdicts_breakdown: [
        { $unwind: "$turns" },
        { $match: { "turns.feedback.verdict": { $exists: true, $ne: null } } },
        { $group: { _id: "$turns.feedback.verdict", count: { $sum: 1 } } },
        { $sort: { count: -1 } }
      ],
      // Branch 3: Generation mode distribution (deterministic vs llm)
      mode_breakdown: [
        { $unwind: "$turns" },
        { $group: { _id: "$turns.mode", count: { $sum: 1 } } }
      ],
      // Branch 4: Groundedness ratio
      groundedness: [
        { $unwind: "$turns" },
        { $group: { _id: "$turns.grounded", count: { $sum: 1 } } }
      ],
      // Branch 5: Top investigated intents
      top_intents: [
        { $unwind: "$turns" },
        { $group: { _id: "$turns.intent", count: { $sum: 1 } } },
        { $sort: { count: -1 } },
        { $limit: 5 }
      ]
    }
  }
]);
```
* **Purpose:** Powers the Investigation Evaluation Dashboard in a single database round-trip.
* **Operators Demonstrated:** `$facet` (parallel aggregation branches), `$unwind` (flattens embedded turn arrays), `$match`, `$group`, `$avg`, `$sum`, `$sort`, `$limit`.
* **Backend Function:** [`session_analytics`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/app/routers/investigations.py#L318).

---

### 6. Session Depth Histogram Pipeline (`$bucket`)

```javascript
db.investigation_sessions.aggregate([
  {
    $bucket: {
      groupBy: "$turn_count",
      boundaries: [0, 2, 5, 10, 20],
      default: "20+",
      output: {
        sessions: { $sum: 1 },
        avg_depth: { $avg: "$turn_count" }
      }
    }
  }
]);
```
* **Purpose:** Analyzes how deeply analysts investigate issues (histogram of turn counts).
* **Concept:** MongoDB Statistical Aggregation (`$bucket`).

---

### 7. Full-Text Search on Session Questions and Answers

```javascript
db.investigation_sessions.find(
  { $text: { $search: "latency timeout" } },
  { score: { $meta: "textScore" }, title: 1, session_id: 1, turn_count: 1 }
).sort(
  { score: { $meta: "textScore" } }
);
```
* **Purpose:** Enables free-text search across session titles, analyst questions, and assistant answers.
* **Index Utilized:** Compound Text Index on `{ title: "text", "turns.question": "text", "turns.answer": "text" }`.

---

## Section D — Faculty Demonstration Sequence (10-Step Interactive Script)

Follow these copy-paste commands during the faculty viva demonstration.

### Step 1: Connect to MongoDB
```bash
# Connect to MongoDB via Docker container
docker exec -it agentshield-mongo mongosh -u agentshield -p agentshield_secret --authenticationDatabase admin agentshield
```

### Step 2: Verify Active Collections
```javascript
// Display all collections in the database
show collections;
// Expected output:
//   investigation_sessions
//   security_cases
```

### Step 3: Inspect Existing Security Cases
```javascript
// Show open security cases escalated from Iceberg lakehouse
db.security_cases.find(
  { status: "OPEN" },
  { case_id: 1, title: 1, severity: 1, priority: 1, "target_agent.agent_id": 1 }
).pretty();
```

### Step 4: Run Existing Case Analytics Aggregation
```javascript
// Aggregate cases by status and severity
db.security_cases.aggregate([
  {
    $group: {
      _id: { status: "$status", severity: "$severity" },
      count: { $sum: 1 }
    }
  },
  { $sort: { "_id.status": 1, count: -1 } }
]);
```

### Step 5: Create a New Investigation Session
```javascript
// Create an investigation session document for an analyst
db.investigation_sessions.insertOne({
  session_id: "SES-DEMO-VIVA01",
  title: "Faculty Demo: Investigating Agent Latency Regression",
  analyst: "faculty_evaluator",
  scope_context: {
    test_run_id: "TR-DEMO-001",
    run_id: null,
    trace_id: "a1b2c3d4e5f60718293a4b5c6d7e8f90",
    agent_id: "qa-assistant",
    agent_version: "2.1.0",
    baseline_version: "2.0.0"
  },
  status: "ACTIVE",
  turn_count: 0,
  turns: [],
  tags: ["viva_demo", "qa-assistant"],
  created_at: new Date(),
  updated_at: new Date()
});
```

### Step 6: Atomically Append Turn #1 with Evidence
```javascript
// Append Turn 1 using $push and $inc
db.investigation_sessions.findOneAndUpdate(
  { session_id: "SES-DEMO-VIVA01" },
  {
    $push: {
      turns: {
        turn_id: 1,
        question: "Why did test run TR-DEMO-001 fail the latency gate?",
        intent: "regression_analysis",
        mode: "deterministic",
        grounded: true,
        answer: "Run TR-DEMO-001 exceeded the P95 latency threshold (2,450ms vs 1,200ms baseline). The cause was database connection pool exhaustion on the embedding retriever.",
        evidence: [
          {
            kind: "trace",
            ref: "a1b2c3d4e5f60718293a4b5c6d7e8f90",
            title: "Retriever connection timeout span",
            detail: "Wait time for free connection was 1,250ms."
          }
        ],
        suggested_questions: ["What was the error rate?", "Which worker failed?"],
        feedback: null,
        created_at: new Date()
      }
    },
    $inc: { turn_count: 1 },
    $set: { updated_at: new Date() }
  },
  { returnDocument: "after" }
);
```

### Step 7: Append Turn #2 (Demonstrating Preserved History)
```javascript
// Append Turn 2 without overwriting Turn 1
db.investigation_sessions.findOneAndUpdate(
  { session_id: "SES-DEMO-VIVA01" },
  {
    $push: {
      turns: {
        turn_id: 2,
        question: "Did any security findings occur during this run?",
        intent: "security_finding_check",
        mode: "deterministic",
        grounded: true,
        answer: "No policy violations or canary leaks occurred during run TR-DEMO-001. All 12 spans adhered to policy SEC-POL-001.",
        evidence: [
          {
            kind: "policy",
            ref: "config/policies.yaml",
            title: "Policy SEC-POL-001 Compliance",
            detail: "Zero disallowed tool calls logged."
          }
        ],
        suggested_questions: ["Check CPU utilization during run"],
        feedback: null,
        created_at: new Date()
      }
    },
    $inc: { turn_count: 1 },
    $set: { updated_at: new Date() }
  },
  { returnDocument: "after" }
);
```

### Step 8: Submit Evaluation Feedback with `arrayFilters`
```javascript
// Rate Turn 1 as accurate (5/5) using arrayFilters
db.investigation_sessions.findOneAndUpdate(
  { session_id: "SES-DEMO-VIVA01", "turns.turn_id": 1 },
  {
    $set: {
      "turns.$[elem].feedback": {
        rating: 5,
        verdict: "accurate",
        notes: "Evidence perfectly matched Iceberg traces.",
        submitted_at: new Date(),
        submitted_by: "faculty_evaluator"
      },
      updated_at: new Date()
    }
  },
  {
    arrayFilters: [{ "elem.turn_id": 1 }],
    returnDocument: "after"
  }
);
```

### Step 9: Run Evaluation Aggregation Pipeline
```javascript
// Show live metrics across all evaluated turns
db.investigation_sessions.aggregate([
  { $unwind: "$turns" },
  { $match: { "turns.feedback.rating": { $exists: true, $ne: null } } },
  {
    $group: {
      _id: "$turns.feedback.verdict",
      avg_score: { $avg: "$turns.feedback.rating" },
      count: { $sum: 1 }
    }
  }
]);
```

### Step 10: Inspect Production Indexes
```javascript
// Display the 8 specialized indexes on investigation_sessions
db.investigation_sessions.getIndexes();
```

---

## Section E — Comprehensive MongoDB Concept & Operator Mapping

| Concept / Operator | Feature | Actual File | Role in AgentShield | Representative Query |
|:---|:---|:---|:---|:---|
| **`$jsonSchema` Validation** | Both | [`backend/app/mongo.py`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/app/mongo.py#L42-L177) | Enforces document integrity at the engine level | `db.createCollection("investigation_sessions", { validator: ... })` |
| **`$set`** | Both | [`backend/app/routers/investigations.py`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/app/routers/investigations.py#L645) | Mutates status and timestamps | `{ $set: { status: "ARCHIVED", updated_at: ISODate() } }` |
| **`$push`** | Both | [`backend/app/routers/investigations.py`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/app/routers/investigations.py#L643) | Appends conversation turns & timeline entries | `{ $push: { turns: turn_doc } }` |
| **`$inc`** | New | [`backend/app/routers/investigations.py`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/app/routers/investigations.py#L644) | Atomic increment of session turn counter | `{ $inc: { turn_count: 1 } }` |
| **`arrayFilters` (`$[elem]`)** | New | [`backend/app/routers/investigations.py`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/app/routers/investigations.py#L703) | Surgical update of a specific nested turn's feedback | `{ $set: { "turns.$[elem].feedback": fb } }, array_filters=[{"elem.turn_id": 1}]` |
| **`$facet`** | New | [`backend/app/routers/investigations.py`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/app/routers/investigations.py#L327) | Multi-branch analytics in a single database round-trip | `{ $facet: { ratings_summary: [...], verdicts: [...] } }` |
| **`$unwind`** | New | [`backend/app/routers/investigations.py`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/app/routers/investigations.py#L330) | Deconstructs embedded turns array for aggregation | `{ $unwind: "$turns" }` |
| **`$bucket`** | New | [`backend/app/routers/investigations.py`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/app/routers/investigations.py#L403) | Computes histogram of session conversation depth | `{ $bucket: { groupBy: "$turn_count", boundaries: [0, 2, 5, 10, 20] } }` |
| **Text Index & Search** | Both | [`backend/app/mongo.py`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/app/mongo.py#L225) | Fast keyword search on questions & answers | `{ $text: { $search: "latency bottleneck" } }` |
| **Multikey Index** | Both | [`backend/app/mongo.py`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/app/mongo.py#L224) | Efficient indexing on array elements (`tags`, `turns.turn_id`) | `col.create_index([("tags", 1)])` |
| **Compound Index** | Both | [`backend/app/mongo.py`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/app/mongo.py#L220) | High-speed filtering by status, analyst, and date | `col.create_index([("status", 1), ("updated_at", -1)])` |

---

## Section F — File-by-File Implementation Reference

### 1. Database Connection & Schema Definition
* **File:** [`backend/app/mongo.py`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/app/mongo.py)
  * `SESSIONS_SCHEMA` (Lines 111–177): BSON validator enforcing required fields (`session_id`, `analyst`, `status`, `turn_count`, `turns`).
  * `SESSIONS_INDEXES` (Lines 216–227): Declares 8 production indexes (unique session ID, compound status/updated_at, analyst filter, test_run filter, trace filter, tags multikey, and text search).
  * `get_sessions_collection()`: Returns a validated handle to `investigation_sessions`.
  * `init_mongo()`: Idempotently creates collections and builds indexes.
  * `check_mongo_health()`: Diagnostic probe returning document counts and connection ping.

### 2. Database Bootstrap Scripts
* **File:** [`infra/mongo/init-mongo.js`](file:///c:/Users/Tapan/Downloads/BigDataPR/infra/mongo/init-mongo.js)
  * Contains automated JavaScript bootstrap commands executed when the Docker container initializes, registering both `security_cases` and `investigation_sessions`.

### 3. Backend Router & API Endpoints
* **File:** [`backend/app/routers/investigations.py`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/app/routers/investigations.py)
  * `POST /api/v1/investigations/sessions`: [`create_session`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/app/routers/investigations.py#L499)
  * `GET /api/v1/investigations/sessions`: [`list_sessions`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/app/routers/investigations.py#L234)
  * `GET /api/v1/investigations/sessions/{session_id}`: [`get_session`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/app/routers/investigations.py#L567)
  * `POST /api/v1/investigations/sessions/{session_id}/turns`: [`add_turn`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/app/routers/investigations.py#L585)
  * `PATCH /api/v1/investigations/sessions/{session_id}/turns/{turn_id}/feedback`: [`submit_turn_feedback`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/app/routers/investigations.py#L680)
  * `GET /api/v1/investigations/sessions/summary/analytics`: [`session_analytics`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/app/routers/investigations.py#L318)
  * `PATCH /api/v1/investigations/sessions/{session_id}`: [`update_session`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/app/routers/investigations.py#L734)
  * `DELETE /api/v1/investigations/sessions/{session_id}`: [`delete_session`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/app/routers/investigations.py#L768)

### 4. Frontend Integration
* **File:** [`frontend/src/api/types.ts`](file:///c:/Users/Tapan/Downloads/BigDataPR/frontend/src/api/types.ts)
  * Defines TypeScript interfaces: `InvestigationSession`, `InvestigationTurn`, `TurnFeedback`, `SessionAnalytics`, `PagedSessions`.
* **File:** [`frontend/src/api/hooks.ts`](file:///c:/Users/Tapan/Downloads/BigDataPR/frontend/src/api/hooks.ts)
  * Provides TanStack React Query hooks: `useInvestigationSessions`, `useInvestigationSession`, `useSessionAnalytics`, `useCreateSession`, `useAddSessionTurn`, `useSubmitTurnFeedback`, `useUpdateSession`.
* **File:** [`frontend/src/pages/Assistant.tsx`](file:///c:/Users/Tapan/Downloads/BigDataPR/frontend/src/pages/Assistant.tsx)
  * Upgrades the assistant UI with session switching, conversation history viewer, interactive star rating and verdict submitter, and live evaluation analytics.

### 5. Automated Test Suites
* **File:** [`backend/tests/test_investigation_sessions.py`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/tests/test_investigation_sessions.py)
  * 11 comprehensive tests verifying session lifecycle, atomic turn append, surgical feedback update with `arrayFilters`, isolation between sessions, and aggregation analytics.
* **File:** [`backend/tests/test_mongo_infra.py`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/tests/test_mongo_infra.py)
  * Verifies MongoDB connection, ping, collection presence, and index definitions.
* **File:** [`backend/tests/test_cases.py`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/tests/test_cases.py)
  * 16 tests verifying the existing security cases feature.

### 6. Safe Migration Utility
* **File:** [`scripts/migrate_investigations_to_mongo.py`](file:///c:/Users/Tapan/Downloads/BigDataPR/scripts/migrate_investigations_to_mongo.py)
  * Reads legacy single-turn rows from PostgreSQL `investigations` and idempotently transforms them into MongoDB session documents.

---

## Section G — Presentation Notes & Faculty Viva Defense Q&A

### 1. 60-Second Elevator Pitch to Faculty
> *"In AgentShield, we engineered a Polyglot Persistence tier. While Apache Iceberg on MinIO stores gigabytes of immutable telemetry and Kafka streams events, our operations require low-latency document mutations. We use MongoDB 7.0 for two distinct workloads: first, for operational security cases where analysts attach polymorphic evidence and track remediation; and second, for our new AI Investigation Assistant Session Memory & Evaluation Store. This allows analysts to conduct multi-turn investigations with preserved conversational context, link back to Iceberg traces without duplicating telemetry, rate assistant answers using surgical `arrayFilters` updates, and aggregate model groundedness using MongoDB `$facet` pipelines."*

### 2. Likely Faculty Viva Questions & Model Answers

#### Q1: "Why did you use MongoDB instead of creating a new PostgreSQL table with a JSONB column?"
**Answer:**  
PostgreSQL `JSONB` can store semi-structured data, but MongoDB was selected for four engineering reasons:
1. **Atomic Array Manipulation:** Modifying an element inside a nested JSONB array requires reading the whole document, modifying the client-side copy, and writing back the entire JSON string. In MongoDB, operators like `$push`, `$inc`, and `arrayFilters` perform in-place, atomic modifications at the storage engine level without document rewrites.
2. **Workload Isolation:** AI assistant conversations and incident tracking have high mutation velocity that would pollute PostgreSQL's buffer pool and write-ahead log (WAL), potentially starving the Iceberg JDBC catalog and Airflow scheduler.
3. **Complex Aggregation Pipelines:** MongoDB's Aggregation Framework provides `$facet`, `$bucket`, and `$unwind` natively, allowing multi-branch statistical summaries (ratings, verdicts, depth histograms) in a single database round-trip.
4. **Natural Document Model:** Investigation sessions are document-native: an analyst's session contains an ordered list of turns, each with polymorphic evidence arrays.

#### Q2: "Does MongoDB duplicate the raw telemetry data that already lives in Iceberg?"
**Answer:**  
**No.** We strictly enforce the principle of **Reference over Duplication**. MongoDB documents store only lightweight reference identifiers (`trace_id`, `span_id`, `run_id`, `rule_id`). When an analyst inspects evidence in the UI, the frontend resolves the reference into a direct hyperlink back to the Lakehouse Trace Explorer (`/app/runs/{trace_id}`). The analytical lakehouse remains the single source of truth for raw telemetry.

#### Q3: "What happens if a conversation has hundreds of turns? Will you hit MongoDB's 16MB document size limit?"
**Answer:**  
Our document schema enforces defensive sizing:
1. **Turn Limit Enforcement:** The backend router restricts sessions to a maximum of 50 turns. If a session hits 50 turns, the API instructs the analyst to archive the session and start a continuation session.
2. **Lean Turn Payloads:** Telemetry payloads are kept out of turns (only evidence references are stored). A typical turn averages ~1.5 KB. Even a full 50-turn session consumes less than 100 KB, which is well below MongoDB's 16 MB BSON document limit.

#### Q4: "How do you handle schema evolution in MongoDB?"
**Answer:**  
We use MongoDB `$jsonSchema` validation with `validationAction: "warn"` or `"error"`. When expanding fields (e.g. adding `suggested_questions` or `feedback.notes`), BSON documents natively allow optional fields without requiring table migration locks.

---

### 3. Safe Live Demo Operations vs. Test Operations

| Operation | Safe Live Demo? | Notes |
|:---|:---|:---|
| `db.investigation_sessions.find()` | **YES (Safe)** | Read-only; can be executed repeatedly |
| `db.investigation_sessions.aggregate()` | **YES (Safe)** | Read-only statistical summary |
| `db.investigation_sessions.getIndexes()` | **YES (Safe)** | Read-only index inspection |
| `insertOne` with `SES-DEMO-...` | **YES (Safe)** | Inserts isolated test document; easily deleted via session ID |
| `findOneAndUpdate` with `arrayFilters` | **YES (Safe)** | Modifies only the demo session created in Step 5 |
| `db.investigation_sessions.drop()` | **NO (Destructive)** | **Do not run during presentation.** Deletes all collection data. |
| `db.security_cases.deleteMany({})` | **NO (Destructive)** | **Do not run during presentation.** Deletes operational cases. |
