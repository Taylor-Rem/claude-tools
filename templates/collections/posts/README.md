# posts — a blog or news list

**Status: scaffold — finish with the first demo that shows posts.** Only the table exists
(`migrations/0001_posts.sql`); there is no Function, no admin view and no
form yet, so `db add posts` refuses and nothing may be promised from it.
Until it is finished, a client asking for this gets the PLAYBOOK § Data
answer for things the layer can't do yet.

To finish: `functions/posts/[slug].js` rendering a post with the site's layout, an index page, an admin view with a markdown body.
