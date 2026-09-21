-- Immutable versioned evidence and durable operation/recovery journal.
CREATE TABLE delivery_bindings (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), data TEXT NOT NULL
);
CREATE INDEX delivery_bindings_project ON delivery_bindings(project_id);
CREATE TABLE delivery_candidates (
    id TEXT PRIMARY KEY, mission_id TEXT NOT NULL REFERENCES missions(id),
    project_id TEXT NOT NULL REFERENCES projects(id), version INTEGER NOT NULL CHECK(version > 0),
    status TEXT NOT NULL, snapshot_id TEXT NOT NULL UNIQUE,
    binding_id TEXT NOT NULL REFERENCES delivery_bindings(id), data TEXT NOT NULL,
    UNIQUE(mission_id, version)
);
CREATE TABLE delivery_snapshots (
    id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL UNIQUE REFERENCES delivery_candidates(id),
    data TEXT NOT NULL, evidence TEXT NOT NULL
);
CREATE TRIGGER delivery_snapshot_no_update BEFORE UPDATE ON delivery_snapshots
BEGIN SELECT RAISE(ABORT, 'Delivery snapshots are immutable'); END;
CREATE TRIGGER delivery_snapshot_no_delete BEFORE DELETE ON delivery_snapshots
BEGIN SELECT RAISE(ABORT, 'Delivery snapshots are immutable'); END;
CREATE TRIGGER delivery_candidate_identity BEFORE UPDATE ON delivery_candidates
WHEN NEW.mission_id != OLD.mission_id OR NEW.project_id != OLD.project_id
 OR NEW.version != OLD.version OR NEW.snapshot_id != OLD.snapshot_id OR NEW.binding_id != OLD.binding_id
 OR json_remove(NEW.data,'$.status','$.updated_at') != json_remove(OLD.data,'$.status','$.updated_at')
BEGIN SELECT RAISE(ABORT, 'Delivery candidate identity is immutable'); END;
CREATE TABLE delivery_records (
    id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES delivery_candidates(id),
    kind TEXT NOT NULL, data TEXT NOT NULL
);
CREATE INDEX delivery_records_lookup ON delivery_records(candidate_id,kind);
CREATE TRIGGER delivery_approval_no_update BEFORE UPDATE ON delivery_records
WHEN OLD.kind='DeliveryApproval'
BEGIN SELECT RAISE(ABORT, 'Delivery approvals are immutable'); END;
CREATE TRIGGER delivery_approval_no_delete BEFORE DELETE ON delivery_records
WHEN OLD.kind='DeliveryApproval'
BEGIN SELECT RAISE(ABORT, 'Delivery approvals are immutable'); END;
CREATE TABLE delivery_operations (
    id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES delivery_candidates(id),
    operation_type TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL, data TEXT NOT NULL,
    UNIQUE(candidate_id,operation_type)
);
CREATE TRIGGER delivery_binding_identity BEFORE UPDATE ON delivery_bindings
WHEN NEW.project_id != OLD.project_id OR
 json_remove(NEW.data,'$.auth_detected','$.auth_type','$.permissions','$.branch_protections','$.last_verified_at') !=
 json_remove(OLD.data,'$.auth_detected','$.auth_type','$.permissions','$.branch_protections','$.last_verified_at')
BEGIN SELECT RAISE(ABORT, 'Binding configuration is immutable; create a new binding'); END;
