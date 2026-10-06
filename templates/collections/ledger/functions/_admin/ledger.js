// How /admin shows the ledger: every receipt, newest first, the month and
// the category as choosers, the amounts added up on the totals line (so
// picking a month is "what did I spend in September"). Patch writes the rows
// from a receipt photo (`db ledger add`); the owner can add one by hand on
// /admin/ledger (functions/admin/ledger/index.js) or fix one here.
export default {
  table: "ledger",
  title: "Ledger",
  singular: "receipt",
  list: [["date", "Date"], ["vendor", "Vendor"], ["amount_cents", "Amount"], ["category", "Category"], ["note", "For"]],
  search: ["vendor", "category", "note"],
  filters: [["month", "Month"], ["category", "Category"]],
  order: [["date", "desc"], ["id", "desc"]],
  sum: ["amount_cents"],
  edit: [
    { name: "date", label: "Date", type: "date" },
    { name: "vendor", label: "Vendor" },
    { name: "amount_cents", label: "Amount (cents: 4218 = $42.18)", type: "number" },
    { name: "category", label: "Category" },
    { name: "note", label: "What it was for" },
  ],
  touch: "updated_at",
};
