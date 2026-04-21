import {
  buildMediaElement,
  fetchStories,
  findStoryIndexByHash,
  incrementStoryClicks,
  joinList,
  storyHash,
  storyUrl,
} from "./site-data.js";
import { getCarouselSlide, initCarouselMode, isCarouselMode, updateCarouselSlide } from "./carousel-mode.js";

const STORY_DELAY_MS = 45000;
const VIDEO_MAX_MS = 45000;
const PAUSE_RESUME_MS = 10 * 60 * 1000;
const SWIPE_THRESHOLD = 60;
const MAX_COLLAGE_ASSETS = 4;

const state = {
  payload: null,
  stories: [],
  storyIndex: 0,
  autoplayEnabled: true,
  autoplayTimer: null,
  mediaCleanup: null,
  pauseResumeTimer: null,
};

const elements = {
  autoplayToggle: document.getElementById("autoplay-toggle"),
  empty: document.getElementById("carousel-empty"),
  menu: document.getElementById("carousel-menu"),
  stage: document.getElementById("carousel-stage"),
  mediaFrame: document.getElementById("carousel-media-frame"),
  headline: document.getElementById("carousel-headline"),
  theme: document.getElementById("carousel-theme"),
  references: document.getElementById("carousel-references"),
  referenceCard: document.getElementById("carousel-reference-card"),
  copy: document.getElementById("carousel-copy"),
  assetCard: document.getElementById("carousel-asset-card"),
  assetHeading: document.getElementById("carousel-asset-heading"),
  assetDetails: document.getElementById("carousel-asset-details"),
  documentLinks: document.getElementById("carousel-document-links"),
  position: document.getElementById("carousel-position"),
  prevStory: document.getElementById("prev-story"),
  nextStory: document.getElementById("next-story"),
  viewStory: document.getElementById("view-story"),
  carouselModeToggle: document.getElementById("carousel-mode-toggle"),
};

async function init() {
  initCarouselMode({
    toggleButton: elements.carouselModeToggle,
    defaultOn: true,
    slide: getCarouselSlide(),
    enableInactivity: false,
    onModeChange() {
      if (state.stories.length) {
        renderStory();
      }
    },
  });
  bindEvents();

  try {
    state.payload = await fetchStories();
    state.stories = state.payload.stories || [];

    if (!state.stories.length) {
      showEmptyState("Rebuild the site data to publish approved stories into the carousel.");
      disableControls();
      return;
    }

    const requestedSlide = new URLSearchParams(window.location.search).get("slide");
    const requestedIndex = findStoryIndexByHash(
      state.stories,
      requestedSlide || window.location.hash.replace(/^#/, "")
    );
    state.storyIndex = requestedIndex >= 0 ? requestedIndex : 0;

    elements.empty.classList.add("hidden");
    elements.stage.classList.remove("hidden");
    renderStory();
  } catch (error) {
    console.error(error);
    showEmptyState(
      "The website data file could not be loaded. Rebuild the site data and try again."
    );
    disableControls();
  }
}

function bindEvents() {
  elements.prevStory.addEventListener("click", () => shiftStory(-1));
  elements.nextStory.addEventListener("click", () => shiftStory(1));
  elements.autoplayToggle.addEventListener("click", toggleAutoplay);
  elements.viewStory.addEventListener("click", () => {
    incrementStoryClicks(currentStory()?.submission_record_id).catch((error) => {
      console.error("Unable to track carousel story click.", error);
    });
  });
  window.addEventListener("keydown", handleKeyboard);
  ["click", "scroll", "keydown", "touchstart"].forEach((eventName) => {
    window.addEventListener(eventName, handlePausedInteraction, { passive: true });
  });

  let pointerStartX = null;
  elements.stage.addEventListener("pointerdown", (event) => {
    pointerStartX = event.clientX;
  });
  elements.stage.addEventListener("pointerup", (event) => {
    if (pointerStartX === null) {
      return;
    }
    const delta = event.clientX - pointerStartX;
    if (Math.abs(delta) > SWIPE_THRESHOLD) {
      shiftStory(delta > 0 ? -1 : 1);
    }
    pointerStartX = null;
  });
}

function handleKeyboard(event) {
  if (event.key === "ArrowRight") {
    shiftStory(1);
  } else if (event.key === "ArrowLeft") {
    shiftStory(-1);
  } else if (event.key === " ") {
    event.preventDefault();
    toggleAutoplay();
  }
}

function showEmptyState(message) {
  elements.empty.classList.remove("hidden");
  elements.stage.classList.add("hidden");
  elements.empty.querySelector("p + h2 + p").textContent = message;
}

function disableControls() {
  elements.prevStory.disabled = true;
  elements.nextStory.disabled = true;
  elements.autoplayToggle.disabled = true;
}

function currentStory() {
  return state.stories[state.storyIndex];
}

function shiftStory(direction) {
  if (!state.stories.length) {
    return;
  }
  teardownActiveMedia();
  state.storyIndex = (state.storyIndex + direction + state.stories.length) % state.stories.length;
  renderStory();
}

function renderStory() {
  const story = currentStory();
  if (!story) {
    showEmptyState("No stories are available.");
    return;
  }

  const hash = storyHash(story);
  if (hash) {
    window.location.hash = hash;
    updateCarouselSlide(hash);
  }

  const mediaStrategy = resolveMediaStrategy(story);
  updateStageLayout(mediaStrategy.layout);
  renderText(story);
  renderReferences(story.references || []);
  renderMedia(mediaStrategy);
  elements.viewStory.href = isCarouselMode()
    ? storyUrl(story, { ref: "carousel", slide: hash })
    : storyUrl(story);
  elements.position.textContent = `${state.storyIndex + 1} / ${state.stories.length}`;
  closeMenu();
  syncAutoplayButton();
  scheduleAdvance(mediaStrategy);
}

function closeMenu() {
  if (elements.menu) {
    elements.menu.open = false;
  }
}

function renderText(story) {
  const headline = story.headline || "Untitled story";
  const copy = displayExcerpt(resolveDisplayCopy(story));

  elements.theme.textContent = joinList(story.themes, "Story");
  elements.headline.textContent = headline;
  elements.copy.textContent = copy;
  applyAdaptiveType(headline, copy);
}

function renderReferences(references) {
  if (!references.length) {
    elements.referenceCard.classList.add("hidden");
    elements.references.textContent = "";
    return;
  }
  elements.referenceCard.classList.remove("hidden");
  elements.references.textContent = joinList(references, "Not provided");
}

function renderMedia(mediaStrategy) {
  elements.mediaFrame.innerHTML = "";

  if (mediaStrategy.layout === "text-only") {
    elements.mediaFrame.classList.add("hidden");
    renderAssetDetails([]);
    return;
  }

  elements.mediaFrame.classList.remove("hidden");

  if (mediaStrategy.layout.startsWith("collage")) {
    elements.mediaFrame.appendChild(buildCollage(mediaStrategy.assets));
    renderAssetDetails(mediaStrategy.assets);
    return;
  }

  const layout = mediaStrategy.layout === "video" ? "video" : "feature";
  elements.mediaFrame.appendChild(buildCarouselMedia(mediaStrategy.asset, layout));
  renderAssetDetails(mediaStrategy.detailAssets);
}

function buildCollage(assets) {
  const collage = document.createElement("div");
  collage.className = `media-collage media-collage--${Math.min(assets.length, MAX_COLLAGE_ASSETS)}`;

  assets.slice(0, MAX_COLLAGE_ASSETS).forEach((asset) => {
    const card = document.createElement("article");
    card.className = "media-collage-card";
    card.appendChild(buildCarouselMedia(asset, "collage"));
    collage.appendChild(card);
  });

  return collage;
}

function buildCarouselMedia(asset, layout) {
  const media = buildMediaElement(asset, { layout });
  if (!asset || !["image", "pdf"].includes(asset.kind)) {
    return media;
  }

  const overlayBits = [];
  if (asset.caption) {
    overlayBits.push(`<p class="media-overlay-caption">${escapeHtml(asset.caption)}</p>`);
  }
  if (asset.mla_citation) {
    overlayBits.push(`<p class="media-overlay-reference">${escapeHtml(asset.mla_citation)}</p>`);
  }

  if (!overlayBits.length) {
    return media;
  }

  const wrapper = document.createElement("div");
  wrapper.className = `carousel-media-with-overlay carousel-media-with-overlay--${layout}`;
  wrapper.appendChild(media);

  const overlay = document.createElement("div");
  overlay.className = "carousel-media-overlay";
  overlay.innerHTML = overlayBits.join("");
  wrapper.appendChild(overlay);
  return wrapper;
}

function renderAssetDetails(assets) {
  elements.assetDetails.innerHTML = "";
  elements.documentLinks.innerHTML = "";

  if (!assets.length) {
    elements.assetCard.classList.add("hidden");
    return;
  }

  const shouldHideForVisibleVisuals = assets.every(
    (asset) => asset && ["image", "pdf"].includes(asset.kind)
  );

  if (shouldHideForVisibleVisuals) {
    elements.assetCard.classList.add("hidden");
    return;
  }

  elements.assetCard.classList.remove("hidden");
  elements.assetHeading.textContent = assets.length > 1 ? "Images on this slide" : "Media details";

  assets.forEach((asset) => {
    const item = document.createElement("div");
    item.className = "asset-meta-item";
    item.innerHTML = `
      <strong>${asset.caption || asset.filename || "Untitled asset"}</strong>
      <p>${asset.mla_citation || "MLA citation not provided."}</p>
    `;
    elements.assetDetails.appendChild(item);

    if (asset.document_url) {
      const link = document.createElement("a");
      link.className = "document-link";
      link.href = asset.document_url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = asset.filename ? `Open ${asset.filename}` : "Open full PDF";
      elements.documentLinks.appendChild(link);
    }
  });
}

function resolveMediaStrategy(story) {
  const assets = story.media_assets || [];
  const videos = assets.filter((asset) => asset.kind === "video" || asset.kind === "video_embed");
  const images = assets.filter((asset) => asset.kind === "image");
  const documents = assets.filter((asset) => asset.kind === "pdf");
  const visualAssets = [...images, ...documents].slice(0, MAX_COLLAGE_ASSETS);

  if (videos.length) {
    return {
      layout: "video",
      asset: videos[0],
      detailAssets: [],
    };
  }

  if (visualAssets.length > 1) {
    return {
      layout: `collage-${visualAssets.length}`,
      assets: visualAssets,
    };
  }

  if (images.length === 1) {
    return {
      layout: "feature-left",
      asset: images[0],
      detailAssets: [images[0]],
    };
  }

  if (documents.length) {
    return {
      layout: "feature-left",
      asset: documents[0],
      detailAssets: [documents[0]],
    };
  }

  return {
    layout: "text-only",
    detailAssets: [],
  };
}

function scheduleAdvance(mediaStrategy) {
  clearAutoplayTimer();

  if (!state.autoplayEnabled || state.stories.length <= 1) {
    return;
  }

  if (mediaStrategy.layout === "video") {
    scheduleVideoAdvance(mediaStrategy);
    return;
  }

  state.autoplayTimer = window.setTimeout(() => shiftStory(1), STORY_DELAY_MS);
}

function scheduleVideoAdvance(mediaStrategy) {
  const fallbackTimer = window.setTimeout(() => shiftStory(1), VIDEO_MAX_MS);
  const video = elements.mediaFrame.querySelector("video");

  if (!video) {
    state.autoplayTimer = fallbackTimer;
    return;
  }

  const finish = () => {
    clearTimeout(fallbackTimer);
    shiftStory(1);
  };

  const scheduleByDuration = () => {
    if (!Number.isFinite(video.duration) || video.duration <= 0) {
      return;
    }
    clearTimeout(fallbackTimer);
    state.autoplayTimer = window.setTimeout(
      () => shiftStory(1),
      Math.min(video.duration * 1000, VIDEO_MAX_MS)
    );
  };

  video.addEventListener("loadedmetadata", scheduleByDuration);
  video.addEventListener("ended", finish);
  state.mediaCleanup = () => {
    video.removeEventListener("loadedmetadata", scheduleByDuration);
    video.removeEventListener("ended", finish);
  };

  if (video.readyState >= 1) {
    scheduleByDuration();
  } else {
    state.autoplayTimer = fallbackTimer;
  }
}

function clearAutoplayTimer() {
  if (state.autoplayTimer) {
    window.clearTimeout(state.autoplayTimer);
    state.autoplayTimer = null;
  }
}

function clearPauseResumeTimer() {
  if (state.pauseResumeTimer) {
    window.clearTimeout(state.pauseResumeTimer);
    state.pauseResumeTimer = null;
  }
}

function teardownActiveMedia() {
  clearAutoplayTimer();
  if (state.mediaCleanup) {
    state.mediaCleanup();
    state.mediaCleanup = null;
  }
}

function toggleAutoplay() {
  if (elements.autoplayToggle.disabled) {
    return;
  }
  state.autoplayEnabled = !state.autoplayEnabled;
  if (!state.autoplayEnabled) {
    incrementStoryClicks(currentStory()?.submission_record_id).catch((error) => {
      console.error("Unable to track carousel pause click.", error);
    });
    teardownActiveMedia();
    startPauseResumeTimer();
    syncAutoplayButton();
    return;
  }
  clearPauseResumeTimer();
  renderStory();
}

function handlePausedInteraction() {
  if (state.autoplayEnabled) {
    return;
  }
  startPauseResumeTimer();
}

function startPauseResumeTimer() {
  clearPauseResumeTimer();
  state.pauseResumeTimer = window.setTimeout(() => {
    state.pauseResumeTimer = null;
    state.autoplayEnabled = true;
    syncAutoplayButton();
    renderStory();
  }, PAUSE_RESUME_MS);
}

function syncAutoplayButton() {
  elements.autoplayToggle.textContent = state.autoplayEnabled ? "Pause" : "Play";
  elements.autoplayToggle.setAttribute("aria-pressed", String(state.autoplayEnabled));
}

function updateStageLayout(layout) {
  elements.stage.classList.remove(
    "display-stage--feature-left",
    "display-stage--feature-right",
    "display-stage--video",
    "display-stage--collage-2",
    "display-stage--collage-3",
    "display-stage--collage-4",
    "display-stage--text-only"
  );
  elements.stage.classList.add(`display-stage--${layout}`);
}

function resolveDisplayCopy(story) {
  return (
    story.ai_copy ||
    story.summary ||
    story.narrative ||
    story.context_connections ||
    "Story text will appear here once the record is ready for display."
  );
}

function displayExcerpt(text) {
  const normalized = String(text || "").replace(/\s+/g, " ").trim();
  return normalized;
}

function applyAdaptiveType(headline, copy) {
  elements.copy.classList.remove(
    "display-copy--tight",
    "display-copy--compact",
    "display-copy--comfortable"
  );
  elements.headline.classList.remove(
    "display-headline--compact",
    "display-headline--comfortable"
  );

  const copyLength = String(copy || "").length;
  const headlineLength = String(headline || "").length;

  if (copyLength > 300) {
    elements.copy.classList.add("display-copy--tight");
  } else if (copyLength > 240) {
    elements.copy.classList.add("display-copy--compact");
  } else {
    elements.copy.classList.add("display-copy--comfortable");
  }

  if (headlineLength > 56) {
    elements.headline.classList.add("display-headline--compact");
  } else {
    elements.headline.classList.add("display-headline--comfortable");
  }
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

init();
