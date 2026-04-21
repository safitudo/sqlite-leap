CREATE TABLE people (id INTEGER PRIMARY KEY, email TEXT, age INTEGER);
CREATE INDEX idx_people_email ON people(email);
INSERT INTO people (email, age) VALUES
    ('a@ex.com', 30), ('b@ex.com', 25), ('c@ex.com', 40);
SELECT id, age FROM people WHERE email = 'b@ex.com';
