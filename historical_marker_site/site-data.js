const STORIES_PATH = "data/stories.json";
const DEFAULT_SITE_CONFIG = Object.freeze({
  dataSource: "static",
  supabaseUrl: "",
  supabaseAnonKey: "",
  supabaseSchema: "public",
  supabaseStoriesTable: "stories_public",
  supabaseSubmissionsTable: "submissions",
  supabaseResponsesTable: "responses",
});
const ALLOWED_VIDEO_HOSTS = ["youtube.com", "youtu.be", "youtube-nocookie.com", "vimeo.com"];
const AUTOPLAY_LAYOUTS = new Set(["video", "feature", "collage", "carousel", "gallery"]);

export async function fetchStories() {
  const config = getSiteConfig();
  if (config.dataSource === "supabase" && config.supabaseUrl && config.supabaseAnonKey) {
    try {
      return normalizeStoriesPayload(await fetchStoriesFromSupabase(config));
    } catch (error) {
      console.warn("Falling back to static story data.", error);
    }
  }
  const response = await fetch(STORIES_PATH, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Unable to load ${STORIES_PATH}: ${response.status}`);
  }
  return normalizeStoriesPayload(await response.json());
}

export async function fetchStoryResponses(submissionRecordId) {
  const config = getSiteConfig();
  if (!submissionRecordId || config.dataSource !== "supabase" || !config.supabaseUrl || !config.supabaseAnonKey) {
    return [];
  }

  const endpoint = new URL(
    `${config.supabaseUrl.replace(/\/$/, "")}/rest/v1/${encodeURIComponent(
      config.supabaseResponsesTable
    )}`
  );
  endpoint.searchParams.set("select", '*');
  endpoint.searchParams.set("submission_id", `eq.${submissionRecordId}`);
  endpoint.searchParams.set("order", "airtable_id.asc");

  const response = await fetch(endpoint.toString(), {
    headers: buildSupabaseHeaders(config),
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`Unable to load story responses: ${response.status}`);
  }

  const rows = await response.json();
  if (!Array.isArray(rows)) {
    return [];
  }
  return rows
    .filter((row) => row && row["Show response"] === true)
    .map((row) => String(row?.Response || "").trim())
    .filter(Boolean);
}

export async function fetchSubmissionRecordIdBySlug(storySlug) {
  const config = getSiteConfig();
  if (!storySlug || config.dataSource !== "supabase" || !config.supabaseUrl || !config.supabaseAnonKey) {
    return null;
  }

  const endpoint = new URL(
    `${config.supabaseUrl.replace(/\/$/, "")}/rest/v1/${encodeURIComponent(
      config.supabaseSubmissionsTable
    )}`
  );
  endpoint.searchParams.set("select", "id");
  endpoint.searchParams.set("story_slug", `eq.${storySlug}`);
  endpoint.searchParams.set("limit", "1");

  const response = await fetch(endpoint.toString(), {
    headers: buildSupabaseHeaders(config),
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`Unable to resolve submission id: ${response.status}`);
  }

  const rows = await response.json();
  if (!Array.isArray(rows) || !rows.length) {
    return null;
  }
  return rows[0]?.id || null;
}

export function incrementStoryClicks(submissionRecordId) {
  const config = getSiteConfig();
  if (!submissionRecordId || config.dataSource !== "supabase" || !config.supabaseUrl || !config.supabaseAnonKey) {
    return Promise.resolve();
  }

  const endpoint = `${config.supabaseUrl.replace(/\/$/, "")}/rest/v1/rpc/increment_clicks`;
  return fetch(endpoint, {
    method: "POST",
    headers: {
      ...buildSupabaseHeaders(config),
      "Content-Type": "application/json",
      Prefer: "return=minimal",
    },
    body: JSON.stringify({ story_id: submissionRecordId }),
    keepalive: true,
  }).then((response) => {
    if (!response.ok) {
      throw new Error(`Unable to increment clicks: ${response.status}`);
    }
  });
}

export function uniqueValues(values) {
  return [...new Set(values.filter(Boolean))].sort((left, right) =>
    String(left).localeCompare(String(right))
  );
}

export function joinList(values, fallback = "Unknown") {
  return values && values.length ? values.join(" • ") : fallback;
}

export function getKeywordValues(story) {
  return story?.keywords || [];
}

export function storyHash(story) {
  return story?.story_slug || "";
}

export function storyUrl(story, options = {}) {
  const params = new URLSearchParams();
  const slug = storyHash(story);
  if (slug) {
    params.set("story", slug);
  }
  if (options.ref) {
    params.set("ref", options.ref);
  }
  if (options.slide) {
    params.set("slide", options.slide);
  }
  return `story.html?${params.toString()}`;
}

export function findStoryIndexByHash(stories, hash) {
  if (!hash) {
    return -1;
  }
  return stories.findIndex((story) => storyHash(story) === hash);
}

export function findStoryBySlug(stories, slug) {
  if (!slug) {
    return null;
  }
  return stories.find((story) => storyHash(story) === slug) || null;
}

export function formatTimestamp(value) {
  if (!value) {
    return "Unavailable";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Unavailable";
  }
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "long",
    timeStyle: "short",
  }).format(date);
}

export function storyExcerpt(story, maxLength = 80) {
  const source = [story?.summary, story?.narrative, story?.context_connections]
    .map((value) => String(value || "").replace(/\s+/g, " ").trim())
    .find(Boolean);

  if (!source) {
    return "A closer look at this story.";
  }
  if (source.length <= maxLength) {
    return source;
  }

  const clipped = source.slice(0, maxLength);
  const cutoff = clipped.lastIndexOf(" ");
  return `${(cutoff > 30 ? clipped.slice(0, cutoff) : clipped).trim()}…`;
}

export function canRenderMediaAsset(asset) {
  if (!asset) {
    return false;
  }
  if (asset.kind === "image") {
    return Boolean(asset.url);
  }
  if (asset.kind === "pdf") {
    return Boolean(asset.preview_url || asset.document_url || asset.url);
  }
  if (asset.kind === "video" || asset.kind === "video_embed") {
    return isAllowedVideoUrl(asset.url);
  }
  if (asset.kind === "external") {
    return Boolean(resolveEmbeddableVideoUrl(asset));
  }
  return false;
}

export function getSiteConfig() {
  return { ...DEFAULT_SITE_CONFIG, ...(window.KTH_SITE_CONFIG || {}) };
}

export function storyPreviewAsset(story) {
  const assets = story?.media_assets || [];
  return (
    assets.find((asset) => asset.kind === "image" && canRenderMediaAsset(asset)) ||
    assets.find((asset) => asset.kind === "pdf" && canRenderMediaAsset(asset)) ||
    assets.find(
      (asset) =>
        (asset.kind === "video_embed" || asset.kind === "video" || asset.kind === "external") &&
        canRenderMediaAsset(asset)
    ) ||
    null
  );
}

export function buildMediaElement(asset, { layout = "detail" } = {}) {
  if (!asset) {
    return buildMissingAssetPlaceholder(layout);
  }

  if (asset.kind === "image" && asset.url) {
    const image = document.createElement("img");
    image.className = `asset-media asset-media--${layout}`;
    image.src = asset.url;
    image.alt = asset.caption || asset.filename || "Story image";
    return image;
  }

  if (asset.kind === "pdf" && asset.preview_url) {
    const image = document.createElement("img");
    image.className = `asset-media asset-media--${layout} asset-media--pdf-preview`;
    image.src = asset.preview_url;
    image.alt = asset.caption || asset.filename || "PDF preview";
    return image;
  }

  if (asset.kind === "pdf" && (asset.document_url || asset.url)) {
    const wrapper = document.createElement("div");
    wrapper.className = "document-card";
    wrapper.innerHTML = `
      <strong>${asset.filename || "Document asset"}</strong>
      <p>${asset.caption || "Open the source PDF in a new tab."}</p>
      <a class="document-link" href="${asset.document_url || asset.url}" target="_blank" rel="noreferrer">Open PDF</a>
    `;
    return wrapper;
  }

  if (asset.kind === "video" || asset.kind === "video_embed" || asset.kind === "external") {
    const embeddableUrl = resolveEmbeddableVideoUrl(asset);
    if (!isAllowedVideoUrl(embeddableUrl)) {
      return buildVideoUnavailable(layout);
    }

    const frame = document.createElement("iframe");
    frame.className = `asset-embed asset-embed--${layout}`;
    frame.src = withVideoParams(embeddableUrl, {
      autoplay: AUTOPLAY_LAYOUTS.has(layout),
      asset,
    });
    frame.title = asset.caption || asset.filename || "Embedded video";
    frame.allow =
      "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share";
    frame.referrerPolicy = "strict-origin-when-cross-origin";
    frame.allowFullscreen = true;
    return frame;
  }

  return buildMissingAssetPlaceholder(layout);
}

export function isAllowedVideoUrl(url) {
  if (!url) {
    return false;
  }
  try {
    const parsed = new URL(url, window.location.href);
    const host = parsed.hostname.toLowerCase();
    return ALLOWED_VIDEO_HOSTS.some((marker) => host.includes(marker));
  } catch (_error) {
    return false;
  }
}

function buildMissingAssetPlaceholder(layout) {
  const placeholder = document.createElement("div");
  placeholder.className = `asset-placeholder asset-placeholder--${layout}`;
  placeholder.innerHTML = `
    <strong>No public asset is attached to this story yet.</strong>
    <p>Add an approved image or PDF attachment in Airtable to display media here.</p>
  `;
  return placeholder;
}

function buildVideoUnavailable(layout) {
  const placeholder = document.createElement("div");
  placeholder.className = `asset-placeholder asset-placeholder--${layout} asset-placeholder--video`;
  placeholder.innerHTML = `
    <strong>Video unavailable</strong>
    <p>This story's video could not be loaded.</p>
  `;
  return placeholder;
}

async function fetchStoriesFromSupabase(config) {
  const endpoint = new URL(
    `${config.supabaseUrl.replace(/\/$/, "")}/rest/v1/${encodeURIComponent(
      config.supabaseStoriesTable
    )}`
  );
  endpoint.searchParams.set("select", "story_slug,workflow_status,date_received,payload");
  endpoint.searchParams.set("order", "date_received.desc.nullslast");

  const response = await fetch(endpoint.toString(), {
    headers: buildSupabaseHeaders(config),
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`Unable to load Supabase stories: ${response.status}`);
  }

  const rows = await response.json();
  const stories = rows
    .map((row) => normalizeSupabaseStory(row))
    .filter(Boolean)
    .filter((story) => {
      const status = String(story.workflow_status || "").trim().toLowerCase();
      return status === "approved" || status === "approved and published";
    })
    .sort((left, right) => compareStoryOrder(left, right));

  return {
    generated_at: new Date().toISOString(),
    source_mode: "supabase",
    source_label: "Approved stories",
    public_publish_ready: true,
    story_count: stories.length,
    stories,
  };
}

function buildSupabaseHeaders(config) {
  return {
    apikey: config.supabaseAnonKey,
    Authorization: `Bearer ${config.supabaseAnonKey}`,
    Accept: "application/json",
    "Accept-Profile": config.supabaseSchema || "public",
    "Content-Profile": config.supabaseSchema || "public",
  };
}

function normalizeSupabaseStory(row) {
  if (!row || typeof row !== "object") {
    return null;
  }

  const payload = row.payload && typeof row.payload === "object" ? row.payload : {};
  const story = {
    ...payload,
    media_assets: Array.isArray(payload.media_assets)
      ? payload.media_assets.map((asset) => normalizeStoryMediaAsset(asset))
      : [],
    story_slug: payload.story_slug || row.story_slug || "",
    workflow_status: payload.workflow_status || row.workflow_status || "",
    date_received: payload.date_received || row.date_received || "",
  };

  return story.story_slug ? story : null;
}

function normalizeStoriesPayload(payload) {
  if (!payload || typeof payload !== "object") {
    return payload;
  }

  return {
    ...payload,
    stories: Array.isArray(payload.stories)
      ? payload.stories.map((story) => normalizeStoryRecord(story)).filter(Boolean)
      : [],
  };
}

function normalizeStoryRecord(story) {
  if (!story || typeof story !== "object") {
    return null;
  }

  return {
    ...story,
    media_assets: Array.isArray(story.media_assets)
      ? story.media_assets.map((asset) => normalizeStoryMediaAsset(asset))
      : [],
  };
}

function normalizeStoryMediaAsset(asset) {
  if (!asset || typeof asset !== "object") {
    return asset;
  }

  const embeddableUrl = resolveEmbeddableVideoUrl(asset);
  if (!embeddableUrl) {
    return asset;
  }

  return {
    ...asset,
    kind: "video_embed",
    url: embeddableUrl,
    source_url: asset.source_url || asset.url,
  };
}

function compareStoryOrder(left, right) {
  const leftOrder = Number.isFinite(Number(left?.publish_order)) ? Number(left.publish_order) : null;
  const rightOrder = Number.isFinite(Number(right?.publish_order)) ? Number(right.publish_order) : null;

  if (leftOrder !== null && rightOrder !== null && leftOrder !== rightOrder) {
    return leftOrder - rightOrder;
  }
  if (leftOrder !== null && rightOrder === null) {
    return -1;
  }
  if (leftOrder === null && rightOrder !== null) {
    return 1;
  }

  const leftDate = Date.parse(String(left?.date_received || "")) || 0;
  const rightDate = Date.parse(String(right?.date_received || "")) || 0;
  if (leftDate !== rightDate) {
    return rightDate - leftDate;
  }

  return String(left?.headline || "").localeCompare(String(right?.headline || ""));
}

function withVideoParams(url, { autoplay = false, asset = null } = {}) {
  try {
    const parsed = new URL(url, window.location.href);
    const host = parsed.hostname.toLowerCase();
    const isShortSource = String(asset?.source_url || asset?.url || "").includes("/shorts/");

    if (autoplay) {
      parsed.searchParams.set("autoplay", "1");
      parsed.searchParams.set("mute", "1");
      parsed.searchParams.set("playsinline", "1");
    } else {
      parsed.searchParams.delete("autoplay");
      parsed.searchParams.delete("mute");
      parsed.searchParams.delete("playsinline");
    }

    if (host.includes("youtube.com") || host.includes("youtu.be") || host.includes("youtube-nocookie.com")) {
      if (isShortSource) {
        parsed.searchParams.set("feature", "oembed");
      } else {
        parsed.searchParams.set("enablejsapi", "1");
        parsed.searchParams.set("rel", "0");
        parsed.searchParams.set("cc_load_policy", "1");
        parsed.searchParams.set("cc_lang_pref", "en");
        parsed.searchParams.set("hl", "en");
      }
    }

    if (host.includes("vimeo.com")) {
      parsed.searchParams.set("autopause", "0");
      parsed.searchParams.set("background", "0");
      parsed.searchParams.set("texttrack", "en");
    }

    return parsed.toString();
  } catch (_error) {
    return url;
  }
}

function resolveEmbeddableVideoUrl(asset) {
  const candidates = [asset?.url, asset?.source_url];
  for (const candidate of candidates) {
    const normalized = normalizeVideoEmbedUrl(candidate);
    if (normalized && isAllowedVideoUrl(normalized)) {
      return normalized;
    }
  }
  return null;
}

function normalizeVideoEmbedUrl(url) {
  if (!url) {
    return null;
  }

  try {
    const parsed = new URL(url, window.location.href);
    const host = parsed.hostname.toLowerCase();

    if (host.includes("youtu.be")) {
      const videoId = parsed.pathname.replace(/^\/+/, "").split("/", 1)[0];
      return videoId ? `https://www.youtube.com/embed/${videoId}` : null;
    }

    if (host.includes("youtube.com") || host.includes("youtube-nocookie.com")) {
      if (parsed.pathname === "/watch") {
        const videoId = parsed.searchParams.get("v");
        return videoId ? `https://www.youtube.com/embed/${videoId}?feature=oembed` : null;
      }
      if (parsed.pathname.startsWith("/shorts/")) {
        const videoId = parsed.pathname.split("/shorts/", 1)[1].split("/", 1)[0];
        return videoId ? `https://www.youtube.com/embed/${videoId}` : null;
      }
      if (parsed.pathname.startsWith("/embed/")) {
        const videoId = parsed.pathname.split("/embed/", 1)[1].split("/", 1)[0];
        return videoId ? `https://www.youtube.com/embed/${videoId}` : null;
      }
    }

    if (host.includes("vimeo.com")) {
      const videoId = parsed.pathname.replace(/^\/+/, "").split("/", 1)[0];
      return /^\d+$/.test(videoId) ? `https://player.vimeo.com/video/${videoId}` : null;
    }
  } catch (_error) {
    return null;
  }

  return null;
}
