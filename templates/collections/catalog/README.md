# catalog — what the site sells (or its menu), pickup hours, Stripe Checkout, orders

**Status: ready.** A restaurant is configured exactly like a store (VISION
2026-09-24): its menu is the catalog, its hours are the pickup hours. The
texts it answers: "sell these six things", "put the menu online with
prices", "the pho is $14 now", "we're out of the lemon cake", "we close at 8
on Sundays", "who ordered today?".

What `db add catalog` puts in the repo:

| file | what it is |
|---|---|
| `migrations/NNNN_catalog.sql` | `products` (name, description, section `category`, `price_cents`, `status` on sale / sold out / hidden, `sort`) and `hours` (weekday 0 = Sunday, opens, closes, note) |
| `migrations/NNNN_orders.sql` | `orders`: one per Checkout, `pending` until Stripe says paid, then `paid` → `ready` → `collected` (or `cancelled`) |
| `functions/api/catalog.js` | `GET /api/catalog`: the products (not hidden), the hours, open now, and the checkout mode (off / test / live) |
| `functions/api/checkout.js` | `POST /api/checkout`: prices from the database, a Stripe Checkout session on the owner's own key, the order written `pending` |
| `functions/api/stripe-webhook.js` | `POST /api/stripe-webhook`: Stripe's signed word that a Checkout was paid → the order is `paid` |
| `functions/_admin/catalog.js`, `orders.js`, `hours.js` | `/admin/catalog` (Products), `/admin/orders`, `/admin/hours` |
| `shop.html` | not copied — the shop block to paste into the page's `#shop` section (`db add` prints it) |

After `db add catalog`:

1. Paste the shop block into a `<section id="shop">`. For hours on the
   page, put `<div data-hours></div>` where they go (the block fills it).
2. The items, one row each (prices in cents):
   `db exec "INSERT INTO products (name, category, price_cents, description, sort) VALUES ('Pho', 'Mains', 1400, 'Beef broth, rice noodles', 1)"`.
   The hours: `db exec "INSERT INTO hours (weekday, opens, closes) VALUES (1, '11:00', '21:00')"` per day.
3. Commit, push, `site publish <name>`. The page shows everything with the
   button "Checkout opens once Stripe is connected" until step 4.
4. Payments are the owner's own Stripe account — Taylor's step, never by
   text: they give Taylor a restricted or secret key, Taylor puts it in the
   toolbelt and runs `SITE_ADMIN=1 site checkout <name> --key-from NAME
   --webhook` (`--live` for real money). The key is a Pages secret; nobody
   prints it. Tell the client that paying online switches on once Taylor
   has set it up, and FORWARD-TO-TAYLOR it.

Everyday texts, no publish needed (the page reads the database live):

- a price: `db exec "UPDATE products SET price_cents = 1400 WHERE id = 3"` (find ids with
  `db query "SELECT id, name, category, price_cents, status FROM products ORDER BY sort, id"`)
- sold out / back: `UPDATE products SET status = 'sold out' WHERE id = 3` / `'on sale'`; off the page: `'hidden'`
- hours: `UPDATE hours SET closes = '20:00' WHERE weekday = 0`; closed a day: `DELETE FROM hours WHERE weekday = 2` (say it back)
- orders: `db query "SELECT id, created_at, name, summary, total_cents, status FROM orders WHERE status IN ('paid','ready') ORDER BY id DESC"`;
  ready: `UPDATE orders SET status = 'ready' WHERE id = 7`

What it doesn't do (say so): delivery or shipping, stock counts, sizes and
add-ons as choices (make them separate items), tips, a kitchen screen,
order tracking for the customer, POS sync, refunds (the owner's Stripe
dashboard). No percentage of orders is ever taken by the site.
