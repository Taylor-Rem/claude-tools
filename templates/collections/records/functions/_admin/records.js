// How /admin shows the records list. For a named list ("Customers"), copy
// this file to functions/_admin/customers.js, set title/singular and
// filter: { kind: "customer" }, and add it to collections.js — one table,
// as many lists as the owner needs.
export default {
  table: "records",
  title: "Records",
  singular: "record",
  list: [["title", "Name"], ["kind", "List"], ["status", "Status"], ["updated_at", "Changed"], ["created_at", "Added"]],
  json: "data",
  statuses: ["open", "done", "archived"],
  create: [
    { name: "title", label: "Name", required: true },
    { name: "notes", label: "Notes", type: "textarea" },
  ],
  edit: [
    { name: "title", label: "Name" },
    { name: "status", label: "Status", type: "select" },
    { name: "notes", label: "Notes", type: "textarea" },
  ],
  touch: "updated_at",
};
