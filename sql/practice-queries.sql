-- Practice queries for bokehline_practice.db (SQLite), numbered to match the exercise list in the README.

-- 1
SELECT * FROM customers;
-- 2
SELECT name, country FROM suppliers WHERE rating = 'A' ORDER BY name;
-- 3
SELECT program_code, name, sop_date FROM programs WHERE status = 'Red';
-- 4
SELECT first_name, last_name, hire_date FROM employees WHERE hire_date >= '2022-01-01' ORDER BY hire_date;
-- 5
SELECT part_number, description, unit_cost FROM parts ORDER BY unit_cost DESC LIMIT 5;
-- 6
SELECT first_name, last_name, title FROM employees WHERE salary IS NULL;
-- 7
SELECT name, commodity FROM suppliers WHERE country IN ('Thailand','China','Malaysia','Taiwan');
-- 8
SELECT segment, COUNT(*) AS customers FROM customers GROUP BY segment;
-- 9
SELECT department, COUNT(*) AS headcount, ROUND(AVG(salary)) AS avg_salary
FROM employees GROUP BY department ORDER BY avg_salary DESC;
-- 10
SELECT current_phase, COUNT(*) AS n FROM programs GROUP BY current_phase ORDER BY current_phase;
-- 11
SELECT commodity, COUNT(*) AS n FROM suppliers GROUP BY commodity HAVING COUNT(*) > 1;
-- 12
SELECT p.program_code, p.name, c.name AS customer, c.segment
FROM programs p JOIN customers c ON c.customer_id = p.customer_id ORDER BY c.segment, p.program_code;
-- 13
SELECT e.first_name || ' ' || e.last_name AS pm, COUNT(*) AS programs
FROM programs p JOIN employees e ON e.employee_id = p.program_manager_id
WHERE p.status <> 'Closed' GROUP BY pm ORDER BY programs DESC;
-- 14
SELECT c.name, COUNT(p.program_id) AS programs
FROM customers c LEFT JOIN programs p ON p.customer_id = c.customer_id
GROUP BY c.name ORDER BY programs;
-- 15
SELECT part_number, description FROM parts WHERE program_id IS NULL;
-- 16
SELECT e.first_name || ' ' || e.last_name AS employee, m.first_name || ' ' || m.last_name AS manager
FROM employees e LEFT JOIN employees m ON m.employee_id = e.manager_id ORDER BY manager;
-- 17
SELECT po.po_number, s.name, ROUND(SUM(l.qty * l.unit_price), 2) AS po_value
FROM purchase_orders po JOIN suppliers s ON s.supplier_id = po.supplier_id
JOIN po_lines l ON l.po_id = po.po_id
GROUP BY po.po_id ORDER BY po_value DESC LIMIT 10;
-- 18
SELECT s.name, s.rating, COUNT(*) AS received,
       SUM(CASE WHEN po.received_date > po.promised_date THEN 1 ELSE 0 END) AS late,
       ROUND(100.0 * SUM(CASE WHEN po.received_date <= po.promised_date THEN 1 ELSE 0 END) / COUNT(*), 1) AS on_time_pct
FROM purchase_orders po JOIN suppliers s ON s.supplier_id = po.supplier_id
WHERE po.received_date IS NOT NULL
GROUP BY s.name, s.rating ORDER BY on_time_pct;
-- 19
SELECT po_number, promised_date FROM purchase_orders
WHERE received_date IS NULL AND promised_date < '2026-11-20' ORDER BY promised_date;
-- 20
SELECT pl.plant_code, ROUND(100.0 * SUM(r.qty_scrapped) / SUM(r.qty_produced), 2) AS scrap_pct
FROM production_runs r JOIN plants pl ON pl.plant_id = r.plant_id
GROUP BY pl.plant_code ORDER BY scrap_pct DESC;
-- 21
SELECT shift, ROUND(100.0 * SUM(qty_scrapped) / SUM(qty_produced), 2) AS scrap_pct
FROM production_runs GROUP BY shift;
-- 22
SELECT strftime('%Y-%m', run_date) AS month, SUM(qty_produced) AS produced, SUM(qty_scrapped) AS scrapped
FROM production_runs GROUP BY month ORDER BY month;
-- 23
SELECT defect_type, SUM(qty) AS qty FROM defects GROUP BY defect_type ORDER BY qty DESC;
-- 24
SELECT pt.part_number, pt.description, SUM(r.qty_scrapped * pt.unit_cost) AS scrap_cost
FROM production_runs r JOIN parts pt ON pt.part_id = r.part_id
GROUP BY pt.part_id ORDER BY scrap_cost DESC LIMIT 5;
-- 25
SELECT first_name, last_name, department, salary FROM employees e
WHERE salary > (SELECT AVG(salary) FROM employees WHERE department = e.department) ORDER BY department, salary DESC;
-- 26
SELECT p.program_code, g.gate, g.planned_date, g.actual_date,
       CAST(julianday(g.actual_date) - julianday(g.planned_date) AS INTEGER) AS days_late
FROM gate_reviews g JOIN programs p ON p.program_id = g.program_id
WHERE g.actual_date > g.planned_date ORDER BY days_late DESC;
-- 27
SELECT p.program_code, p.name, p.current_phase, p.sop_date
FROM programs p WHERE p.sop_date < '2026-11-20' AND p.current_phase <> 'Closed';
-- 28
SELECT p.program_code, g.gate, g.planned_date
FROM gate_reviews g JOIN programs p ON p.program_id = g.program_id
WHERE g.actual_date IS NULL
  AND g.planned_date = (SELECT MIN(planned_date) FROM gate_reviews g2 WHERE g2.program_id = g.program_id AND g2.actual_date IS NULL)
ORDER BY g.planned_date;
-- 29
WITH part_rev AS (
  SELECT pt.program_id, SUM(r.qty_produced - r.qty_scrapped) * 1.0 AS good_units,
         SUM((r.qty_produced - r.qty_scrapped) * (pt.unit_price - pt.unit_cost)) AS margin
  FROM production_runs r JOIN parts pt ON pt.part_id = r.part_id GROUP BY pt.program_id)
SELECT pr.program_code, pr.name, ROUND(pv.margin, 2) AS margin,
       RANK() OVER (ORDER BY pv.margin DESC) AS rnk
FROM part_rev pv JOIN programs pr ON pr.program_id = pv.program_id;
-- 30
SELECT month, produced, SUM(produced) OVER (ORDER BY month) AS running_total
FROM (SELECT strftime('%Y-%m', run_date) AS month, SUM(qty_produced) AS produced FROM production_runs GROUP BY month);
-- 31
SELECT * FROM (
  SELECT pl.plant_code, r.run_date, pt.part_number, r.qty_scrapped,
         ROW_NUMBER() OVER (PARTITION BY r.plant_id ORDER BY r.qty_scrapped DESC) AS rn
  FROM production_runs r JOIN plants pl ON pl.plant_id = r.plant_id JOIN parts pt ON pt.part_id = r.part_id)
WHERE rn <= 3;
-- 32
WITH RECURSIVE chain(employee_id, name, level) AS (
  SELECT employee_id, first_name || ' ' || last_name, 0 FROM employees WHERE manager_id IS NULL
  UNION ALL
  SELECT e.employee_id, e.first_name || ' ' || e.last_name, c.level + 1
  FROM employees e JOIN chain c ON e.manager_id = c.employee_id)
SELECT level, COUNT(*) FROM chain GROUP BY level;
