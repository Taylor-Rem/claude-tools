// Routes: the stops for each day in order, marked done or skipped by text or here.
export default {
  table: "routes",
  title: "Routes",
  singular: "stop",
  list: [["customer", "Customer"], ["stop", "Stop"], ["job", "Job"], ["area", "Area"], ["day", "Day"], ["status", "Status"]],
  statuses: ["to do", "done", "skipped"],
  filters: [["day", "Day", "today"]],
  order: [["day", "asc"], ["stop", "asc"]],
  quick: ["done", "skipped"],
  create: [
    { name: "day", label: "Day", type: "date", required: true },
    { name: "stop", label: "Stop number", type: "number", default: "1", required: true },
    { name: "customer", label: "Customer", required: true },
    { name: "job", label: "Job (weekly service, filter clean…)" },
    { name: "area", label: "Area" },
  ],
  edit: ["status", "stop", "day", "notes"],
  touch: "updated_at",
};
