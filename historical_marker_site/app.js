import {
  buildMediaElement,
  canRenderMediaAsset,
  fetchStories,
  incrementStoryClicks,
  storyExcerpt,
  storyPreviewAsset,
  storyUrl,
  uniqueValues,
} from "./site-data.js";
import { getCarouselSlide, initCarouselMode, isCarouselMode } from "./carousel-mode.js";

const state = {
  payload: null,
  stories: [],
  filteredStories: [],
  search: "",
  theme: "all",
};

const elements = {
  emptyState: document.getElementById("empty-state"),
  archiveShell: document.getElementById("stories"),
  storiesLoading: document.getElementById("stories-loading"),
  storiesEmpty: document.getElementById("stories-empty"),
  storyGrid: document.getElementById("story-grid"),
  storySearch: document.getElementById("story-search"),
  storyFilter: document.getElementById("story-filter"),
  carouselModeToggle: document.getElementById("carousel-mode-toggle"),
};

async function init() {
  initCarouselMode({
    toggleButton: elements.carouselModeToggle,
    enableInactivity: true,
    inactivityMs: 120000,
    onModeChange() {
      if (state.stories.length) {
        renderStoryGrid();
      }
    },
  });
  bindEvents();
  showLoadingState();

  try {
    state.payload = await fetchStories();
    state.stories = state.payload?.stories || [];
    populateThemeFilter();
    applyFilters();
  } catch (error) {
    console.error(error);
    showFatalEmptyState(
      "The website data file could not be loaded. Rebuild the site data and try again."
    );
  }
}

function bindEvents() {
  elements.storySearch.addEventListener("input", (event) => {
    state.search = event.target.value.trim().toLowerCase();
    applyFilters();
  });

  elements.storyFilter.addEventListener("change", (event) => {
    state.theme = event.target.value;
    applyFilters();
  });
}

function showLoadingState() {
  elements.emptyState.classList.add("hidden");
  elements.archiveShell.classList.remove("hidden");
  elements.storiesLoading.classList.remove("hidden");
  elements.storiesEmpty.classList.add("hidden");
  elements.storyGrid.innerHTML = "";
}

function populateThemeFilter() {
  const themes = uniqueValues(state.stories.flatMap((story) => story.themes || []));
  elements.storyFilter.innerHTML = "";

  const allOption = document.createElement("option");
  allOption.value = "all";
  allOption.textContent = themes.length ? "All themes" : "All stories";
  elements.storyFilter.appendChild(allOption);

  themes.forEach((theme) => {
    const option = document.createElement("option");
    option.value = theme;
    option.textContent = theme;
    elements.storyFilter.appendChild(option);
  });
}

function applyFilters() {
  const search = state.search;
  const theme = state.theme;

  state.filteredStories = state.stories.filter((story) => {
    const themeMatch = theme === "all" || (story.themes || []).includes(theme);
    const excerpt = storyExcerpt(story, 80).toLowerCase();
    const headline = String(story.headline || "").toLowerCase();
    const searchMatch = !search || headline.includes(search) || excerpt.includes(search);
    return themeMatch && searchMatch;
  });

  elements.storiesLoading.classList.add("hidden");

  if (!state.stories.length) {
    showFatalEmptyState("No approved stories are available yet.");
    return;
  }

  elements.emptyState.classList.add("hidden");
  elements.archiveShell.classList.remove("hidden");
  renderStoryGrid();
}

function showFatalEmptyState(message) {
  elements.emptyState.classList.remove("hidden");
  elements.archiveShell.classList.add("hidden");
  elements.emptyState.querySelector("[data-empty-copy]").textContent = message;
}

function renderStoryGrid() {
  elements.storyGrid.innerHTML = "";

  if (!state.filteredStories.length) {
    elements.storiesEmpty.classList.remove("hidden");
    return;
  }

  elements.storiesEmpty.classList.add("hidden");

  state.filteredStories.forEach((story) => {
    const card = document.createElement("article");
    card.className = "story-card story-card--archive";

    const previewAsset = storyPreviewAsset(story);
    if (previewAsset && canRenderMediaAsset(previewAsset)) {
      const mediaShell = document.createElement("div");
      mediaShell.className = "story-card-media-shell";
      mediaShell.appendChild(buildMediaElement(previewAsset, { layout: "card" }));
      card.appendChild(mediaShell);
    }

    const copy = document.createElement("div");
    copy.className = "story-card-copy";
    const storyHref = isCarouselMode()
      ? storyUrl(story, { ref: "carousel", slide: getCarouselSlide() || "" })
      : storyUrl(story);
    copy.innerHTML = `
      <h3>${story.headline || "Untitled story"}</h3>
      <p class="story-card-summary">${storyExcerpt(story, 80)}</p>
      <a class="story-card-link" href="${storyHref}">Read Story</a>
    `;
    const link = copy.querySelector(".story-card-link");
    if (link) {
      link.addEventListener("click", () => {
        incrementStoryClicks(story.submission_record_id).catch((error) => {
          console.error("Unable to track Explore click.", error);
        });
      });
    }
    card.appendChild(copy);

    elements.storyGrid.appendChild(card);
  });
}

init();
