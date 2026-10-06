// /api/bookings.ics?key=<key> — the owner's calendar feed (B119): every
// confirmed booking, which Google Calendar, Apple Calendar or Outlook polls
// once subscribed (`db bookings feed` prints the address and the steps). The
// key is the Pages secret BOOKINGS_FEED_KEY, kept in the site registry too; a
// wrong key or none is a plain 404, so the address can't be guessed into.
// One-way: the owner's own busy times don't close slots here.
import { calendar, sameString } from "../_lib/bookings.js";

export async function onRequestGet({ request, env }) {
  const url = new URL(request.url);
  if (!env.BOOKINGS_FEED_KEY || !sameString(url.searchParams.get("key"), env.BOOKINGS_FEED_KEY)) {
    return new Response("Not found\n", { status: 404, headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" } });
  }
  return new Response(await calendar(env, url.origin), {
    headers: {
      "content-type": "text/calendar; charset=utf-8", "cache-control": "private, max-age=300",
      "content-disposition": 'inline; filename="bookings.ics"', "x-robots-tag": "noindex",
    },
  });
}
