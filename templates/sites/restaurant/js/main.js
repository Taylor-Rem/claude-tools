/* {{NAME}} — the site's only script: fade-in reveals on scroll.
   Skipped entirely when the visitor prefers reduced motion. The CSS only
   hides .reveal elements after this file adds the js-motion class, so with
   JS off every page is complete and readable. */

(function () {
  "use strict";

  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

  document.documentElement.classList.add("js-motion");

  var revealed = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window && revealed.length) {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.15 });
    revealed.forEach(function (el) { observer.observe(el); });
  } else {
    revealed.forEach(function (el) { el.classList.add("is-visible"); });
  }
})();
