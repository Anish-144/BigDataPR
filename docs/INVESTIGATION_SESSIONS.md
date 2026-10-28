# AgentShield — AI Assistant Multi-Turn Session Memory & Evaluation Store (`INVESTIGATION_SESSIONS.md`)

> **Feature Specification & Engineering Documentation**  
> **Collection:** `investigation_sessions` in MongoDB 7.0  
> **Status:** Fully Implemented, Tested, and Integrated with FastAPI & React  
> **Primary Reference:** See [`docs/MONGODB_QUERY_REFERENCE.md`](file:///c:/Users/Tapan/Downloads/BigDataPR/docs/MONGODB_QUERY_REFERENCE.md) for live faculty demonstration queries.

---

## 1. Executive Summary

The **AI Assistant Multi-Turn Session Memory & Evaluation Store** introduces stateful, multi-turn conversational investigations into AgentShield. 

Before this implementation, the Investigation Assistant was stateless or recorded isolated Q&A turns in the PostgreSQL `investigations` table as flat relational rows. Analysts could not conduct ongoing multi-turn troubleshooting sessions, evaluate assistant answer quality across a dialogue, or preserve contextual references to lakehouse telemetry.

This feature establishes a dedicated MongoDB collection—`investigation_sessions`—that stores complete conversation histories, structured evidence links, analyst evaluation ratings (1–5 stars), and verdict classifications (`accurate`, `hallucination`, `incomplete`, `irrelevant`, `misleading`).

---

## 2. Polyglot Architecture & Scope Boundaries

### Polyglot Responsibilities

```text
+-----------------------+-------------------------------------------------------------+
| System Component      | Architectural Responsibility                                |
+-----------------------+-------------------------------------------------------------+
| PostgreSQL 16         | Iceberg JDBC Catalog, Airflow metadata, agent registry &    |
|                       | test-run execution lock (ACID consistency).                 |
+-----------------------+-------------------------------------------------------------+
| Apache Iceberg (MinIO)| Immutable telemetry lakehouse (runs, spans, traces, policy  |
|                       | findings). Single source of truth for telemetry facts.      |
+-----------------------+-------------------------------------------------------------+
| MongoDB 7.0           | Operational security cases (`security_cases`) and multi-turn|
|                       | assistant investigation sessions (`investigation_sessions`).|
+-----------------------+-------------------------------------------------------------+
```

### Telemetry Referencing Rule (Zero Duplication)
To avoid replicating multi-gigabyte trace payloads from Iceberg into MongoDB:
- **Iceberg** stores full spans, error logs, and metrics.
- **MongoDB** stores lightweight evidence descriptors (`trace_id`, `span_id`, `ref`, `kind`).
- **React UI** resolves references into direct links to `/runs/{trace_id}`.

---

## 3. MongoDB Schema & Document Structure

### Collection: `investigation_sessions`

```json
{
  "_id": "ObjectId('...')",
  "session_id": "SES-20261028-4A9B1C",
  "title": "Investigation: summarizer-agent (Oct 28)",
  "analyst": "analyst_sec",
  "scope_context": {
    "test_run_id": "TR-20261028-001",
    "run_id": null,
    "trace_id": "4c7a6e1189d248b6b7a91176219800a1",
    "agent_id": "summarizer-agent",
    "agent_version": "1.2.0",
    "baseline_version": "1.0.0"
  },
  "status": "ACTIVE",
  "turn_count": 1,
  "turns": [
    {
      "turn_id": 1,
      "question": "Why did latency spike during test run TR-20261028-001?",
      "intent": "latency_investigation",
      "mode": "deterministic",
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
      "suggested_questions": ["What tools timed out?"],
      "feedback": {
        "rating": 5,
        "verdict": "accurate",
        "notes": "Verified against Iceberg spans table.",
        "submitted_at": "2026-10-28T09:20:00Z",
        "submitted_by": "analyst_sec"
      },
      "created_at": "2026-10-28T09:18:00Z"
    }
  ],
  "tags": ["performance", "summarizer-agent"],
  "created_at": "2026-10-28T09:18:00Z",
  "updated_at": "2026-10-28T09:20:00Z"
}
```

### Document-Size Defenses
1. **Turn Cap:** Maximum 50 turns per session enforced by backend validation.
2. **Lean Payloads:** Average turn size is ~1.5 KB; a full 50-turn session consumes < 100 KB (well within MongoDB's 16 MB limit).

---

## 4. Production Indexing Strategy

The collection is provisioned with 8 specialized indexes:

| Index Name | Specification | Query Pattern Supported |
|:---|:---|:---|
| `uniq_session_id` | `{ session_id: 1 }` (unique) | O(1) point lookup by session ID |
| `idx_sess_status_updated` | `{ status: 1, updated_at: -1 }` | Fast sorting of active/archived sessions |
| `idx_sess_analyst_created` | `{ analyst: 1, created_at: -1 }` | Sessions assigned to specific analyst |
| `idx_sess_test_run` | `{ "scope_context.test_run_id": 1 }` | Sessions linked to a specific test run |
| `idx_sess_trace` | `{ "scope_context.trace_id": 1 }` | Sessions investigating a specific trace |
| `idx_sess_agent` | `{ "scope_context.agent_id": 1, "scope_context.agent_version": 1 }` | Filter sessions by investigated agent |
| `idx_sess_tags` | `{ tags: 1 }` (multikey) | Tag-based classification filtering |
| `idx_sess_text` | `{ title: "text", "turns.question": "text", "turns.answer": "text" }` | Full-text keyword search across investigations |

---

## 5. REST API Endpoints

All endpoints are hosted under `/api/v1/investigations`:

| Method | Endpoint | Description | Key MongoDB Operation |
|:---|:---|:---|:---|
| `POST` | `/sessions` | Create a new session (with optional Turn 1) | `insertOne` |
| `GET` | `/sessions` | List, search, filter, and paginate sessions | `find().sort().skip().limit()` |
| `GET` | `/sessions/{id}` | Retrieve session with full turn history | `findOne({ session_id })` |
| `POST` | `/sessions/{id}/turns` | Append a new conversation turn atomically | `findOneAndUpdate` with `$push`, `$inc`, `$set` |
| `PATCH` | `/sessions/{id}/turns/{turn_id}/feedback` | Submit analyst rating and verdict | `findOneAndUpdate` with `arrayFilters` |
| `GET` | `/sessions/summary/analytics` | Aggregated evaluation & depth metrics | `$facet`, `$unwind`, `$group`, `$bucket` |
| `PATCH` | `/sessions/{id}` | Update session title, status, or tags | `findOneAndUpdate` with `$set` |
| `DELETE` | `/sessions/{id}` | Delete session document | `deleteOne` |

---

## 6. Migration & Backward Compatibility

### 1. Dual-Write Audit Trail
When an analyst asks a question in a multi-turn session, the system atomically updates MongoDB while dual-writing an entry to the PostgreSQL `InvestigationLog` table to preserve legacy audit compatibility.

### 2. Standalone Migration Script
To migrate historical PostgreSQL records into MongoDB without data loss:
```bash
python scripts/migrate_investigations_to_mongo.py
```
- **Read-only on PostgreSQL:** Does not alter or delete existing relational tables.
- **Idempotent on MongoDB:** Uses deterministic IDs (`SES-MIG-PG{id:06d}`) and checks existence before inserting.
- **Preserved Status:** Marks migrated historical single turns as `ARCHIVED`.

---

## 7. Automated Testing Verification

The test suite in [`backend/tests/test_investigation_sessions.py`](file:///c:/Users/Tapan/Downloads/BigDataPR/backend/tests/test_investigation_sessions.py) validates:
1. `test_create_session_empty`: Session creation without initial question.
2. `test_create_session_with_initial_turn`: Creation with immediate Turn 1 population.
3. `test_get_session_by_id`: Complete document retrieval.
4. `test_add_conversation_turn`: Atomic turn append with `$push` and `$inc`.
5. `test_session_turn_isolation`: Verifies that adding turns to Session A does not affect Session B.
6. `test_turn_limit_enforced`: Rejects requests after 50 turns.
7. `test_submit_turn_feedback_array_filters`: Updates specific turn feedback via `arrayFilters`.
8. `test_update_session_metadata_and_archive`: Status mutation to `ARCHIVED`.
9. `test_list_sessions_filtering_and_pagination`: Filtering by status, analyst, and pagination.
10. `test_session_analytics_aggregation`: Multi-faceted pipeline computing average ratings and groundedness.
11. `test_single_turn_backward_compatibility`: Legacy endpoint synchronizes with active session when `session_id` is supplied.
