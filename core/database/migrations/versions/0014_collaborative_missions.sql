-- V3 additive collaboration schema. Existing tasks/sessions are reused.
CREATE TABLE missions (
 id TEXT PRIMARY KEY,
 project_id TEXT NOT NULL REFERENCES projects(id),
 command_id TEXT NOT NULL UNIQUE,
 data TEXT NOT NULL CHECK(json_valid(data) AND json_extract(data, '$.schema_version') = 1)
);
CREATE TABLE mission_events (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT,
 mission_id TEXT NOT NULL REFERENCES missions(id),
 entity_type TEXT NOT NULL,
 entity_id TEXT NOT NULL,
 record TEXT NOT NULL CHECK(json_valid(record)),
 timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 schema_version INTEGER NOT NULL DEFAULT 1 CHECK(schema_version=1)
);
CREATE INDEX mission_events_order ON mission_events(mission_id, sequence);
CREATE TRIGGER mission_events_immutable_update BEFORE UPDATE ON mission_events BEGIN
 SELECT RAISE(ABORT, 'MissionEvent is immutable'); END;
CREATE TRIGGER mission_events_immutable_delete BEFORE DELETE ON mission_events BEGIN
 SELECT RAISE(ABORT, 'MissionEvent is immutable'); END;
CREATE TABLE mission_commands (
 id TEXT PRIMARY KEY, mission_id TEXT NOT NULL REFERENCES missions(id),
 data TEXT NOT NULL CHECK(json_valid(data)),
 status TEXT NOT NULL CHECK(status IN ('pending','completed','failed')) DEFAULT 'pending'
);
CREATE TABLE mission_task_links (
 task_id TEXT PRIMARY KEY REFERENCES tasks(id),
 mission_id TEXT NOT NULL REFERENCES missions(id)
);
CREATE TABLE mission_session_links (
 session_id TEXT PRIMARY KEY REFERENCES sessions(id),
 mission_id TEXT NOT NULL REFERENCES missions(id)
);
CREATE TABLE mission_workspace_leases (
 path TEXT PRIMARY KEY, mission_id TEXT NOT NULL UNIQUE REFERENCES missions(id)
);
CREATE TABLE mission_plans (
 id TEXT PRIMARY KEY, mission_id TEXT NOT NULL REFERENCES missions(id),
 data TEXT NOT NULL CHECK(json_valid(data) AND json_extract(data, '$.schema_version') = 1)
 ,leader_session_id TEXT NOT NULL REFERENCES sessions(id), version INTEGER NOT NULL, UNIQUE(mission_id, version)
 );
 CREATE INDEX mission_plans_mission ON mission_plans(mission_id);
 CREATE TABLE mission_assignments (
 id TEXT PRIMARY KEY, mission_id TEXT NOT NULL REFERENCES missions(id),
 data TEXT NOT NULL CHECK(json_valid(data) AND json_extract(data, '$.schema_version') = 1)
 ,task_id TEXT REFERENCES tasks(id), agent_id TEXT NOT NULL REFERENCES agents(id), session_id TEXT NOT NULL UNIQUE REFERENCES sessions(id)
 );
 CREATE INDEX mission_assignments_mission ON mission_assignments(mission_id);
 CREATE TABLE agent_messages (
 id TEXT PRIMARY KEY, mission_id TEXT NOT NULL REFERENCES missions(id),
 data TEXT NOT NULL CHECK(json_valid(data) AND json_extract(data, '$.schema_version') = 1)
 ,task_id TEXT REFERENCES tasks(id), from_session_id TEXT NOT NULL REFERENCES sessions(id), to_session_id TEXT REFERENCES sessions(id), reply_to TEXT REFERENCES agent_messages(id)
 );
 CREATE INDEX agent_messages_mission ON agent_messages(mission_id);
 CREATE TABLE mission_artifacts (
 id TEXT PRIMARY KEY, mission_id TEXT NOT NULL REFERENCES missions(id),
 data TEXT NOT NULL CHECK(json_valid(data) AND json_extract(data, '$.schema_version') = 1)
 ,task_id TEXT REFERENCES tasks(id), session_id TEXT REFERENCES sessions(id)
 );
 CREATE INDEX mission_artifacts_mission ON mission_artifacts(mission_id);
 CREATE TABLE mission_reviews (
 id TEXT PRIMARY KEY, mission_id TEXT NOT NULL REFERENCES missions(id),
 data TEXT NOT NULL CHECK(json_valid(data) AND json_extract(data, '$.schema_version') = 1)
 ,task_id TEXT NOT NULL REFERENCES tasks(id), reviewer_session_id TEXT NOT NULL REFERENCES sessions(id), worker_session_id TEXT NOT NULL REFERENCES sessions(id), CHECK(reviewer_session_id != worker_session_id)
 );
 CREATE INDEX mission_reviews_mission ON mission_reviews(mission_id);
 CREATE TABLE mission_instructions (
 id TEXT PRIMARY KEY, mission_id TEXT NOT NULL REFERENCES missions(id),
 data TEXT NOT NULL CHECK(json_valid(data) AND json_extract(data, '$.schema_version') = 1)
 
 );
 CREATE INDEX mission_instructions_mission ON mission_instructions(mission_id);
 CREATE TRIGGER missions_insert_event AFTER INSERT ON missions BEGIN
  INSERT INTO mission_events(mission_id,entity_type,entity_id,record) VALUES(NEW.id,'missions',NEW.id,NEW.data);
  END;
  CREATE TRIGGER missions_update_event AFTER UPDATE ON missions BEGIN
  INSERT INTO mission_events(mission_id,entity_type,entity_id,record) VALUES(NEW.id,'missions',NEW.id,NEW.data);
  END;
  CREATE TRIGGER mission_plans_insert_event AFTER INSERT ON mission_plans BEGIN
  INSERT INTO mission_events(mission_id,entity_type,entity_id,record) VALUES(NEW.mission_id,'mission_plans',NEW.id,NEW.data);
  END;
  CREATE TRIGGER mission_plans_update_event AFTER UPDATE ON mission_plans BEGIN
  INSERT INTO mission_events(mission_id,entity_type,entity_id,record) VALUES(NEW.mission_id,'mission_plans',NEW.id,NEW.data);
  END;
  CREATE TRIGGER mission_assignments_insert_event AFTER INSERT ON mission_assignments BEGIN
  INSERT INTO mission_events(mission_id,entity_type,entity_id,record) VALUES(NEW.mission_id,'mission_assignments',NEW.id,NEW.data);
  END;
  CREATE TRIGGER mission_assignments_update_event AFTER UPDATE ON mission_assignments BEGIN
  INSERT INTO mission_events(mission_id,entity_type,entity_id,record) VALUES(NEW.mission_id,'mission_assignments',NEW.id,NEW.data);
  END;
  CREATE TRIGGER agent_messages_insert_event AFTER INSERT ON agent_messages BEGIN
  INSERT INTO mission_events(mission_id,entity_type,entity_id,record) VALUES(NEW.mission_id,'agent_messages',NEW.id,NEW.data);
  END;
  CREATE TRIGGER agent_messages_update_event AFTER UPDATE ON agent_messages BEGIN
  INSERT INTO mission_events(mission_id,entity_type,entity_id,record) VALUES(NEW.mission_id,'agent_messages',NEW.id,NEW.data);
  END;
  CREATE TRIGGER mission_artifacts_insert_event AFTER INSERT ON mission_artifacts BEGIN
  INSERT INTO mission_events(mission_id,entity_type,entity_id,record) VALUES(NEW.mission_id,'mission_artifacts',NEW.id,NEW.data);
  END;
  CREATE TRIGGER mission_artifacts_update_event AFTER UPDATE ON mission_artifacts BEGIN
  INSERT INTO mission_events(mission_id,entity_type,entity_id,record) VALUES(NEW.mission_id,'mission_artifacts',NEW.id,NEW.data);
  END;
  CREATE TRIGGER mission_reviews_insert_event AFTER INSERT ON mission_reviews BEGIN
  INSERT INTO mission_events(mission_id,entity_type,entity_id,record) VALUES(NEW.mission_id,'mission_reviews',NEW.id,NEW.data);
  END;
  CREATE TRIGGER mission_reviews_update_event AFTER UPDATE ON mission_reviews BEGIN
  INSERT INTO mission_events(mission_id,entity_type,entity_id,record) VALUES(NEW.mission_id,'mission_reviews',NEW.id,NEW.data);
  END;
  CREATE TRIGGER mission_instructions_insert_event AFTER INSERT ON mission_instructions BEGIN
  INSERT INTO mission_events(mission_id,entity_type,entity_id,record) VALUES(NEW.mission_id,'mission_instructions',NEW.id,NEW.data);
  END;
  CREATE TRIGGER mission_instructions_update_event AFTER UPDATE ON mission_instructions BEGIN
  INSERT INTO mission_events(mission_id,entity_type,entity_id,record) VALUES(NEW.mission_id,'mission_instructions',NEW.id,NEW.data);
  END;
  CREATE TRIGGER mission_task_linked AFTER INSERT ON mission_task_links BEGIN
 INSERT INTO mission_events(mission_id,entity_type,entity_id,record) VALUES(NEW.mission_id,'tasks',NEW.task_id,json_object('schema_version',1,'status',(SELECT status FROM tasks WHERE id=NEW.task_id)));
 END;
 CREATE TRIGGER mission_task_updated AFTER UPDATE ON tasks BEGIN
 INSERT INTO mission_events(mission_id,entity_type,entity_id,record)
 SELECT mission_id,'tasks',NEW.id,json_object('schema_version',1,'status',NEW.status) FROM mission_task_links WHERE task_id=NEW.id;
 END;
 CREATE TRIGGER mission_session_linked AFTER INSERT ON mission_session_links BEGIN
 INSERT INTO mission_events(mission_id,entity_type,entity_id,record) VALUES(NEW.mission_id,'sessions',NEW.session_id,json_object('schema_version',1,'status',(SELECT status FROM sessions WHERE id=NEW.session_id)));
 END;
 CREATE TRIGGER mission_session_updated AFTER UPDATE ON sessions BEGIN
 INSERT INTO mission_events(mission_id,entity_type,entity_id,record)
 SELECT mission_id,'sessions',NEW.id,json_object('schema_version',1,'status',NEW.status) FROM mission_session_links WHERE session_id=NEW.id;
 END;
 CREATE TRIGGER independent_mission_review BEFORE INSERT ON mission_reviews BEGIN
 SELECT CASE WHEN
 (SELECT agent_id FROM sessions WHERE id=NEW.reviewer_session_id) =
 (SELECT agent_id FROM sessions WHERE id=NEW.worker_session_id)
 THEN RAISE(ABORT,'An agent cannot approve its own work') END;
 END;

CREATE TRIGGER mission_plans_scope_insert BEFORE INSERT ON mission_plans BEGIN
SELECT CASE WHEN NEW.leader_session_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM mission_session_links WHERE session_id=NEW.leader_session_id AND mission_id=NEW.mission_id) THEN RAISE(ABORT,'Cross-mission leader_session_id') END;
END;

CREATE TRIGGER mission_plans_scope_update BEFORE UPDATE ON mission_plans BEGIN
SELECT CASE WHEN NEW.leader_session_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM mission_session_links WHERE session_id=NEW.leader_session_id AND mission_id=NEW.mission_id) THEN RAISE(ABORT,'Cross-mission leader_session_id') END;
END;

CREATE TRIGGER mission_assignments_scope_insert BEFORE INSERT ON mission_assignments BEGIN
SELECT CASE WHEN NEW.session_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM mission_session_links WHERE session_id=NEW.session_id AND mission_id=NEW.mission_id) THEN RAISE(ABORT,'Cross-mission session_id') END;
SELECT CASE WHEN NEW.task_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM mission_task_links WHERE task_id=NEW.task_id AND mission_id=NEW.mission_id) THEN RAISE(ABORT,'Cross-mission task_id') END;
END;

CREATE TRIGGER mission_assignments_scope_update BEFORE UPDATE ON mission_assignments BEGIN
SELECT CASE WHEN NEW.session_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM mission_session_links WHERE session_id=NEW.session_id AND mission_id=NEW.mission_id) THEN RAISE(ABORT,'Cross-mission session_id') END;
SELECT CASE WHEN NEW.task_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM mission_task_links WHERE task_id=NEW.task_id AND mission_id=NEW.mission_id) THEN RAISE(ABORT,'Cross-mission task_id') END;
END;

CREATE TRIGGER agent_messages_scope_insert BEFORE INSERT ON agent_messages BEGIN
SELECT CASE WHEN NEW.from_session_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM mission_session_links WHERE session_id=NEW.from_session_id AND mission_id=NEW.mission_id) THEN RAISE(ABORT,'Cross-mission from_session_id') END;
SELECT CASE WHEN NEW.to_session_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM mission_session_links WHERE session_id=NEW.to_session_id AND mission_id=NEW.mission_id) THEN RAISE(ABORT,'Cross-mission to_session_id') END;
SELECT CASE WHEN NEW.task_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM mission_task_links WHERE task_id=NEW.task_id AND mission_id=NEW.mission_id) THEN RAISE(ABORT,'Cross-mission task_id') END;
END;

CREATE TRIGGER agent_messages_scope_update BEFORE UPDATE ON agent_messages BEGIN
SELECT CASE WHEN NEW.from_session_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM mission_session_links WHERE session_id=NEW.from_session_id AND mission_id=NEW.mission_id) THEN RAISE(ABORT,'Cross-mission from_session_id') END;
SELECT CASE WHEN NEW.to_session_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM mission_session_links WHERE session_id=NEW.to_session_id AND mission_id=NEW.mission_id) THEN RAISE(ABORT,'Cross-mission to_session_id') END;
SELECT CASE WHEN NEW.task_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM mission_task_links WHERE task_id=NEW.task_id AND mission_id=NEW.mission_id) THEN RAISE(ABORT,'Cross-mission task_id') END;
END;

CREATE TRIGGER mission_artifacts_scope_insert BEFORE INSERT ON mission_artifacts BEGIN
SELECT CASE WHEN NEW.session_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM mission_session_links WHERE session_id=NEW.session_id AND mission_id=NEW.mission_id) THEN RAISE(ABORT,'Cross-mission session_id') END;
SELECT CASE WHEN NEW.task_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM mission_task_links WHERE task_id=NEW.task_id AND mission_id=NEW.mission_id) THEN RAISE(ABORT,'Cross-mission task_id') END;
END;

CREATE TRIGGER mission_artifacts_scope_update BEFORE UPDATE ON mission_artifacts BEGIN
SELECT CASE WHEN NEW.session_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM mission_session_links WHERE session_id=NEW.session_id AND mission_id=NEW.mission_id) THEN RAISE(ABORT,'Cross-mission session_id') END;
SELECT CASE WHEN NEW.task_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM mission_task_links WHERE task_id=NEW.task_id AND mission_id=NEW.mission_id) THEN RAISE(ABORT,'Cross-mission task_id') END;
END;

CREATE TRIGGER mission_reviews_scope_insert BEFORE INSERT ON mission_reviews BEGIN
SELECT CASE WHEN NEW.reviewer_session_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM mission_session_links WHERE session_id=NEW.reviewer_session_id AND mission_id=NEW.mission_id) THEN RAISE(ABORT,'Cross-mission reviewer_session_id') END;
SELECT CASE WHEN NEW.worker_session_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM mission_session_links WHERE session_id=NEW.worker_session_id AND mission_id=NEW.mission_id) THEN RAISE(ABORT,'Cross-mission worker_session_id') END;
SELECT CASE WHEN NEW.task_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM mission_task_links WHERE task_id=NEW.task_id AND mission_id=NEW.mission_id) THEN RAISE(ABORT,'Cross-mission task_id') END;
END;

CREATE TRIGGER mission_reviews_scope_update BEFORE UPDATE ON mission_reviews BEGIN
SELECT CASE WHEN NEW.reviewer_session_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM mission_session_links WHERE session_id=NEW.reviewer_session_id AND mission_id=NEW.mission_id) THEN RAISE(ABORT,'Cross-mission reviewer_session_id') END;
SELECT CASE WHEN NEW.worker_session_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM mission_session_links WHERE session_id=NEW.worker_session_id AND mission_id=NEW.mission_id) THEN RAISE(ABORT,'Cross-mission worker_session_id') END;
SELECT CASE WHEN NEW.task_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM mission_task_links WHERE task_id=NEW.task_id AND mission_id=NEW.mission_id) THEN RAISE(ABORT,'Cross-mission task_id') END;
END;

CREATE TRIGGER message_reply_scope BEFORE INSERT ON agent_messages BEGIN
 SELECT CASE WHEN NEW.reply_to IS NOT NULL AND NOT EXISTS
 (SELECT 1 FROM agent_messages WHERE id=NEW.reply_to AND mission_id=NEW.mission_id)
 THEN RAISE(ABORT,'Cross-mission reply') END;
 SELECT CASE WHEN EXISTS (SELECT 1 FROM json_each(NEW.data,'$.artifact_ids') refs
 WHERE NOT EXISTS (SELECT 1 FROM mission_artifacts WHERE id=refs.value AND mission_id=NEW.mission_id))
 THEN RAISE(ABORT,'Cross-mission artifact reference') END;
END;
CREATE TRIGGER assignment_identity BEFORE INSERT ON mission_assignments BEGIN
 SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM sessions WHERE id=NEW.session_id
 AND agent_id=NEW.agent_id AND task_id IS NEW.task_id)
 THEN RAISE(ABORT,'Assignment/session identity mismatch') END;
END;
CREATE TRIGGER review_independence_history BEFORE INSERT ON mission_reviews BEGIN
 SELECT CASE WHEN EXISTS (SELECT 1 FROM mission_assignments a JOIN sessions s ON s.id=NEW.reviewer_session_id
 WHERE a.task_id=NEW.task_id AND a.agent_id=s.agent_id AND json_extract(a.data,'$.role')='worker')
 THEN RAISE(ABORT,'Reviewer implemented this task') END;
END;
