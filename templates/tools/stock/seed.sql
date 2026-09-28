-- Sample rows (the store demo's golden rows): what `db add stock --from-sheet`
-- imported from fernhill-stock.xlsx. Six are below reorder.
INSERT INTO stock (item, kind, on_hand, reorder_at, supplier, unit_cost_cents, last_counted) VALUES
  ('Cedar & Smoke 8 oz', 'Candle', 14, 10, 'Poured here', 640, '2026-09-26'),
  ('Morning Orchard 8 oz', 'Candle', 6, 10, 'Poured here', 640, '2026-09-26'),
  ('Salt Flats 8 oz', 'Candle', 22, 10, 'Poured here', 640, '2026-09-26'),
  ('Brown Butter Bakery 8 oz', 'Candle', 9, 10, 'Poured here', 690, '2026-09-26'),
  ('Canyon Rain 8 oz', 'Candle', 11, 10, 'Poured here', 640, '2026-09-26'),
  ('Fernhill Signature 14 oz', 'Candle', 4, 6, 'Poured here', 1120, '2026-09-26'),
  ('Travel tin trio', 'Candle', 12, 8, 'Poured here', 510, '2026-09-26'),
  ('Pumpkin Chai 8 oz', 'Candle', 18, 10, 'Poured here', 690, '2026-09-26'),
  ('Soy wax (10 lb bag)', 'Supply', 3, 4, 'Example Wax Supply', 3200, '2026-09-25'),
  ('Cotton wicks (100)', 'Supply', 5, 2, 'Sample Wick Works', 950, '2026-09-25'),
  ('Amber jars 8 oz (12)', 'Supply', 7, 6, 'Placeholder Glass Co.', 2100, '2026-09-25'),
  ('Tins 4 oz (24)', 'Supply', 1, 2, 'Placeholder Glass Co.', 1800, '2026-09-25'),
  ('Wick trimmers', 'Retail', 6, 4, 'Sample Wick Works', 525, '2026-09-25'),
  ('Long matches (box)', 'Retail', 10, 12, 'Example Wax Supply', 180, '2026-09-25');
