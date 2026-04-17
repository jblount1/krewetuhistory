import {
  buildMediaElement,
  fetchSubmissionRecordIdBySlug,
  fetchStories,
  fetchStoryResponses,
  findStoryBySlug,
} from "./site-data.js";
import { getCarouselReturnUrl, initCarouselMode } from "./carousel-mode.js";

const elements = {
  loading: document.getElementById("story-loading"),
  empty: document.getElementById("story-empty"),
  article: document.getElementById("story-article"),
  title: document.getElementById("story-title"),
  aiNote: document.getElementById("story-ai-note"),
  media: document.getElementById("story-media"),
  mediaCaption: document.getElementById("story-media-caption"),
  body: document.getElementById("story-body"),
  gallery: document.getElementById("story-gallery"),
  galleryGrid: document.getElementById("story-gallery-grid"),
  references: document.getElementById("story-references"),
  referencesList: document.getElementById("story-references-list"),
  reactions: document.getElementById("story-reactions"),
  reactionsCount: document.getElementById("story-reactions-count"),
  reactionsActions: document.getElementById("story-reactions-actions"),
  responseQr: document.getElementById("story-response-qr"),
  responseLink: document.getElementById("story-response-link"),
  reactionsSummary: document.getElementById("story-reactions-summary"),
  reactionsRating: document.getElementById("story-reactions-rating"),
  reactionsNote: document.getElementById("story-reactions-note"),
  reactionsComments: document.getElementById("story-reactions-comments"),
  reactionsComment: document.getElementById("story-reactions-comment"),
  carouselLink: document.getElementById("story-carousel-link"),
  carouselModeToggle: document.getElementById("carousel-mode-toggle"),
};

const state = {
  slide: "",
  reactionsTimer: null,
  reactionsVisibilityHandler: null,
};

async function init() {
  const params = new URLSearchParams(window.location.search);
  const slug = params.get("story");
  state.slide = params.get("slide") || slug || "";
  initCarouselMode({
    toggleButton: elements.carouselModeToggle,
    params,
    slide: state.slide,
    enableInactivity: true,
    inactivityMs: 120000,
  });

  if (!slug) {
    showNotFound();
    return;
  }

  try {
    const payload = await fetchStories();
    const story = findStoryBySlug(payload.stories || [], slug);
    if (!story) {
      showNotFound();
      return;
    }
    await renderStory(story);
  } catch (error) {
    console.error(error);
    showNotFound();
  }
}

async function renderStory(story) {
  teardownReactionRotation();
  elements.loading.classList.add("hidden");
  elements.empty.classList.add("hidden");
  elements.article.classList.remove("hidden");

  document.title = `${story.headline || "Story"} | Krewe TU History`;
  elements.title.textContent = story.headline || "Untitled story";
  elements.carouselLink.href = getCarouselReturnUrl();
  elements.carouselLink.classList.remove("hidden");

  const primaryAsset = selectPrimaryAsset(story);
  const remainingAssets = selectRemainingAssets(story, primaryAsset);

  if (primaryAsset) {
    elements.media.classList.remove("hidden");
    elements.media.innerHTML = "";
    elements.media.appendChild(buildMediaElement(primaryAsset, { layout: "detail" }));
    renderMediaCaption(primaryAsset);
  } else {
    elements.media.classList.add("hidden");
    elements.media.innerHTML = "";
    elements.mediaCaption.classList.add("hidden");
    elements.mediaCaption.innerHTML = "";
  }

  elements.body.innerHTML = buildStoryBody(story);
  renderRemainingMedia(remainingAssets);
  renderAiNote(story);
  renderReferences(story.references || []);
  await renderReactions(story);
}

function buildStoryBody(story) {
  const sections = [];

  if (hasContent(story.summary)) {
    sections.push(sectionMarkup("Summary", story.summary));
  }
  if (hasContent(story.narrative)) {
    sections.push(sectionMarkup("Narrative", story.narrative));
  }

  const contextSections = (story.context_sections || []).filter(
    (section) => section && hasContent(section.text)
  );
  if (contextSections.length) {
    sections.push(contextSectionMarkup(contextSections));
  }

  return sections.join("");
}

function sectionMarkup(title, body) {
  return `<section class="story-body-section"><h2>${title}</h2><p>${escapeHtml(body).replace(/\n/g, "<br />")}</p></section>`;
}

function contextSectionMarkup(sections) {
  const paragraphs = sections
    .map((section) => {
      const label = section.label && section.label !== "Context and Connections"
        ? `<strong>${escapeHtml(section.label)}:</strong> `
        : "";
      return `<p>${label}${escapeHtml(section.text).replace(/\n/g, "<br />")}</p>`;
    })
    .join("");
  return `<section class="story-body-section"><h2>Context & Connections</h2>${paragraphs}</section>`;
}

function renderMediaCaption(asset) {
  const parts = [];
  if (hasContent(asset?.caption)) {
    parts.push(`<p>${escapeHtml(asset.caption)}</p>`);
  }
  if (hasContent(asset?.mla_citation)) {
    parts.push(`<p class="story-media-citation">${escapeHtml(asset.mla_citation)}</p>`);
  }

  if (!parts.length) {
    elements.mediaCaption.classList.add("hidden");
    elements.mediaCaption.innerHTML = "";
    return;
  }

  elements.mediaCaption.classList.remove("hidden");
  elements.mediaCaption.innerHTML = parts.join("");
}

function renderAiNote(story) {
  const value = String(story?.ai_generated || "").trim().toLowerCase();
  if (value !== "yes") {
    elements.aiNote.classList.add("hidden");
    elements.aiNote.textContent = "";
    return;
  }

  elements.aiNote.classList.remove("hidden");
  elements.aiNote.textContent =
    "This story was shaped with AI assistance, drawing from sources and details provided by the submitter. All references used to generate this summary are cited below. The history and perspective at the heart of this story belong to the people and communities it represents.";
}

function renderReferences(references) {
  elements.referencesList.innerHTML = "";
  if (!references.length) {
    elements.references.classList.add("hidden");
    return;
  }

  elements.references.classList.remove("hidden");
  references.forEach((reference) => {
    const item = document.createElement("li");
    item.textContent = reference;
    elements.referencesList.appendChild(item);
  });
}

async function renderReactions(story) {
  const hasQr = hasContent(story?.response_qr);
  const hasLink = hasContent(story?.response_link);
  const responseCount = Number.isFinite(Number(story?.number_of_responses))
    ? Number(story.number_of_responses)
    : 0;
  const avgRating = Number.isFinite(Number(story?.avg_rating)) ? Number(story.avg_rating) : null;
  let submissionRecordId = story?.submission_record_id || null;

  let comments = [];
  if (responseCount > 0 && !submissionRecordId && hasContent(story?.story_slug)) {
    try {
      submissionRecordId = await fetchSubmissionRecordIdBySlug(story.story_slug);
    } catch (error) {
      console.error("Unable to resolve story submission id.", error);
    }
  }

  if (responseCount > 0 && hasContent(submissionRecordId)) {
    try {
      comments = await fetchStoryResponses(submissionRecordId);
    } catch (error) {
      console.error("Unable to load story reactions.", error);
    }
  }

  if (!hasQr && !hasLink && responseCount <= 0) {
    elements.reactions.classList.add("hidden");
    return;
  }

  elements.reactions.classList.remove("hidden");

  if (hasQr || hasLink) {
    elements.reactionsActions.classList.remove("hidden");
  } else {
    elements.reactionsActions.classList.add("hidden");
  }

  if (hasQr) {
    elements.responseQr.classList.remove("hidden");
    elements.responseQr.src = story.response_qr;
  } else {
    elements.responseQr.classList.add("hidden");
    elements.responseQr.removeAttribute("src");
  }

  if (hasLink) {
    elements.responseLink.classList.remove("hidden");
    elements.responseLink.href = story.response_link;
  } else {
    elements.responseLink.classList.add("hidden");
    elements.responseLink.removeAttribute("href");
  }

  if (responseCount > 0) {
    elements.reactionsCount.classList.remove("hidden");
    elements.reactionsCount.textContent = `${responseCount} reaction${responseCount === 1 ? "" : "s"}`;
    elements.reactionsSummary.classList.remove("hidden");
    renderRating(avgRating);
  } else {
    elements.reactionsCount.classList.add("hidden");
    elements.reactionsCount.textContent = "";
    elements.reactionsSummary.classList.add("hidden");
    elements.reactionsRating.innerHTML = "";
    elements.reactionsRating.setAttribute("aria-label", "Story rating unavailable");
  }

  renderReactionComments(comments);
}

function renderRating(avgRating) {
  if (!Number.isFinite(avgRating)) {
    elements.reactionsRating.innerHTML = "";
    elements.reactionsRating.setAttribute("aria-label", "Story rating unavailable");
    return;
  }

  const normalized = Math.max(0, Math.min(5, avgRating));
  const label = `${normalized.toFixed(1).replace(/\.0$/, "")} out of 5 stars`;
  elements.reactionsRating.innerHTML = buildStarMarkup(normalized);
  elements.reactionsRating.setAttribute("aria-label", label);
}

function renderReactionComments(comments) {
  teardownReactionRotation();
  const cleanedComments = comments.filter(hasContent);

  if (!cleanedComments.length) {
    elements.reactionsNote.classList.add("hidden");
    elements.reactionsComments.classList.add("hidden");
    elements.reactionsComment.textContent = "";
    return;
  }

  elements.reactionsNote.classList.remove("hidden");
  elements.reactionsComments.classList.remove("hidden");
  elements.reactionsComment.textContent = cleanedComments[0];

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (cleanedComments.length === 1 || reducedMotion) {
    return;
  }

  let activeIndex = 0;
  const rotate = () => {
    activeIndex = (activeIndex + 1) % cleanedComments.length;
    elements.reactionsComment.classList.add("is-fading");
    window.setTimeout(() => {
      elements.reactionsComment.textContent = cleanedComments[activeIndex];
      elements.reactionsComment.classList.remove("is-fading");
    }, 180);
  };

  const start = () => {
    if (state.reactionsTimer || document.visibilityState === "hidden") {
      return;
    }
    state.reactionsTimer = window.setInterval(rotate, 4000);
  };

  const stop = () => {
    if (state.reactionsTimer) {
      window.clearInterval(state.reactionsTimer);
      state.reactionsTimer = null;
    }
  };

  state.reactionsVisibilityHandler = () => {
    if (document.visibilityState === "hidden") {
      stop();
    } else {
      start();
    }
  };

  document.addEventListener("visibilitychange", state.reactionsVisibilityHandler);
  start();
}

function renderRemainingMedia(assets) {
  const galleryAssets = assets.filter((asset) => ["image", "pdf"].includes(asset?.kind));
  elements.galleryGrid.innerHTML = "";

  if (!galleryAssets.length) {
    elements.gallery.classList.add("hidden");
    return;
  }

  elements.gallery.classList.remove("hidden");
  galleryAssets.forEach((asset) => {
    const card = document.createElement("article");
    card.className = "story-gallery-card";

    const mediaShell = document.createElement("div");
    mediaShell.className = "story-gallery-media";

    if (asset.kind === "pdf" && (asset.preview_url || asset.url)) {
      const link = document.createElement("a");
      link.className = "story-gallery-link";
      link.href = asset.document_url || asset.url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.appendChild(buildMediaElement(asset, { layout: "card" }));
      mediaShell.appendChild(link);
    } else {
      mediaShell.appendChild(buildMediaElement(asset, { layout: "card" }));
    }

    const meta = document.createElement("div");
    meta.className = "story-gallery-meta";
    meta.innerHTML = `
      ${hasContent(asset.caption) ? `<p class="story-gallery-caption">${escapeHtml(asset.caption)}</p>` : ""}
      ${hasContent(asset.mla_citation) ? `<p class="story-gallery-citation">${escapeHtml(asset.mla_citation)}</p>` : ""}
    `;

    card.appendChild(mediaShell);
    if (meta.innerHTML.trim()) {
      card.appendChild(meta);
    }
    elements.galleryGrid.appendChild(card);
  });
}

function showNotFound() {
  teardownReactionRotation();
  elements.loading.classList.add("hidden");
  elements.article.classList.add("hidden");
  elements.empty.classList.remove("hidden");
}

function selectPrimaryAsset(story) {
  const assets = story?.media_assets || [];
  return (
    assets.find((asset) => asset.kind === "video_embed" || asset.kind === "video") ||
    assets.find((asset) => asset.kind === "image") ||
    assets.find((asset) => asset.kind === "pdf") ||
    null
  );
}

function selectRemainingAssets(story, primaryAsset) {
  const assets = story?.media_assets || [];
  if (!primaryAsset) {
    return assets;
  }

  let usedPrimary = false;
  return assets.filter((asset) => {
    if (!usedPrimary && asset === primaryAsset) {
      usedPrimary = true;
      return false;
    }
    return true;
  });
}

function hasContent(value) {
  return Boolean(String(value || "").trim());
}

function buildStarMarkup(rating) {
  return Array.from({ length: 5 }, (_value, index) => {
    const fill = Math.max(0, Math.min(1, rating - index));
    return `
      <span class="story-rating-star" aria-hidden="true">
        <svg viewBox="0 0 24 24" focusable="false">
          <path
            class="story-rating-star-base"
            d="M12 2.8l2.85 5.78 6.38.93-4.61 4.49 1.09 6.36L12 17.37 6.29 20.36l1.09-6.36L2.77 9.51l6.38-.93L12 2.8z"
          ></path>
          <clipPath id="story-star-fill-${index}">
            <rect x="0" y="0" width="${fill * 24}" height="24"></rect>
          </clipPath>
          <path
            class="story-rating-star-fill"
            clip-path="url(#story-star-fill-${index})"
            d="M12 2.8l2.85 5.78 6.38.93-4.61 4.49 1.09 6.36L12 17.37 6.29 20.36l1.09-6.36L2.77 9.51l6.38-.93L12 2.8z"
          ></path>
        </svg>
      </span>
    `;
  }).join("");
}

function teardownReactionRotation() {
  if (state.reactionsTimer) {
    window.clearInterval(state.reactionsTimer);
    state.reactionsTimer = null;
  }
  if (state.reactionsVisibilityHandler) {
    document.removeEventListener("visibilitychange", state.reactionsVisibilityHandler);
    state.reactionsVisibilityHandler = null;
  }
  elements.reactionsComment.classList.remove("is-fading");
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
