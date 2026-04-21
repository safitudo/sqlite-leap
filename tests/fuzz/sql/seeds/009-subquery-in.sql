CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE posts (id INTEGER PRIMARY KEY, author_id INTEGER, body TEXT);
INSERT INTO users VALUES (1, 'a'), (2, 'b'), (3, 'c');
INSERT INTO posts VALUES (1, 1, 'p1'), (2, 1, 'p2'), (3, 3, 'p3');
SELECT name FROM users
WHERE id IN (SELECT DISTINCT author_id FROM posts)
ORDER BY name;
