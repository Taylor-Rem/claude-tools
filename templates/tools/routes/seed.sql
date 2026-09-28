-- Sample rows for a demo (the service demo's golden rows use these): a
-- week of stops around today, on the site's clock (Denver, UTC-6 in
-- summer), fictional customers. Today's route is under way: some done, one
-- skipped, the rest to do.
WITH s(k, stop, customer, job, area, status) AS (VALUES
  (-1, 1, 'Sam Example', 'Weekly service', 'North bench', 'done'),
  (-1, 2, 'Casey Demo', 'Weekly service', 'North bench', 'done'),
  (-1, 3, 'Jordan Placeholder', 'Filter clean', 'Old town', 'done'),
  (-1, 4, 'Avery Sample', 'Weekly service', 'Old town', 'skipped'),
  (0, 1, 'Robin Sample', 'Heater check', 'East hills', 'done'),
  (0, 2, 'Morgan Example', 'Weekly service', 'East hills', 'done'),
  (0, 3, 'Riley Placeholder', 'Weekly service', 'East hills', 'done'),
  (0, 4, 'Quinn Demo', 'Green-to-clean', 'Canal road', 'skipped'),
  (0, 5, 'Taylor Sample', 'Weekly service', 'Canal road', 'to do'),
  (0, 6, 'Drew Example', 'Salt cell clean', 'Canal road', 'to do'),
  (0, 7, 'Jamie Placeholder', 'Weekly service', 'North bench', 'to do'),
  (1, 1, 'Sam Example', 'Weekly service', 'North bench', 'to do'),
  (1, 2, 'Casey Demo', 'Pump seal', 'North bench', 'to do'),
  (1, 3, 'Avery Sample', 'Weekly service', 'Old town', 'to do'),
  (2, 1, 'Morgan Example', 'Weekly service', 'East hills', 'to do'),
  (2, 2, 'Drew Example', 'Weekly service', 'Canal road', 'to do'))
INSERT INTO routes (day, stop, customer, job, area, status)
SELECT date('now', '-6 hours', k || ' days'), stop, customer, job, area, status FROM s;
