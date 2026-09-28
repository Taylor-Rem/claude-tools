// Stock: made by `db add stock --from-sheet` from fernhill-stock.xlsx, sheet Stock. Change the title, the
// columns shown or the statuses here; the /admin shell does the rest (search, totals, CSV).
export default {
  table: "stock",
  title: "Stock",
  singular: "item",
  list: [["item", "Item"], ["kind", "Kind"], ["on_hand", "On hand"], ["reorder_at", "Reorder at"], ["supplier", "Supplier"], ["status", "Status"]],
  statuses: ["stocked", "discontinued"],
  order: ["item", "asc"],
  shortcuts: [["below reorder", "on_hand < reorder_at"]],
  create: [
    { name: "item", label: "Item", required: true },
    { name: "kind", label: "Kind" },
    { name: "on_hand", label: "On hand", type: "number" },
    { name: "reorder_at", label: "Reorder at", type: "number" },
    { name: "supplier", label: "Supplier" },
    { name: "unit_cost_cents", label: "Unit cost (cents: 450 = $4.50)", type: "number" },
    { name: "last_counted", label: "Last counted", type: "date" },
  ],
  edit: ["status", "on_hand", "reorder_at", "unit_cost_cents", "last_counted", "notes"],
  touch: "updated_at",
};
