CREATE TABLE sales (region TEXT, amount INTEGER);
INSERT INTO sales VALUES
    ('east', 100), ('east', 200), ('east', 150),
    ('west', 300), ('west', 250);
SELECT region, amount,
       ROW_NUMBER() OVER (PARTITION BY region ORDER BY amount DESC) AS rank
FROM sales
ORDER BY region, rank;
