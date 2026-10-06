// How /admin shows the estimates. The lines, the acceptance and the invoice
// come from `estimate` (by text); here the owner reads them, changes the
// status, and keeps notes. Rename the title to the owner's word ("Quotes");
// `db add` doesn't rewrite this file.
export default {
  table: "estimates",
  title: "Estimates",
  singular: "estimate",
  list: [["number", "No."], ["customer", "Customer"], ["total_cents", "Total"], ["status", "Status"],
         ["valid_until", "Good until"], ["accepted_name", "Accepted by"], ["accepted_at", "Accepted"]],
  json: "lines",
  sum: ["total_cents"],
  statuses: ["draft", "sent", "accepted", "declined", "void"],
  edit: [
    { name: "status", label: "Status", type: "select" },
    { name: "owner_notes", label: "Notes (only you see these)", type: "textarea" },
  ],
  touch: "updated_at",
};
