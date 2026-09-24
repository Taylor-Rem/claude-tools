// How /admin shows the times the owner opens for booking. A slot is a start
// time on the site's own clock, how long it is, and how many bookings it
// takes; closing one hides it from the calendar (bookings already made stay).
export default {
  table: "booking_slots",
  title: "Open times",
  singular: "time",
  list: [["starts_at", "Starts"], ["minutes", "Minutes"], ["capacity", "Places"], ["label", "Label"], ["status", "Status"]],
  statuses: ["open", "closed"],
  create: [
    { name: "starts_at", label: "Starts", type: "datetime-local", required: true },
    { name: "minutes", label: "Minutes", type: "number", default: "60", required: true },
    { name: "capacity", label: "Places (how many bookings it takes)", type: "number", default: "1", required: true },
    { name: "label", label: "Label (optional)" },
  ],
  edit: [
    { name: "label", label: "Label" },
    { name: "capacity", label: "Places", type: "number" },
    { name: "status", label: "Status", type: "select" },
  ],
  touch: "updated_at",
};
