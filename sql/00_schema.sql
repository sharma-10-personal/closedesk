-- CloseDesk schema. All matching and audit state lives in Exasol.
-- Safe to re-run: drops the application schema then recreates it.

DROP SCHEMA IF EXISTS CLOSEDESK CASCADE;
CREATE SCHEMA CLOSEDESK;
OPEN SCHEMA CLOSEDESK;

CREATE TABLE npci_settlement (
    npci_ref          VARCHAR(32) UTF8 NOT NULL,
    txn_ts            TIMESTAMP NOT NULL,
    amount_inr        DECIMAL(18,2) NOT NULL,
    status            VARCHAR(16) UTF8 NOT NULL,
    payer_psp         VARCHAR(64) UTF8,
    payee_psp         VARCHAR(64) UTF8,
    merchant_id       VARCHAR(32) UTF8,
    mcc               VARCHAR(8) UTF8,
    gateway_id        VARCHAR(32) UTF8,
    PRIMARY KEY (npci_ref)
);

CREATE TABLE bank_ledger (
    ledger_id         VARCHAR(32) UTF8 NOT NULL,
    npci_ref          VARCHAR(32) UTF8,
    txn_ts            TIMESTAMP NOT NULL,
    amount_inr        DECIMAL(18,2) NOT NULL,
    direction         VARCHAR(8) UTF8 NOT NULL,
    account_id        VARCHAR(32) UTF8 NOT NULL,
    status            VARCHAR(16) UTF8 NOT NULL,
    posting_ts        TIMESTAMP NOT NULL,
    PRIMARY KEY (ledger_id)
);

CREATE TABLE merchant_records (
    merchant_txn_id   VARCHAR(32) UTF8 NOT NULL,
    npci_ref          VARCHAR(32) UTF8,
    txn_ts            TIMESTAMP NOT NULL,
    amount_inr        DECIMAL(18,2) NOT NULL,
    merchant_id       VARCHAR(32) UTF8 NOT NULL,
    gateway_id        VARCHAR(32) UTF8,
    status            VARCHAR(16) UTF8 NOT NULL,
    PRIMARY KEY (merchant_txn_id)
);

-- Planted truth. Used only for evaluation, never shown as a production signal.
CREATE TABLE answer_key (
    break_id          VARCHAR(32) UTF8 NOT NULL,
    npci_ref          VARCHAR(32) UTF8,
    break_type        VARCHAR(32) UTF8 NOT NULL,
    expected_action   VARCHAR(32) UTF8 NOT NULL,
    PRIMARY KEY (break_id)
);

CREATE TABLE match_stage_log (
    run_id            VARCHAR(32) UTF8 NOT NULL,
    stage             VARCHAR(32) UTF8 NOT NULL,
    started_at        TIMESTAMP NOT NULL,
    elapsed_ms        DECIMAL(18,0) NOT NULL,
    rows_in           DECIMAL(18,0) NOT NULL,
    rows_matched      DECIMAL(18,0) NOT NULL,
    rupees_matched    DECIMAL(18,2) NOT NULL,
    PRIMARY KEY (run_id, stage)
);

CREATE TABLE matches (
    run_id            VARCHAR(32) UTF8 NOT NULL,
    npci_ref          VARCHAR(32) UTF8 NOT NULL,
    ledger_id         VARCHAR(32) UTF8,
    merchant_txn_id   VARCHAR(32) UTF8,
    stage             VARCHAR(32) UTF8 NOT NULL,
    amount_inr        DECIMAL(18,2) NOT NULL,
    PRIMARY KEY (run_id, npci_ref, stage)
);

CREATE TABLE breaks (
    run_id            VARCHAR(32) UTF8 NOT NULL,
    break_id          DECIMAL(18,0) IDENTITY NOT NULL,
    npci_ref          VARCHAR(32) UTF8,
    ledger_id         VARCHAR(32) UTF8,
    merchant_txn_id   VARCHAR(32) UTF8,
    break_type        VARCHAR(32) UTF8 NOT NULL,
    amount_inr        DECIMAL(18,2) NOT NULL,
    rupees_at_risk    DECIMAL(18,2) NOT NULL,
    deadline_ts       TIMESTAMP,
    root_cause_id     VARCHAR(64) UTF8,
    PRIMARY KEY (run_id, break_id)
);

CREATE TABLE root_causes (
    run_id            VARCHAR(32) UTF8 NOT NULL,
    root_cause_id     VARCHAR(64) UTF8 NOT NULL,
    title             VARCHAR(200) UTF8 NOT NULL,
    break_count       DECIMAL(18,0) NOT NULL,
    rupees_at_risk    DECIMAL(18,2) NOT NULL,
    PRIMARY KEY (run_id, root_cause_id)
);

CREATE TABLE proposals (
    proposal_id       VARCHAR(32) UTF8 NOT NULL,
    run_id            VARCHAR(32) UTF8 NOT NULL,
    break_id          DECIMAL(18,0) NOT NULL,
    action_name       VARCHAR(32) UTF8 NOT NULL,
    explanation       VARCHAR(4000) UTF8 NOT NULL,
    amount_inr        DECIMAL(18,2) NOT NULL,
    gate_decision     VARCHAR(16) UTF8 NOT NULL,
    status            VARCHAR(16) UTF8 NOT NULL,
    created_at        TIMESTAMP NOT NULL,
    PRIMARY KEY (proposal_id)
);

CREATE TABLE decisions (
    decision_id       VARCHAR(32) UTF8 NOT NULL,
    proposal_id       VARCHAR(32) UTF8 NOT NULL,
    decided_by        VARCHAR(64) UTF8 NOT NULL,
    decision_name     VARCHAR(16) UTF8 NOT NULL,
    decided_at        TIMESTAMP NOT NULL,
    note              VARCHAR(1000) UTF8,
    PRIMARY KEY (decision_id)
);

CREATE TABLE audit_log (
    audit_id          DECIMAL(18,0) IDENTITY NOT NULL PRIMARY KEY,
    at_ts             TIMESTAMP NOT NULL,
    actor             VARCHAR(64) UTF8 NOT NULL,
    action_name       VARCHAR(32) UTF8 NOT NULL,
    entity_type       VARCHAR(32) UTF8 NOT NULL,
    entity_id         VARCHAR(32) UTF8 NOT NULL,
    before_json       VARCHAR(4000) UTF8,
    after_json        VARCHAR(4000) UTF8
);
