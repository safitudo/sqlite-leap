CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
INSERT INTO t (name) VALUES ('alpha'), ('beta'), ('gamma');
SELECT id, name FROM t ORDER BY id;
