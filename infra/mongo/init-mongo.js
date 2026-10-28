// AgentShield: MongoDB Initialization Script
// Runs automatically on first container boot (/docker-entrypoint-initdb.d/)

const dbName = process.env.MONGO_INITDB_DATABASE || "agentshield";
const dbInstance = db.getSiblingDB(dbName);

print(`[agentshield-mongo] Initializing database: ${dbName}`);

// -----------------------------------------------------------------------------
// 1. Collection: security_cases with JSON Schema Validation
// -----------------------------------------------------------------------------
const casesSchema = {
  $jsonSchema: {
    bsonType: "object",
    required: ["case_id", "title", "status", "severity", "target_agent", "created_at"],
    properties: {
      case_id: {
        bsonType: "string",
        pattern: "^CASE-[0-9]{6}-[0-9a-fA-F]{4,8}$",
        description: "Standardized unique case identifier, e.g. CASE-202610-0042"
      },
      title: {
        bsonType: "string",
        minLength: 3,
        maxLength: 256,
        description: "Descriptive human-readable case title"
      },
      status: {
        enum: ["OPEN", "TRIAGED", "IN_REVIEW", "REMEDIATION_PENDING", "RESOLVED", "DISMISSED"],
        description: "Operational incident state"
      },
      severity: {
        enum: ["low", "medium", "high", "critical"],
        description: "Case severity level"
      },
      priority: {
        enum: ["P1", "P2", "P3", "P4"],
        description: "Operational response priority"
      },
      assigned_analyst: {
        bsonType: ["object", "null"],
        properties: {
          username: { bsonType: "string" },
          email: { bsonType: ["string", "null"] },
          assigned_at: { bsonType: ["date", "null"] }
        }
      },
      target_agent: {
        bsonType: "object",
        required: ["agent_id", "agent_version"],
        properties: {
          agent_id: { bsonType: "string" },
          agent_version: { bsonType: "string" },
          workload_type: { bsonType: ["string", "null"] },
          model_name: { bsonType: ["string", "null"] }
        }
      },
      linked_findings: {
        bsonType: "array",
        items: {
          bsonType: "object",
          required: ["finding_id", "rule_id", "trace_id"],
          properties: {
            finding_id: { bsonType: "string" },
            rule_id: { bsonType: "string" },
            rule_name: { bsonType: "string" },
            severity: { bsonType: "string" },
            trace_id: { bsonType: "string" },
            span_id: { bsonType: ["string", "null"] },
            event_time: { bsonType: ["date", "string"] }
          }
        }
      },
      linked_anomaly_alerts: {
        bsonType: "array",
        items: {
          bsonType: "object",
          required: ["alert_id", "anomaly_type"],
          properties: {
            alert_id: { bsonType: "string" },
            anomaly_type: { bsonType: "string" },
            score: { bsonType: "double" },
            detector: { bsonType: "string" }
          }
        }
      },
      evidence_bundle: {
        bsonType: "array",
        items: {
          bsonType: "object",
          required: ["evidence_id", "kind"],
          properties: {
            evidence_id: { bsonType: "string" },
            kind: { bsonType: "string" },
            title: { bsonType: "string" },
            detail: { bsonType: "string" },
            ref: { bsonType: "string" },
            metadata: { bsonType: "object" }
          }
        }
      },
      timeline: {
        bsonType: "array",
        items: {
          bsonType: "object",
          required: ["timestamp", "author", "action", "notes"],
          properties: {
            timestamp: { bsonType: "date" },
            author: { bsonType: "string" },
            action: { bsonType: "string" },
            notes: { bsonType: "string" }
          }
        }
      },
      remediation: {
        bsonType: ["object", "null"],
        properties: {
          recommended_action: { bsonType: "string" },
          policy_file: { bsonType: ["string", "null"] },
          target_tool: { bsonType: ["string", "null"] },
          requires_code_freeze: { bsonType: "bool" },
          completed: { bsonType: "bool" },
          completed_at: { bsonType: ["date", "null"] },
          completed_by: { bsonType: ["string", "null"] }
        }
      },
      tags: {
        bsonType: "array",
        items: { bsonType: "string" }
      },
      created_at: { bsonType: "date" },
      updated_at: { bsonType: "date" }
    }
  }
};

const existingCollections = dbInstance.getCollectionNames();
if (!existingCollections.includes("security_cases")) {
  dbInstance.createCollection("security_cases", { validator: casesSchema });
  print("[agentshield-mongo] Created collection: security_cases with schema validator");
} else {
  dbInstance.runCommand({
    collMod: "security_cases",
    validator: casesSchema
  });
  print("[agentshield-mongo] Updated schema validator on existing collection: security_cases");
}

// -----------------------------------------------------------------------------
// 2. Indexes for security_cases
// -----------------------------------------------------------------------------
const casesCol = dbInstance.getCollection("security_cases");

// Unique business key
casesCol.createIndex({ case_id: 1 }, { unique: true, name: "idx_case_id_unique" });

// Triage filtering & SLA ordering
casesCol.createIndex(
  { status: 1, severity: 1, priority: 1, created_at: -1 },
  { name: "idx_cases_triage_sla" }
);

// Agent correlation
casesCol.createIndex(
  { "target_agent.agent_id": 1, "target_agent.agent_version": 1 },
  { name: "idx_cases_target_agent" }
);

// Multikey indexes on linked telemetry references
casesCol.createIndex(
  { "linked_findings.finding_id": 1 },
  { name: "idx_multikey_findings_finding_id" }
);
casesCol.createIndex(
  { "linked_findings.trace_id": 1 },
  { name: "idx_multikey_findings_trace_id" }
);
casesCol.createIndex(
  { "linked_anomaly_alerts.alert_id": 1 },
  { name: "idx_multikey_alerts_alert_id" }
);

// Full-text search index across titles and investigation timeline notes
casesCol.createIndex(
  { title: "text", "timeline.notes": "text" },
  { name: "idx_text_title_notes" }
);

print("[agentshield-mongo] Successfully initialized security_cases indexes.");

// -----------------------------------------------------------------------------
// 3. Collection: investigation_sessions with JSON Schema Validation
// -----------------------------------------------------------------------------
const sessionsSchema = {
  $jsonSchema: {
    bsonType: "object",
    required: ["session_id", "title", "status", "turn_count", "created_at", "updated_at"],
    properties: {
      session_id: {
        bsonType: "string",
        pattern: "^SESS-[0-9]{6}-[0-9a-fA-F]{4,8}$",
        description: "Standardized unique investigation session identifier"
      },
      title: {
        bsonType: "string",
        minLength: 3,
        maxLength: 256,
        description: "Descriptive title for the investigation session"
      },
      analyst: {
        bsonType: "string",
        pattern: "^[A-Za-z0-9_.\\-]{1,64}$",
        description: "Username of the analyst running the investigation"
      },
      status: {
        enum: ["ACTIVE", "ARCHIVED", "CLOSED"],
        description: "Lifecycle state of the investigation session"
      },
      scope_context: {
        bsonType: "object",
        properties: {
          test_run_id: { bsonType: ["string", "null"] },
          run_id: { bsonType: ["string", "null"] },
          trace_id: { bsonType: ["string", "null"] },
          agent_id: { bsonType: ["string", "null"] },
          agent_version: { bsonType: ["string", "null"] },
          baseline_version: { bsonType: ["string", "null"] }
        }
      },
      turn_count: {
        bsonType: "int",
        minimum: 0,
        maximum: 100,
        description: "Number of conversation turns in the session"
      },
      turns: {
        bsonType: "array",
        items: {
          bsonType: "object",
          required: ["turn_id", "question", "intent", "mode", "answer", "grounded", "created_at"],
          properties: {
            turn_id: { bsonType: "int", minimum: 1 },
            question: { bsonType: "string", minLength: 1, maxLength: 1000 },
            intent: { bsonType: "string", minLength: 1, maxLength: 64 },
            mode: { enum: ["deterministic", "llm"] },
            grounded: { bsonType: "bool" },
            answer: { bsonType: "string", minLength: 1 },
            evidence: {
              bsonType: "array",
              items: {
                bsonType: "object",
                required: ["kind", "ref", "title"],
                properties: {
                  kind: { bsonType: "string" },
                  ref: { bsonType: "string" },
                  title: { bsonType: "string" },
                  detail: { bsonType: "string" }
                }
              }
            },
            suggested_questions: {
              bsonType: "array",
              items: { bsonType: "string" }
            },
            feedback: {
              bsonType: ["object", "null"],
              properties: {
                rating: { bsonType: "int", minimum: 1, maximum: 5 },
                verdict: { enum: ["accurate", "hallucination", "incomplete"] },
                notes: { bsonType: ["string", "null"], maxLength: 1000 },
                submitted_at: { bsonType: "date" },
                submitted_by: { bsonType: "string" }
              }
            },
            created_at: { bsonType: "date" }
          }
        }
      },
      tags: {
        bsonType: "array",
        items: { bsonType: "string" }
      },
      created_at: { bsonType: "date" },
      updated_at: { bsonType: "date" }
    }
  }
};

if (!existingCollections.includes("investigation_sessions")) {
  dbInstance.createCollection("investigation_sessions", { validator: sessionsSchema });
  print("[agentshield-mongo] Created collection: investigation_sessions with schema validator");
} else {
  dbInstance.runCommand({
    collMod: "investigation_sessions",
    validator: sessionsSchema
  });
  print("[agentshield-mongo] Updated schema validator on existing collection: investigation_sessions");
}

// -----------------------------------------------------------------------------
// 4. Indexes for investigation_sessions
// -----------------------------------------------------------------------------
const sessionsCol = dbInstance.getCollection("investigation_sessions");

// Unique business key
sessionsCol.createIndex({ session_id: 1 }, { unique: true, name: "idx_session_id_unique" });

// Status & recency listing
sessionsCol.createIndex({ status: 1, updated_at: -1 }, { name: "idx_sessions_status_updated" });

// Analyst filter
sessionsCol.createIndex({ analyst: 1, updated_at: -1 }, { name: "idx_sessions_analyst" });

// Agent correlation
sessionsCol.createIndex(
  { "scope_context.agent_id": 1, "scope_context.agent_version": 1 },
  { name: "idx_sessions_agent" }
);

// Test run and trace correlations
sessionsCol.createIndex({ "scope_context.test_run_id": 1 }, { name: "idx_sessions_test_run" });
sessionsCol.createIndex({ "scope_context.trace_id": 1 }, { name: "idx_sessions_trace_id" });

// Multikey index on evidence references
sessionsCol.createIndex({ "turns.evidence.ref": 1 }, { name: "idx_multikey_turns_evidence_ref" });

// Full-text search index across titles, questions, and answers
sessionsCol.createIndex(
  { title: "text", "turns.question": "text", "turns.answer": "text" },
  { name: "idx_text_session_content" }
);

print("[agentshield-mongo] Successfully initialized investigation_sessions indexes.");
