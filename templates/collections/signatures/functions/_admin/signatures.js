// How /admin shows the documents sent for signing. `sign new` writes the rows;
// the customer signs on /sign/<token>; this list is the owner's record.
// Change the title or the columns here; `db add` doesn't rewrite this file.
export default {
  table: "signatures",
  title: "Signed documents",
  singular: "document",
  list: [["created_at", "Sent"], ["title", "Document"], ["for_name", "For"], ["status", "Status"], ["signed_name", "Signed by"], ["signed_at", "Signed"]],
  statuses: ["sent", "signed", "void"],
  edit: [
    { name: "notes", label: "Notes (only you see these)", type: "textarea" },
  ],
  touch: "updated_at",
};
