CREATE TABLE IF NOT EXISTS replication_test (
    id SERIAL PRIMARY KEY,
    message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO replication_test (message) VALUES ('hello from primary');


SELECT * FROM replication_test;