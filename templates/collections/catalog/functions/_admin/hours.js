// How /admin shows the pickup hours: one row per open stretch (a day can have
// two: lunch and dinner). Weekday 0 is Sunday, 6 is Saturday; times are the
// site's own clock, 24-hour (11:00, 21:30).
export default {
  table: "hours",
  title: "Hours",
  singular: "opening",
  list: [["weekday", "Day (0 = Sun)"], ["opens", "Opens"], ["closes", "Closes"], ["note", "Note"]],
  create: [
    { name: "weekday", label: "Day (0 = Sunday … 6 = Saturday)", type: "number", required: true },
    { name: "opens", label: "Opens (24-hour, e.g. 11:00)", type: "time", required: true },
    { name: "closes", label: "Closes (e.g. 21:00)", type: "time", required: true },
    { name: "note", label: "Note (optional)" },
  ],
  edit: [
    { name: "opens", label: "Opens", type: "time" },
    { name: "closes", label: "Closes", type: "time" },
    { name: "note", label: "Note" },
  ],
  touch: "updated_at",
};
