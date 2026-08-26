-- Durable Base quote-proposal and transaction/receipt ledger.
--
-- This migration creates accounting and audit primitives only.  It does NOT grant
-- wallet custody, build/supply calldata, request token approvals, sign a message,
-- or broadcast a transaction.
--
-- All monetary quantities are exact NUMERIC values.  Token amounts are stored in
-- base units, and USDC exposure/loss values use six decimal places.

BEGIN;

CREATE TABLE IF NOT EXISTS autotrader_schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    checksum TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS policy_versions (
    id UUID PRIMARY KEY,
    policy_hash CHAR(64) NOT NULL UNIQUE,
    chain_id INTEGER NOT NULL CHECK (chain_id = 8453),
    execution_enabled BOOLEAN NOT NULL,
    emergency_stop BOOLEAN NOT NULL,
    max_trade_usdc NUMERIC(38, 6) NOT NULL CHECK (max_trade_usdc >= 0),
    max_daily_usdc NUMERIC(38, 6) NOT NULL CHECK (max_daily_usdc >= 0),
    max_daily_loss_usdc NUMERIC(38, 6) NOT NULL CHECK (max_daily_loss_usdc >= 0),
    max_slippage_bps INTEGER NOT NULL CHECK (max_slippage_bps BETWEEN 0 AND 100),
    max_network_fee_wei NUMERIC(78, 0) NOT NULL CHECK (max_network_fee_wei >= 0),
    configuration JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (jsonb_typeof(configuration) = 'object')
);

CREATE TABLE IF NOT EXISTS quote_proposals (
    id UUID PRIMARY KEY,
    idempotency_key UUID NOT NULL UNIQUE,
    policy_version_id UUID NOT NULL REFERENCES policy_versions(id) ON DELETE RESTRICT,
    provider TEXT NOT NULL CHECK (provider IN ('uniswap')),
    provider_request_id TEXT NOT NULL,
    routing TEXT NOT NULL CHECK (routing = 'CLASSIC'),
    chain_id INTEGER NOT NULL CHECK (chain_id = 8453),
    swapper_address CHAR(42) NOT NULL CHECK (swapper_address ~ '^0x[0-9a-f]{40}$'),
    token_in CHAR(42) NOT NULL CHECK (token_in = '0x833589fcd6edb6e08f4c7c32d4f71b54bda02913'),
    token_out CHAR(42) NOT NULL CHECK (token_out = '0x4200000000000000000000000000000000000006'),
    amount_in_base_units NUMERIC(78, 0) NOT NULL CHECK (amount_in_base_units > 0),
    amount_in_usdc NUMERIC(38, 6) NOT NULL CHECK (amount_in_usdc > 0),
    quoted_amount_out_base_units NUMERIC(78, 0) NOT NULL CHECK (quoted_amount_out_base_units > 0),
    min_amount_out_base_units NUMERIC(78, 0) NOT NULL CHECK (min_amount_out_base_units > 0),
    estimated_network_fee_wei NUMERIC(78, 0) NOT NULL CHECK (estimated_network_fee_wei > 0),
    slippage_bps INTEGER NOT NULL CHECK (slippage_bps BETWEEN 0 AND 100),
    requires_token_approval BOOLEAN NOT NULL,
    quoted_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('RESERVED', 'EXPIRED', 'RELEASED', 'CONSUMED', 'REJECTED')),
    provider_metadata JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (expires_at > quoted_at),
    CHECK (expires_at <= quoted_at + INTERVAL '120 seconds'),
    CHECK (amount_in_base_units = amount_in_usdc * 1000000),
    CHECK (min_amount_out_base_units <= quoted_amount_out_base_units),
    CHECK (jsonb_typeof(provider_metadata) = 'object')
);

CREATE INDEX IF NOT EXISTS quote_proposals_created_at_idx ON quote_proposals (created_at DESC);
CREATE INDEX IF NOT EXISTS quote_proposals_active_idx ON quote_proposals (chain_id, expires_at)
    WHERE status = 'RESERVED';

CREATE TABLE IF NOT EXISTS daily_risk_state (
    chain_id INTEGER NOT NULL CHECK (chain_id = 8453),
    risk_date DATE NOT NULL,
    reserved_exposure_usdc NUMERIC(38, 6) NOT NULL DEFAULT 0 CHECK (reserved_exposure_usdc >= 0),
    consumed_exposure_usdc NUMERIC(38, 6) NOT NULL DEFAULT 0 CHECK (consumed_exposure_usdc >= 0),
    realized_loss_usdc NUMERIC(38, 6) NOT NULL DEFAULT 0 CHECK (realized_loss_usdc >= 0),
    loss_stop_triggered BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (chain_id, risk_date)
);

CREATE TABLE IF NOT EXISTS exposure_reservations (
    id UUID PRIMARY KEY,
    proposal_id UUID NOT NULL UNIQUE REFERENCES quote_proposals(id) ON DELETE RESTRICT,
    chain_id INTEGER NOT NULL CHECK (chain_id = 8453),
    risk_date DATE NOT NULL,
    amount_usdc NUMERIC(38, 6) NOT NULL CHECK (amount_usdc > 0),
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'EXPIRED', 'RELEASED', 'CONSUMED')),
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    released_at TIMESTAMPTZ,
    release_reason TEXT,
    FOREIGN KEY (chain_id, risk_date) REFERENCES daily_risk_state(chain_id, risk_date) ON DELETE RESTRICT,
    CHECK (
        (status = 'ACTIVE' AND released_at IS NULL AND release_reason IS NULL)
        OR (status <> 'ACTIVE' AND released_at IS NOT NULL AND release_reason IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS exposure_reservations_active_idx
    ON exposure_reservations (chain_id, risk_date, expires_at)
    WHERE status = 'ACTIVE';

-- Future reconciliation tables.  No application path in this change inserts into
-- them; they exist so an audited receipt worker can reconcile immutable records.
CREATE TABLE IF NOT EXISTS chain_transactions (
    id UUID PRIMARY KEY,
    proposal_id UUID NOT NULL UNIQUE REFERENCES quote_proposals(id) ON DELETE RESTRICT,
    chain_id INTEGER NOT NULL CHECK (chain_id = 8453),
    tx_hash CHAR(66) NOT NULL UNIQUE CHECK (tx_hash ~ '^0x[0-9a-f]{64}$'),
    sender_address CHAR(42) NOT NULL CHECK (sender_address ~ '^0x[0-9a-f]{40}$'),
    target_address CHAR(42) NOT NULL CHECK (target_address ~ '^0x[0-9a-f]{40}$'),
    nonce NUMERIC(78, 0) NOT NULL CHECK (nonce >= 0),
    value_wei NUMERIC(78, 0) NOT NULL DEFAULT 0 CHECK (value_wei >= 0),
    calldata_sha256 CHAR(64) NOT NULL CHECK (calldata_sha256 ~ '^[0-9a-f]{64}$'),
    status TEXT NOT NULL CHECK (status IN ('SUBMITTED', 'CONFIRMED', 'REVERTED', 'DROPPED', 'REPLACED')),
    submitted_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS chain_transactions_status_idx ON chain_transactions (status, submitted_at DESC);

CREATE TABLE IF NOT EXISTS transaction_receipts (
    transaction_id UUID PRIMARY KEY REFERENCES chain_transactions(id) ON DELETE RESTRICT,
    block_number NUMERIC(78, 0) NOT NULL CHECK (block_number >= 0),
    block_hash CHAR(66) NOT NULL CHECK (block_hash ~ '^0x[0-9a-f]{64}$'),
    receipt_status BOOLEAN NOT NULL,
    gas_used NUMERIC(78, 0) NOT NULL CHECK (gas_used >= 0),
    effective_gas_price_wei NUMERIC(78, 0) NOT NULL CHECK (effective_gas_price_wei >= 0),
    total_fee_wei NUMERIC(78, 0) NOT NULL CHECK (total_fee_wei >= 0),
    confirmed_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (total_fee_wei = gas_used * effective_gas_price_wei)
);

CREATE TABLE IF NOT EXISTS fills (
    id UUID PRIMARY KEY,
    transaction_id UUID NOT NULL REFERENCES chain_transactions(id) ON DELETE RESTRICT,
    proposal_id UUID NOT NULL REFERENCES quote_proposals(id) ON DELETE RESTRICT,
    chain_id INTEGER NOT NULL CHECK (chain_id = 8453),
    token_in CHAR(42) NOT NULL CHECK (token_in ~ '^0x[0-9a-f]{40}$'),
    token_out CHAR(42) NOT NULL CHECK (token_out ~ '^0x[0-9a-f]{40}$'),
    amount_in_base_units NUMERIC(78, 0) NOT NULL CHECK (amount_in_base_units > 0),
    amount_out_base_units NUMERIC(78, 0) NOT NULL CHECK (amount_out_base_units > 0),
    observed_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS fills_proposal_idx ON fills (proposal_id, observed_at DESC);

CREATE TABLE IF NOT EXISTS ledger_entries (
    id UUID PRIMARY KEY,
    chain_id INTEGER NOT NULL CHECK (chain_id = 8453),
    proposal_id UUID REFERENCES quote_proposals(id) ON DELETE RESTRICT,
    transaction_id UUID REFERENCES chain_transactions(id) ON DELETE RESTRICT,
    entry_type TEXT NOT NULL CHECK (entry_type IN ('QUOTE_RESERVED', 'QUOTE_EXPIRED', 'QUOTE_RELEASED', 'EXPOSURE_CONSUMED', 'REALIZED_LOSS', 'NETWORK_FEE')),
    amount_usdc NUMERIC(38, 6) NOT NULL DEFAULT 0 CHECK (amount_usdc >= 0),
    amount_wei NUMERIC(78, 0) NOT NULL DEFAULT 0 CHECK (amount_wei >= 0),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (proposal_id IS NOT NULL OR transaction_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS ledger_entries_recorded_idx ON ledger_entries (recorded_at DESC);

CREATE TABLE IF NOT EXISTS risk_events (
    id UUID PRIMARY KEY,
    chain_id INTEGER NOT NULL CHECK (chain_id = 8453),
    risk_date DATE NOT NULL,
    proposal_id UUID REFERENCES quote_proposals(id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL CHECK (event_type IN ('POLICY_REJECTED', 'EXPOSURE_RESERVED', 'EXPOSURE_EXPIRED', 'DAILY_LOSS_STOP')),
    severity TEXT NOT NULL CHECK (severity IN ('INFO', 'WARNING', 'CRITICAL')),
    message TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS risk_events_date_idx ON risk_events (chain_id, risk_date, created_at DESC);

-- The application must call this function inside a SERIALIZABLE transaction.  It
-- creates a proposal and reserves daily exposure as one all-or-nothing operation.
-- It repeats monetary checks in the database so client requests cannot bypass the
-- policy validator through concurrency or a stale in-memory snapshot.
CREATE OR REPLACE FUNCTION autotrader_create_quote_proposal_and_reserve(
    p_proposal_id UUID,
    p_reservation_id UUID,
    p_idempotency_key UUID,
    p_policy_version_id UUID,
    p_provider TEXT,
    p_provider_request_id TEXT,
    p_routing TEXT,
    p_swapper_address CHAR(42),
    p_amount_in_base_units NUMERIC(78, 0),
    p_amount_in_usdc NUMERIC(38, 6),
    p_quoted_amount_out_base_units NUMERIC(78, 0),
    p_min_amount_out_base_units NUMERIC(78, 0),
    p_estimated_network_fee_wei NUMERIC(78, 0),
    p_slippage_bps INTEGER,
    p_requires_token_approval BOOLEAN,
    p_quoted_at TIMESTAMPTZ,
    p_expires_at TIMESTAMPTZ,
    p_provider_metadata JSONB,
    p_max_trade_usdc NUMERIC(38, 6),
    p_max_daily_usdc NUMERIC(38, 6),
    p_max_daily_loss_usdc NUMERIC(38, 6),
    p_max_slippage_bps INTEGER,
    p_max_network_fee_wei NUMERIC(78, 0),
    p_now TIMESTAMPTZ DEFAULT now()
) RETURNS TABLE (proposal_id UUID, reservation_id UUID, risk_date DATE, idempotent BOOLEAN)
LANGUAGE plpgsql
AS $$
DECLARE
    v_risk_date DATE := (p_now AT TIME ZONE 'UTC')::date;
    v_existing_proposal UUID;
    v_existing_reservation UUID;
    v_existing_risk_date DATE;
    v_expired_amount NUMERIC(38, 6) := 0;
    v_state daily_risk_state%ROWTYPE;
BEGIN
    IF p_provider <> 'uniswap' OR p_routing <> 'CLASSIC' THEN
        RAISE EXCEPTION 'Only the sanitised Uniswap CLASSIC quote route is permitted';
    END IF;
    IF p_amount_in_usdc <= 0 OR p_amount_in_base_units <> p_amount_in_usdc * 1000000 THEN
        RAISE EXCEPTION 'Invalid exact USDC input amount';
    END IF;
    IF p_quoted_amount_out_base_units <= 0 OR p_min_amount_out_base_units <= 0
       OR p_min_amount_out_base_units > p_quoted_amount_out_base_units THEN
        RAISE EXCEPTION 'Invalid output quote amounts';
    END IF;
    IF p_expires_at <= p_quoted_at OR p_expires_at > p_quoted_at + INTERVAL '120 seconds' OR p_expires_at <= p_now THEN
        RAISE EXCEPTION 'Quote TTL is invalid or expired';
    END IF;
    IF p_max_trade_usdc <= 0 OR p_max_daily_usdc <= 0 OR p_max_daily_loss_usdc <= 0
       OR p_max_network_fee_wei <= 0 THEN
        RAISE EXCEPTION 'A mandatory financial safety cap is unset';
    END IF;
    IF p_amount_in_usdc > p_max_trade_usdc THEN
        RAISE EXCEPTION 'Per-trade exposure cap exceeded';
    END IF;
    IF p_slippage_bps < 0 OR p_slippage_bps > p_max_slippage_bps OR p_max_slippage_bps > 100 THEN
        RAISE EXCEPTION 'Slippage cap exceeded or invalid';
    END IF;
    IF p_estimated_network_fee_wei <= 0 OR p_estimated_network_fee_wei > p_max_network_fee_wei THEN
        RAISE EXCEPTION 'Network-fee cap exceeded or unavailable';
    END IF;

    -- Idempotency is resolved before capacity is charged.  The unique key also
    -- serialises concurrent identical calls without relying on process memory.
    INSERT INTO quote_proposals (
        id, idempotency_key, policy_version_id, provider, provider_request_id,
        routing, chain_id, swapper_address, token_in, token_out,
        amount_in_base_units, amount_in_usdc, quoted_amount_out_base_units,
        min_amount_out_base_units, estimated_network_fee_wei, slippage_bps,
        requires_token_approval, quoted_at, expires_at, status, provider_metadata
    ) VALUES (
        p_proposal_id, p_idempotency_key, p_policy_version_id, p_provider,
        p_provider_request_id, p_routing, 8453, lower(p_swapper_address),
        '0x833589fcd6edb6e08f4c7c32d4f71b54bda02913',
        '0x4200000000000000000000000000000000000006',
        p_amount_in_base_units, p_amount_in_usdc, p_quoted_amount_out_base_units,
        p_min_amount_out_base_units, p_estimated_network_fee_wei, p_slippage_bps,
        p_requires_token_approval, p_quoted_at, p_expires_at, 'RESERVED', p_provider_metadata
    ) ON CONFLICT (idempotency_key) DO NOTHING
    RETURNING id INTO v_existing_proposal;

    IF v_existing_proposal IS NULL THEN
        SELECT qp.id, er.id, er.risk_date
          INTO v_existing_proposal, v_existing_reservation, v_existing_risk_date
          FROM quote_proposals qp
          JOIN exposure_reservations er ON er.proposal_id = qp.id
         WHERE qp.idempotency_key = p_idempotency_key;
        RETURN QUERY SELECT v_existing_proposal, v_existing_reservation, v_existing_risk_date, TRUE;
        RETURN;
    END IF;

    INSERT INTO daily_risk_state (chain_id, risk_date)
    VALUES (8453, v_risk_date)
    ON CONFLICT ON CONSTRAINT daily_risk_state_pkey DO NOTHING;

    SELECT * INTO v_state
      FROM daily_risk_state AS drs
     WHERE drs.chain_id = 8453 AND drs.risk_date = v_risk_date
     FOR UPDATE;

    WITH expired AS (
        UPDATE exposure_reservations AS er
           SET status = 'EXPIRED', released_at = p_now, release_reason = 'quote_ttl_elapsed'
         WHERE er.chain_id = 8453
           AND er.risk_date = v_risk_date
           AND status = 'ACTIVE'
           AND expires_at <= p_now
        RETURNING er.amount_usdc, er.proposal_id
    )
    SELECT COALESCE(SUM(amount_usdc), 0) INTO v_expired_amount FROM expired;

    IF v_expired_amount > 0 THEN
        UPDATE daily_risk_state AS drs
           SET reserved_exposure_usdc = drs.reserved_exposure_usdc - v_expired_amount,
               updated_at = p_now
         WHERE drs.chain_id = 8453 AND drs.risk_date = v_risk_date;
        UPDATE quote_proposals AS qp
           SET status = 'EXPIRED'
         WHERE qp.id IN (
            SELECT er.proposal_id FROM exposure_reservations AS er
             WHERE er.chain_id = 8453 AND er.risk_date = v_risk_date
               AND er.status = 'EXPIRED' AND er.released_at = p_now
         );
        v_state.reserved_exposure_usdc := v_state.reserved_exposure_usdc - v_expired_amount;
    END IF;

    IF v_state.realized_loss_usdc >= p_max_daily_loss_usdc OR v_state.loss_stop_triggered THEN
        RAISE EXCEPTION 'Daily realised-loss stop is active';
    END IF;
    IF v_state.reserved_exposure_usdc + v_state.consumed_exposure_usdc + p_amount_in_usdc > p_max_daily_usdc THEN
        RAISE EXCEPTION 'Daily exposure cap exceeded';
    END IF;

    INSERT INTO exposure_reservations (
        id, proposal_id, chain_id, risk_date, amount_usdc, status, expires_at
    ) VALUES (
        p_reservation_id, p_proposal_id, 8453, v_risk_date, p_amount_in_usdc, 'ACTIVE', p_expires_at
    );

    UPDATE daily_risk_state AS drs
       SET reserved_exposure_usdc = drs.reserved_exposure_usdc + p_amount_in_usdc,
           updated_at = p_now
     WHERE drs.chain_id = 8453 AND drs.risk_date = v_risk_date;

    INSERT INTO ledger_entries (id, chain_id, proposal_id, entry_type, amount_usdc, metadata)
    VALUES (
        p_reservation_id, 8453, p_proposal_id, 'QUOTE_RESERVED', p_amount_in_usdc,
        jsonb_build_object('risk_date', v_risk_date, 'expires_at', p_expires_at)
    );

    INSERT INTO risk_events (id, chain_id, risk_date, proposal_id, event_type, severity, message, metadata)
    VALUES (
        gen_random_uuid(), 8453, v_risk_date, p_proposal_id, 'EXPOSURE_RESERVED', 'INFO',
        'Quote proposal reserved daily USDC exposure.',
        jsonb_build_object('amount_usdc', p_amount_in_usdc, 'expires_at', p_expires_at)
    );

    RETURN QUERY SELECT p_proposal_id, p_reservation_id, v_risk_date, FALSE;
END;
$$;

-- A future receipt reconciler must call this function in the same transaction as
-- its immutable receipt/fill/ledger inserts.  It keeps daily loss state durable
-- and records an irreversible loss-stop event once the configured threshold is met.
CREATE OR REPLACE FUNCTION autotrader_record_realized_loss(
    p_entry_id UUID,
    p_event_id UUID,
    p_chain_id INTEGER,
    p_risk_date DATE,
    p_proposal_id UUID,
    p_loss_usdc NUMERIC(38, 6),
    p_max_daily_loss_usdc NUMERIC(38, 6),
    p_now TIMESTAMPTZ DEFAULT now()
) RETURNS BOOLEAN
LANGUAGE plpgsql
AS $$
DECLARE
    v_state daily_risk_state%ROWTYPE;
    v_triggered BOOLEAN := FALSE;
BEGIN
    IF p_chain_id <> 8453 OR p_loss_usdc <= 0 OR p_max_daily_loss_usdc <= 0 THEN
        RAISE EXCEPTION 'Invalid realised-loss recording request';
    END IF;

    INSERT INTO daily_risk_state (chain_id, risk_date)
    VALUES (p_chain_id, p_risk_date)
    ON CONFLICT ON CONSTRAINT daily_risk_state_pkey DO NOTHING;

    SELECT * INTO v_state
      FROM daily_risk_state
     WHERE chain_id = p_chain_id AND risk_date = p_risk_date
     FOR UPDATE;

    UPDATE daily_risk_state
       SET realized_loss_usdc = realized_loss_usdc + p_loss_usdc,
           loss_stop_triggered = loss_stop_triggered
                                 OR realized_loss_usdc + p_loss_usdc >= p_max_daily_loss_usdc,
           updated_at = p_now
     WHERE chain_id = p_chain_id AND risk_date = p_risk_date
     RETURNING loss_stop_triggered INTO v_triggered;

    INSERT INTO ledger_entries (id, chain_id, proposal_id, entry_type, amount_usdc, metadata)
    VALUES (p_entry_id, p_chain_id, p_proposal_id, 'REALIZED_LOSS', p_loss_usdc,
            jsonb_build_object('risk_date', p_risk_date));

    IF v_triggered AND NOT v_state.loss_stop_triggered THEN
        INSERT INTO risk_events (id, chain_id, risk_date, proposal_id, event_type, severity, message, metadata)
        VALUES (p_event_id, p_chain_id, p_risk_date, p_proposal_id, 'DAILY_LOSS_STOP', 'CRITICAL',
                'Daily realised-loss stop was triggered.',
                jsonb_build_object('realized_loss_usdc', v_state.realized_loss_usdc + p_loss_usdc));
    END IF;

    RETURN v_triggered;
END;
$$;

-- pgcrypto is required only for a database-generated audit-event UUID inside the
-- atomic reservation function.  It is enabled after the function declaration to
-- make the dependency explicit for operators.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

COMMIT;
