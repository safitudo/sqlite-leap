CREATE TABLE orders (id INTEGER PRIMARY KEY, customer TEXT, total REAL);
INSERT INTO orders (customer, total) VALUES
    ('alice', 10.50), ('bob', 5.25), ('alice', 7.75), ('bob', 100.00);
SELECT customer, COUNT(*) AS n, SUM(total) AS gross, AVG(total) AS mean
FROM orders
GROUP BY customer
HAVING SUM(total) > 10
ORDER BY customer;
