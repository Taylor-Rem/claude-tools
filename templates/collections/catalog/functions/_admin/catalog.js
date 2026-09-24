// How /admin shows what the site sells. Prices are in cents (1250 = $12.50).
// "sold out" stays on the page, marked; "hidden" takes it off.
export default {
  table: "products",
  title: "Products",
  singular: "product",
  list: [["name", "Name"], ["category", "Section"], ["price_cents", "Price (cents)"], ["status", "Status"], ["updated_at", "Changed"]],
  statuses: ["on sale", "sold out", "hidden"],
  create: [
    { name: "name", label: "Name", required: true },
    { name: "category", label: "Section (e.g. Mains, Candles)" },
    { name: "price_cents", label: "Price in cents (1250 = $12.50)", type: "number", required: true },
    { name: "description", label: "Description", type: "textarea" },
  ],
  edit: [
    { name: "name", label: "Name" },
    { name: "category", label: "Section" },
    { name: "price_cents", label: "Price in cents (1250 = $12.50)", type: "number" },
    { name: "description", label: "Description", type: "textarea" },
    { name: "status", label: "Status", type: "select" },
  ],
  touch: "updated_at",
};
