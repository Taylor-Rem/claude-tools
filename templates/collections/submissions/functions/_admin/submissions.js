// How /admin shows the submissions list. Change the title to what the owner
// calls it ("Quote requests"), or the columns; `db add` doesn't rewrite this file.
export default {
  table: "submissions",
  title: "Form submissions",
  singular: "submission",
  list: [["created_at", "Received"], ["name", "Name"], ["email", "Email"], ["form", "Form"], ["status", "Status"]],
  json: "fields",
  statuses: ["new", "replied", "done"],
  edit: [
    { name: "status", label: "Status", type: "select" },
    { name: "notes", label: "Notes (only you see these)", type: "textarea" },
  ],
  touch: "updated_at",
};
