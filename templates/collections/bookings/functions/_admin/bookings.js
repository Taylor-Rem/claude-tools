// How /admin shows the bookings people made. Rename the title to the owner's
// word ("Appointments"); `db add` doesn't rewrite this file.
export default {
  table: "bookings",
  title: "Bookings",
  singular: "booking",
  list: [["starts_at", "When"], ["name", "Name"], ["phone", "Phone"], ["email", "Email"], ["status", "Status"], ["created_at", "Booked"]],
  statuses: ["requested", "confirmed", "cancelled", "done"],
  edit: [
    { name: "status", label: "Status (cancelled frees the place)", type: "select" },
    { name: "owner_notes", label: "Notes (only you see these)", type: "textarea" },
  ],
  touch: "updated_at",
};
