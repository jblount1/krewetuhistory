const MODE_KEY = "kth-carousel-mode";
const SLIDE_KEY = "kth-carousel-slide";
const OVERLAY_ID = "carousel-return-overlay";

export function initCarouselMode({
  toggleButton = null,
  defaultOn = false,
  params = new URLSearchParams(window.location.search),
  slide = "",
  enableInactivity = false,
  inactivityMs = 120000,
  countdownSeconds = 5,
  onModeChange = null,
} = {}) {
  if (params.get("ref") === "carousel") {
    setCarouselMode(true, { slide: params.get("slide") || slide });
  } else if (defaultOn && sessionStorage.getItem(MODE_KEY) === null) {
    setCarouselMode(true, { slide });
  }

  if (slide) {
    updateCarouselSlide(slide);
  }

  let cleanupInactivity = null;

  const sync = () => {
    syncToggle(toggleButton);
    if (cleanupInactivity) {
      cleanupInactivity();
      cleanupInactivity = null;
    }
    if (enableInactivity && isCarouselMode()) {
      cleanupInactivity = startInactivityReturn({ inactivityMs, countdownSeconds });
    }
    if (typeof onModeChange === "function") {
      onModeChange(isCarouselMode());
    }
  };

  if (toggleButton) {
    toggleButton.addEventListener("click", () => {
      setCarouselMode(!isCarouselMode());
      sync();
    });
  }

  sync();

  return {
    isCarouselMode,
    getCarouselReturnUrl,
    updateCarouselSlide,
    destroy() {
      if (cleanupInactivity) {
        cleanupInactivity();
        cleanupInactivity = null;
      }
    },
    sync,
  };
}

export function isCarouselMode() {
  return sessionStorage.getItem(MODE_KEY) === "on";
}

export function setCarouselMode(enabled, { slide = "" } = {}) {
  sessionStorage.setItem(MODE_KEY, enabled ? "on" : "off");
  if (slide) {
    updateCarouselSlide(slide);
  }
}

export function updateCarouselSlide(slide) {
  if (!slide) {
    return;
  }
  sessionStorage.setItem(SLIDE_KEY, slide);
}

export function getCarouselSlide() {
  return sessionStorage.getItem(SLIDE_KEY) || "";
}

export function getCarouselReturnUrl() {
  const slide = getCarouselSlide();
  if (!slide) {
    return "carousel.html";
  }
  const params = new URLSearchParams();
  params.set("slide", slide);
  return `carousel.html?${params.toString()}`;
}

function syncToggle(button) {
  if (!button) {
    return;
  }
  const active = isCarouselMode();
  button.textContent = active ? "Carousel Mode: On" : "Carousel Mode: Off";
  button.setAttribute("aria-pressed", String(active));
}

function startInactivityReturn({ inactivityMs, countdownSeconds }) {
  let inactivityTimer = null;
  let countdownTimer = null;
  let countdownValue = countdownSeconds;
  const overlay = ensureOverlay();
  const countdownNode = overlay.querySelector("[data-countdown]");
  const stayButton = overlay.querySelector("[data-stay]");

  const hideOverlay = () => {
    overlay.classList.add("hidden");
    window.clearInterval(countdownTimer);
    countdownTimer = null;
    countdownValue = countdownSeconds;
    countdownNode.textContent = String(countdownSeconds);
  };

  const redirect = () => {
    window.clearInterval(countdownTimer);
    window.location.href = getCarouselReturnUrl();
  };

  const showOverlay = () => {
    overlay.classList.remove("hidden");
    countdownValue = countdownSeconds;
    countdownNode.textContent = String(countdownValue);
    countdownTimer = window.setInterval(() => {
      countdownValue -= 1;
      countdownNode.textContent = String(Math.max(countdownValue, 0));
      if (countdownValue <= 0) {
        redirect();
      }
    }, 1000);
  };

  const reset = () => {
    if (!isCarouselMode()) {
      return;
    }
    hideOverlay();
    window.clearTimeout(inactivityTimer);
    inactivityTimer = window.setTimeout(showOverlay, inactivityMs);
  };

  const handleActivity = () => {
    if (!isCarouselMode()) {
      return;
    }
    reset();
  };

  const handleStay = () => reset();

  stayButton.addEventListener("click", handleStay);
  ["scroll", "click", "keydown", "touchstart"].forEach((eventName) => {
    window.addEventListener(eventName, handleActivity, { passive: true });
  });

  reset();

  return () => {
    window.clearTimeout(inactivityTimer);
    window.clearInterval(countdownTimer);
    stayButton.removeEventListener("click", handleStay);
    ["scroll", "click", "keydown", "touchstart"].forEach((eventName) => {
      window.removeEventListener(eventName, handleActivity, { passive: true });
    });
    hideOverlay();
  };
}

function ensureOverlay() {
  let overlay = document.getElementById(OVERLAY_ID);
  if (overlay) {
    return overlay;
  }

  overlay = document.createElement("div");
  overlay.id = OVERLAY_ID;
  overlay.className = "return-overlay hidden";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.setAttribute("aria-live", "assertive");
  overlay.innerHTML = `
    <div class="return-overlay-card">
      <p class="return-overlay-copy">Returning to the carousel…</p>
      <div class="return-countdown" data-countdown>5</div>
      <button class="primary-button button-reset" type="button" data-stay>Stay on this page</button>
    </div>
  `;
  document.body.appendChild(overlay);
  return overlay;
}
