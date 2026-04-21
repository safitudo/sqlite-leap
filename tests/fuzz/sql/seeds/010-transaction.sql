CREATE TABLE acct (id INTEGER PRIMARY KEY, balance INTEGER NOT NULL);
INSERT INTO acct VALUES (1, 100), (2, 50);
BEGIN;
UPDATE acct SET balance = balance - 30 WHERE id = 1;
UPDATE acct SET balance = balance + 30 WHERE id = 2;
COMMIT;
SELECT id, balance FROM acct ORDER BY id;
