import {
  buildMediaElement,
  fetchStories,
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
  carouselLink: document.getElementById("story-carousel-link"),
  carouselModeToggle: document.getElementById("carousel-mode-toggle"),
};

const state = {
  slide: "",
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
    renderStory(story);
  } catch (error) {
    console.error(error);
    showNotFound();
  }
}

function renderStory(story) {
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

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

init();
