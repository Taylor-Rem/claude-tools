// How /admin shows every job in the customer book, newest first. A job is
// added on its customer's page (/admin/customers/<id>) or by text
// (`db jobs add`); here the owner finds one and marks it done.
export default {
  table: "jobs",
  title: "Jobs",
  singular: "job",
  list: [["date", "Date"], ["customer_name", "Customer"], ["what", "Job"], ["amount_cents", "Amount"], ["status", "Status"]],
  search: ["customer_name", "what", "notes"],
  statuses: ["booked", "done", "cancelled"],
  order: ["date", "desc"],
  sum: ["amount_cents"],
  quick: ["done"],
  edit: [
    { name: "status", label: "Status", type: "select" },
    { name: "date", label: "Date", type: "date" },
    { name: "what", label: "Job" },
    { name: "amount_cents", label: "Amount (cents: 45000 = $450.00)", type: "number" },
    "notes",
  ],
  touch: "updated_at",
};
