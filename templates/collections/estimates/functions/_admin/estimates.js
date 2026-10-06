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
  // Only these two by hand: sent and accepted are written by `estimate send` and by the customer's
  // own acceptance, and setting a status back to sent would let the page take a second acceptance
  // over the first one's name. Declined or void close the page to the customer.
  quick: ["declined", "void"],
  edit: [
    { name: "owner_notes", label: "Notes (only you see these)", type: "textarea" },
  ],
  touch: "updated_at",
};
