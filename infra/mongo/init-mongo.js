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
          email: { bsonType: "string" },
          assigned_at: { bsonType: "date" }
        }
      },
      target_agent: {
        bsonType: "object",
        required: ["agent_id", "agent_version"],
        properties: {
          agent_id: { bsonType: "string" },
          agent_version: { bsonType: "string" },
          workload_type: { bsonType: "string" },
          model_name: { bsonType: "string" }
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
          policy_file: { bsonType: "string" },
          target_tool: { bsonType: "string" },
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
