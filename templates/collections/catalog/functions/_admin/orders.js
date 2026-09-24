// How /admin shows orders. `pending` means the customer went to Checkout and
// hasn't paid (or the webhook hasn't landed); Stripe's word turns it `paid`.
// Refunds are done in the owner's Stripe dashboard, not here.
export default {
  table: "orders",
  title: "Orders",
  singular: "order",
  list: [["created_at", "Placed"], ["name", "Name"], ["summary", "Items"], ["total_cents", "Total (cents)"], ["status", "Status"], ["mode", "Mode"]],
  json: "items",
  statuses: ["pending", "paid", "ready", "collected", "cancelled"],
  edit: [
    { name: "status", label: "Status", type: "select" },
    { name: "owner_notes", label: "Notes (only you see these)", type: "textarea" },
  ],
  touch: "updated_at",
};
