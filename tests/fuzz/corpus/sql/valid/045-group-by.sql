CREATE TABLE t (k TEXT, v INTEGER); INSERT INTO t VALUES ('a', 1), ('a', 2), ('b', 3); SELECT k, SUM(v) FROM t GROUP BY k;
