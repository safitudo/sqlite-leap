CREATE TABLE kv (k TEXT PRIMARY KEY, v INTEGER NOT NULL);
INSERT INTO kv (k, v) VALUES ('a', 1);
INSERT INTO kv (k, v) VALUES ('a', 2)
    ON CONFLICT(k) DO UPDATE SET v = kv.v + excluded.v;
SELECT k, v FROM kv;
