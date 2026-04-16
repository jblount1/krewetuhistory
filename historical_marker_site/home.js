import { initCarouselMode } from "./carousel-mode.js";

initCarouselMode({
  toggleButton: document.getElementById("carousel-mode-toggle"),
  enableInactivity: true,
  inactivityMs: 120000,
});
