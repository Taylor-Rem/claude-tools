// How /admin shows the customer book. functions/admin/customers/ has the
// customer's own page (the jobs under them, add a job, mark one done), the
// CSV import, and the add form that matches by phone or email; the list
// itself, its search and its Download CSV are the shell's.
export default {
  table: "customers",
  title: "Customers",
  singular: "customer",
  list: [["name", "Name"], ["phone", "Phone"], ["email", "Email"], ["tags", "Tags"], ["last_seen", "Last seen"]],
  search: ["name", "phone", "phone_key", "email", "address", "notes", "tags"],
  order: ["name", "asc"],
  create: [
    { name: "name", label: "Name", required: true },
    { name: "phone", label: "Phone", type: "tel" },
    { name: "email", label: "Email", type: "email" },
    { name: "address", label: "Address" },
    { name: "tags", label: "Tags (weekly, spa…)" },
    { name: "notes", label: "Notes (gate code, the dog…)", type: "textarea" },
  ],
  edit: ["name", "phone", "email", "address", "tags", "notes"],
  touch: "updated_at",
};
