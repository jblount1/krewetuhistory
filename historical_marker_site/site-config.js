const previewHost = (window.location.hostname || "").toLowerCase();
const previewParams = new URLSearchParams(window.location.search);
const previewSourceOverride = (
  previewParams.get("dataSource") ||
  previewParams.get("data_source") ||
  ""
).toLowerCase();
const previewDataSource =
  previewHost.includes("deploy-preview-") && previewSourceOverride !== "supabase"
    ? "static"
    : "supabase";

window.KTH_SITE_CONFIG = window.KTH_SITE_CONFIG || {
  dataSource: previewDataSource,
  supabaseUrl: "https://fhssutwdezceozpzghco.supabase.co",
  supabaseAnonKey: "sb_publishable_TSaDSgM1IiPAySbCd2GsRw_xp_3KVZA",
  supabaseSchema: "public",
  supabaseStoriesTable: "stories_public",
  supabaseSubmissionsTable: "submissions",
  supabaseResponsesTable: "responses",
};
