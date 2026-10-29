-- =====================================================================
-- Securities brokerage - TRADING / OMS (MySQL 8.4)
--
-- Owns: orders and their lifecycle events, executions (matched trades),
-- client login sessions and watchlists.
--
-- account_id, customer_id and instrument_id refer to the PostgreSQL core
-- database (account.accounts, customer.customers, product.instruments).
-- They are logical references: there is no FK across databases. symbol and
-- exchange_code are denormalized on purpose, as a real OMS keeps them to
-- avoid calling the core system on the hot path.
--
-- Conventions: same as postgres_core.sql; timestamps are DATETIME(6) in UTC.
-- =====================================================================

CREATE DATABASE IF NOT EXISTS oms CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE oms;

CREATE TABLE orders (
    order_id              BIGINT        NOT NULL AUTO_INCREMENT,
    order_no              VARCHAR(30)   NOT NULL COMMENT 'Business order number shown to the customer, unique per day and channel',
    account_id            BIGINT        NOT NULL COMMENT 'Logical ref to core account.accounts.account_id',
    customer_id           BIGINT        NOT NULL COMMENT 'Logical ref to core customer.customers.customer_id (denormalized)',
    instrument_id         INT           NOT NULL COMMENT 'Logical ref to core product.instruments.instrument_id',
    symbol                VARCHAR(20)   NOT NULL COMMENT 'Ticker, denormalized from product.instruments',
    exchange_code         VARCHAR(10)   NOT NULL COMMENT 'HOSE, HNX or UPCOM',
    side                  VARCHAR(4)    NOT NULL COMMENT 'BUY or SELL',
    order_type            VARCHAR(5)    NOT NULL COMMENT 'LO = limit; ATO/ATC = opening/closing auction; MP = market (HOSE); MTL/MOK/MAK = market variants (HNX); PLO = post-close limit (HNX)',
    price                 DECIMAL(18,4) NULL     COMMENT 'Limit price in VND; NULL for market and auction orders',
    quantity              BIGINT        NOT NULL COMMENT 'Ordered quantity, multiple of the lot size',
    filled_quantity       BIGINT        NOT NULL DEFAULT 0 COMMENT 'Total matched quantity so far',
    average_fill_price    DECIMAL(18,4) NULL     COMMENT 'Volume-weighted matched price',
    status                VARCHAR(20)   NOT NULL COMMENT 'PENDING_NEW -> NEW -> PARTIALLY_FILLED -> FILLED, or CANCELLED / REJECTED / EXPIRED',
    is_margin             BOOLEAN       NOT NULL DEFAULT FALSE COMMENT 'TRUE when a BUY uses margin buying power',
    channel               VARCHAR(10)   NOT NULL COMMENT 'WEB, MOBILE, BROKER (placed by a broker for the customer) or API',
    placed_by_employee_id INT           NULL     COMMENT 'Broker who entered the order when channel = BROKER',
    trade_date            DATE          NOT NULL COMMENT 'Trading day (Asia/Ho_Chi_Minh) the order belongs to',
    reject_reason         VARCHAR(200)  NULL     COMMENT 'E.g. INSUFFICIENT_BUYING_POWER, PRICE_OUT_OF_BAND, INSUFFICIENT_SECURITIES',
    created_at            DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at            DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    version               INT           NOT NULL DEFAULT 1,
    PRIMARY KEY (order_id),
    UNIQUE KEY uk_orders_order_no (order_no),
    KEY ix_orders_account_date (account_id, trade_date),
    KEY ix_orders_instrument_date (instrument_id, trade_date),
    KEY ix_orders_date_status (trade_date, status),
    CONSTRAINT ck_orders_side CHECK (side IN ('BUY','SELL')),
    CONSTRAINT ck_orders_type CHECK (order_type IN ('LO','ATO','ATC','MP','MTL','MOK','MAK','PLO')),
    CONSTRAINT ck_orders_status CHECK (status IN ('PENDING_NEW','NEW','PARTIALLY_FILLED','FILLED','CANCELLED','REJECTED','EXPIRED')),
    CONSTRAINT ck_orders_channel CHECK (channel IN ('WEB','MOBILE','BROKER','API')),
    CONSTRAINT ck_orders_qty CHECK (quantity > 0 AND filled_quantity BETWEEN 0 AND quantity),
    CONSTRAINT ck_orders_price CHECK (order_type NOT IN ('LO','PLO') OR price IS NOT NULL)
) ENGINE=InnoDB COMMENT='Customer orders (lenh dat). Current state of each order; full history is in order_events';

CREATE TABLE order_events (
    order_event_id   BIGINT        NOT NULL AUTO_INCREMENT,
    order_id         BIGINT        NOT NULL,
    event_type       VARCHAR(20)   NOT NULL COMMENT 'SUBMITTED, ACCEPTED, MODIFIED, CANCEL_REQUESTED, CANCELLED, PARTIALLY_FILLED, FILLED, REJECTED, EXPIRED',
    old_price        DECIMAL(18,4) NULL,
    new_price        DECIMAL(18,4) NULL,
    old_quantity     BIGINT        NULL,
    new_quantity     BIGINT        NULL,
    reason           VARCHAR(200)  NULL,
    source           VARCHAR(20)   NOT NULL COMMENT 'CLIENT, BROKER, EXCHANGE or SYSTEM (e.g. end-of-day expiry, force sell)',
    event_time       DATETIME(6)   NOT NULL,
    PRIMARY KEY (order_event_id),
    KEY ix_order_events_order (order_id, event_time),
    CONSTRAINT fk_order_events_order FOREIGN KEY (order_id) REFERENCES orders (order_id),
    CONSTRAINT ck_order_events_type CHECK (event_type IN ('SUBMITTED','ACCEPTED','MODIFIED','CANCEL_REQUESTED','CANCELLED','PARTIALLY_FILLED','FILLED','REJECTED','EXPIRED')),
    CONSTRAINT ck_order_events_source CHECK (source IN ('CLIENT','BROKER','EXCHANGE','SYSTEM'))
) ENGINE=InnoDB COMMENT='Append-only order lifecycle. Fast submit-then-cancel sequences are the raw signal for spoofing detection';

CREATE TABLE executions (
    execution_id       BIGINT        NOT NULL AUTO_INCREMENT,
    exchange_exec_no   VARCHAR(30)   NOT NULL COMMENT 'Match number assigned by the exchange',
    order_id           BIGINT        NOT NULL,
    account_id         BIGINT        NOT NULL COMMENT 'Logical ref to core account.accounts.account_id',
    instrument_id      INT           NOT NULL COMMENT 'Logical ref to core product.instruments.instrument_id',
    symbol             VARCHAR(20)   NOT NULL,
    side               VARCHAR(4)    NOT NULL,
    matched_quantity   BIGINT        NOT NULL,
    matched_price      DECIMAL(18,4) NOT NULL,
    matched_value      DECIMAL(20,2) NOT NULL COMMENT 'matched_quantity * matched_price',
    fee_amount         DECIMAL(20,2) NOT NULL COMMENT 'Brokerage fee from the account fee schedule',
    tax_amount         DECIMAL(20,2) NOT NULL DEFAULT 0 COMMENT 'Selling tax 0.1% of matched value, SELL only',
    trade_date         DATE          NOT NULL,
    matched_at         DATETIME(6)   NOT NULL,
    PRIMARY KEY (execution_id),
    UNIQUE KEY uk_executions_exchange_no (trade_date, exchange_exec_no),
    KEY ix_executions_order (order_id),
    KEY ix_executions_account_date (account_id, trade_date),
    KEY ix_executions_instrument_time (instrument_id, matched_at),
    CONSTRAINT fk_executions_order FOREIGN KEY (order_id) REFERENCES orders (order_id),
    CONSTRAINT ck_executions_side CHECK (side IN ('BUY','SELL')),
    CONSTRAINT ck_executions_qty CHECK (matched_quantity > 0)
) ENGINE=InnoDB COMMENT='Matched trades (lenh khop). One order can have many executions; each one produces a T+2 settlement in core';

CREATE TABLE client_sessions (
    session_id      BIGINT       NOT NULL AUTO_INCREMENT,
    customer_id     BIGINT       NOT NULL COMMENT 'Logical ref to core customer.customers.customer_id',
    channel         VARCHAR(10)  NOT NULL COMMENT 'WEB, MOBILE or API',
    device_id       VARCHAR(64)  NOT NULL COMMENT 'Hashed device fingerprint; one device shared by many customers is a fraud signal',
    ip_address      VARCHAR(45)  NOT NULL COMMENT '[PII] Client IP (v4 or v6)',
    user_agent      VARCHAR(300) NULL,
    login_result    VARCHAR(20)  NOT NULL COMMENT 'SUCCESS, WRONG_PASSWORD, WRONG_OTP, LOCKED',
    login_at        DATETIME(6)  NOT NULL,
    logout_at       DATETIME(6)  NULL,
    PRIMARY KEY (session_id),
    KEY ix_client_sessions_customer (customer_id, login_at),
    KEY ix_client_sessions_device (device_id),
    CONSTRAINT ck_client_sessions_channel CHECK (channel IN ('WEB','MOBILE','API')),
    CONSTRAINT ck_client_sessions_result CHECK (login_result IN ('SUCCESS','WRONG_PASSWORD','WRONG_OTP','LOCKED'))
) ENGINE=InnoDB COMMENT='Login attempts and sessions of trading channels';

CREATE TABLE watchlists (
    watchlist_id   BIGINT       NOT NULL AUTO_INCREMENT,
    customer_id    BIGINT       NOT NULL COMMENT 'Logical ref to core customer.customers.customer_id',
    name           VARCHAR(100) NOT NULL,
    created_at     DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (watchlist_id),
    KEY ix_watchlists_customer (customer_id)
) ENGINE=InnoDB COMMENT='Customer watchlists (danh muc theo doi) in the trading app';

CREATE TABLE watchlist_items (
    watchlist_id   BIGINT      NOT NULL,
    instrument_id  INT         NOT NULL COMMENT 'Logical ref to core product.instruments.instrument_id',
    symbol         VARCHAR(20) NOT NULL,
    added_at       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    removed_at     DATETIME(6) NULL COMMENT 'Soft delete keeps the add/remove history for recommendation models',
    PRIMARY KEY (watchlist_id, instrument_id, added_at),
    CONSTRAINT fk_watchlist_items_watchlist FOREIGN KEY (watchlist_id) REFERENCES watchlists (watchlist_id)
) ENGINE=InnoDB COMMENT='Instruments in a watchlist';
