-- Native OceanX storage. No migration/import path for legacy workspaces.
CREATE TABLE artifact_commit_intents (
                    operation_id TEXT PRIMARY KEY,
                    request_id TEXT,
                    origin_request_id TEXT,
                    task_id TEXT,
                    task_relation TEXT,
                    workspace_id TEXT NOT NULL,
                        artifact_id TEXT NOT NULL,
                        version INTEGER NOT NULL,
                        expected_workspace_revision INTEGER,
                        staging_uri TEXT NOT NULL,
                        target_uri TEXT NOT NULL,
                        manifest_json TEXT NOT NULL,
                        manifest_sha256 TEXT NOT NULL,
                        status TEXT NOT NULL,
                        quarantine_uri TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    , committed_event_id TEXT);

CREATE TABLE artifact_files (
                        workspace_id TEXT NOT NULL,
                        artifact_id TEXT NOT NULL,
                        version INTEGER NOT NULL,
                        uri TEXT NOT NULL,
                        mime_type TEXT NOT NULL,
                        size_bytes INTEGER NOT NULL,
                        sha256 TEXT NOT NULL,
                        PRIMARY KEY (workspace_id, artifact_id, version, uri),
                        FOREIGN KEY (workspace_id, artifact_id, version)
                            REFERENCES artifact_versions(workspace_id, artifact_id, version)
                    );

CREATE TABLE artifact_links (
                        link_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        workspace_id TEXT NOT NULL,
                        source_artifact_id TEXT NOT NULL,
                        source_version INTEGER NOT NULL,
                        target_artifact_id TEXT NOT NULL,
                        target_version INTEGER NOT NULL,
                        relation TEXT NOT NULL,
                        intrinsic INTEGER NOT NULL,
                        created_at TEXT NOT NULL,
                        source_event_id TEXT
                    );

CREATE TABLE artifact_projections (
                        workspace_id TEXT NOT NULL,
                        artifact_id TEXT NOT NULL,
                        version INTEGER NOT NULL,
                        lifecycle_state TEXT NOT NULL,
                        impact_state TEXT NOT NULL,
                        impact_reasons_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        source_event_id TEXT,
                        PRIMARY KEY (workspace_id, artifact_id, version),
                        FOREIGN KEY (workspace_id, artifact_id, version)
                            REFERENCES artifact_versions(workspace_id, artifact_id, version)
                    );

CREATE TABLE artifact_state_events (
                        state_event_id TEXT PRIMARY KEY,
                        workspace_id TEXT NOT NULL,
                        artifact_id TEXT NOT NULL,
                        version INTEGER NOT NULL,
                        kind TEXT NOT NULL,
                        active INTEGER NOT NULL,
                        source_event_id TEXT,
                        created_at TEXT NOT NULL
                    );

CREATE TABLE artifact_versions (
                        workspace_id TEXT NOT NULL,
                        artifact_id TEXT NOT NULL,
                        version INTEGER NOT NULL,
                        artifact_type TEXT NOT NULL,
                        schema_version TEXT NOT NULL,
                        title TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        created_by TEXT NOT NULL,
                        supersedes_version INTEGER,
                        content_json TEXT NOT NULL,
                        intrinsic_links_json TEXT NOT NULL,
                        provenance_json TEXT NOT NULL,
                        manifest_uri TEXT NOT NULL,
                        manifest_sha256 TEXT NOT NULL,
                        PRIMARY KEY (workspace_id, artifact_id, version),
                        UNIQUE (manifest_uri)
                    );

CREATE TABLE code_executions (
                        execution_id TEXT PRIMARY KEY,
                        workspace_id TEXT NOT NULL,
                        task_id TEXT NOT NULL,
                        agent_thread_id TEXT NOT NULL,
                        server_run_id TEXT NOT NULL,
                        state TEXT NOT NULL,
                        request_json TEXT NOT NULL,
                        result_json TEXT,
                        started_at TEXT NOT NULL,
                        ended_at TEXT,
                        FOREIGN KEY (task_id) REFERENCES research_tasks(task_id),
                        CHECK (state IN (
                            'running', 'succeeded', 'failed', 'timed_out',
                            'resource_limited', 'cancelled'
                        ))
                    );

CREATE TABLE coordinator_result_receipts (
                        request_id TEXT PRIMARY KEY,
                        result_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (request_id) REFERENCES request_records(request_id)
                    );

CREATE TABLE disclosure_audit_records (
                        audit_id TEXT PRIMARY KEY,
                        workspace_id TEXT NOT NULL,
                        provider_id TEXT NOT NULL,
                        policy_version INTEGER NOT NULL,
                        content_type TEXT NOT NULL,
                        disposition TEXT NOT NULL,
                        byte_count INTEGER NOT NULL,
                        item_count INTEGER NOT NULL,
                        source_ref_json TEXT,
                        created_at TEXT NOT NULL
                    );

CREATE TABLE event_records (
                    event_id TEXT PRIMARY KEY,
                    request_id TEXT,
                    workspace_id TEXT,
                    event_type TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

CREATE TABLE model_call_observations (
                        call_id TEXT PRIMARY KEY, request_id TEXT, thread_id TEXT NOT NULL,
                        record_json TEXT NOT NULL
                    );

CREATE TABLE operation_checkpoints (
                    operation_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    tool_call_id TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

CREATE TABLE request_records (
                    request_id TEXT PRIMARY KEY,
                    request_type TEXT NOT NULL,
                    canonical_hash TEXT NOT NULL,
                    canonical_request_json TEXT NOT NULL,
                    principal TEXT NOT NULL,
                    session_id TEXT,
                    workspace_id TEXT,
                    state TEXT NOT NULL,
                    terminal_event_json TEXT,
                    terminal_event_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                , task_id TEXT);

CREATE TABLE research_tasks (
                        task_id TEXT PRIMARY KEY,
                        workspace_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        status TEXT NOT NULL,
                        task_revision INTEGER NOT NULL,
                        active_request_id TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        CHECK (status IN ('active', 'completed', 'archived'))
                    );

CREATE TABLE resource_usage_records (
                        usage_id TEXT PRIMARY KEY,
                        workspace_id TEXT NOT NULL,
                        agent_run_id TEXT,
                        resource_kind TEXT NOT NULL,
                        resource_name TEXT NOT NULL,
                        resource_version TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    , request_id TEXT, agent_id TEXT);

CREATE TABLE session_records (
                    session_id TEXT PRIMARY KEY,
                    principal TEXT NOT NULL,
                    workspace_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

CREATE TABLE task_artifact_links (
                        task_id TEXT NOT NULL,
                        artifact_id TEXT NOT NULL,
                        version INTEGER NOT NULL,
                        relation TEXT NOT NULL,
                        origin_request_id TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (
                            task_id, artifact_id, version, relation, origin_request_id
                        ),
                        FOREIGN KEY (task_id) REFERENCES research_tasks(task_id)
                    );

CREATE TABLE task_interactions (
                        interaction_id TEXT PRIMARY KEY,
                        request_id TEXT NOT NULL,
                        task_id TEXT,
                        workspace_id TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        principal TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        question TEXT NOT NULL,
                        options_json TEXT NOT NULL DEFAULT '[]',
                        state TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        resolved_at TEXT,
                        CHECK (kind IN ('question', 'permission', 'paper_selection')),
                        CHECK (state IN ('pending', 'answered', 'interrupted'))
                    );

CREATE TABLE task_transcript_items (
                        item_id TEXT PRIMARY KEY,
                        task_id TEXT NOT NULL,
                        sequence INTEGER NOT NULL,
                        role TEXT NOT NULL,
                        text TEXT NOT NULL,
                        request_id TEXT,
                        turn_id TEXT,
                        tool_call_id TEXT,
                        interrupted INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        UNIQUE(task_id, sequence),
                        FOREIGN KEY (task_id) REFERENCES research_tasks(task_id),
                        CHECK (role IN ('user', 'assistant', 'tool', 'system'))
                    );

CREATE TABLE task_workflows (
                        request_id TEXT PRIMARY KEY,
                        task_id TEXT NOT NULL,
                        workspace_id TEXT NOT NULL,
                        state TEXT NOT NULL,
                        activity TEXT NOT NULL,
                        heartbeat_at TEXT NOT NULL,
                        failure_fingerprint TEXT,
                        repeated_failures INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY (task_id) REFERENCES research_tasks(task_id),
                        CHECK (state IN (
                            'planning', 'working', 'completed', 'incomplete',
                            'failed', 'cancelled'
                        )),
                        CHECK (repeated_failures >= 0)
                    );

CREATE TABLE tool_call_records (
                        operation_id TEXT PRIMARY KEY,
                        request_id TEXT NOT NULL,
                        turn_id TEXT NOT NULL,
                        tool_call_id TEXT NOT NULL,
                        tool_name TEXT NOT NULL,
                        state TEXT NOT NULL,
                        result_json TEXT,
                        created_at TEXT NOT NULL,
                        completed_at TEXT
                    );

CREATE TABLE workspace_active_refs (
                        workspace_id TEXT NOT NULL,
                        slot TEXT NOT NULL,
                        artifact_id TEXT NOT NULL,
                        version INTEGER NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (workspace_id, slot)
                    );

CREATE TABLE workspace_disclosure_policies (
                        workspace_id TEXT PRIMARY KEY,
                        provider_id TEXT NOT NULL,
                        policy_version INTEGER NOT NULL,
                        policy_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

CREATE TABLE workspace_disclosure_policy_versions (
                        workspace_id TEXT NOT NULL,
                        policy_version INTEGER NOT NULL,
                        provider_id TEXT NOT NULL,
                        policy_json TEXT NOT NULL,
                        confirmed_request_id TEXT,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (workspace_id, policy_version)
                    );

CREATE TABLE workspace_records (
                    workspace_id TEXT PRIMARY KEY,
                    path TEXT,
                    revision INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );

CREATE UNIQUE INDEX idx_artifact_commit_intents_version
                        ON artifact_commit_intents(workspace_id, artifact_id, version)
                        ;

CREATE INDEX idx_artifact_links_source
                        ON artifact_links(workspace_id, source_artifact_id, source_version, relation);

CREATE INDEX idx_artifact_links_target
                        ON artifact_links(workspace_id, target_artifact_id, target_version, relation);

CREATE INDEX idx_code_executions_task
                        ON code_executions(task_id, started_at);

CREATE INDEX idx_code_executions_agent
                        ON code_executions(agent_thread_id, started_at);

CREATE INDEX idx_disclosure_audit_workspace
                        ON disclosure_audit_records(workspace_id, created_at);

CREATE INDEX idx_disclosure_policy_versions_workspace
                        ON workspace_disclosure_policy_versions(workspace_id, policy_version DESC);

CREATE INDEX idx_event_records_workspace
                    ON event_records(workspace_id, created_at);

CREATE INDEX idx_model_calls_request ON model_call_observations(request_id);

CREATE INDEX idx_request_records_session_state
                    ON request_records(session_id, state);

CREATE INDEX idx_request_records_task_state
                        ON request_records(task_id, state);

CREATE INDEX idx_research_tasks_workspace_updated
                        ON research_tasks(workspace_id, updated_at DESC);

CREATE INDEX idx_resource_usage_agent_run
                        ON resource_usage_records(agent_run_id, created_at);

CREATE INDEX idx_resource_usage_workspace
                        ON resource_usage_records(workspace_id, created_at);

CREATE INDEX idx_task_artifact_links_task
                        ON task_artifact_links(task_id, created_at DESC);

CREATE INDEX idx_task_interactions_request_state
                        ON task_interactions(request_id, state);

CREATE INDEX idx_task_interactions_task_state
                        ON task_interactions(task_id, state, created_at DESC);

CREATE INDEX idx_task_transcript_items_task_sequence
                        ON task_transcript_items(task_id, sequence DESC);

CREATE INDEX idx_task_workflows_state_heartbeat
                        ON task_workflows(state, heartbeat_at);

CREATE INDEX idx_task_workflows_task_updated
                        ON task_workflows(task_id, updated_at DESC);

CREATE INDEX idx_tool_call_records_request
                        ON tool_call_records(request_id, created_at);

CREATE TABLE storage_contract (version TEXT PRIMARY KEY);
INSERT INTO storage_contract VALUES ('oceanx-agent-server/v3');
