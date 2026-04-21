const previewHost = (window.location.hostname || "").toLowerCase();
const previewDataSource = previewHost.includes("deploy-preview-") ? "static" : "supabase";

window.KTH_SITE_CONFIG = window.KTH_SITE_CONFIG || {
  dataSource: previewDataSource,
  supabaseUrl: "https://fhssutwdezceozpzghco.supabase.co",
  supabaseAnonKey: "sb_publishable_TSaDSgM1IiPAySbCd2GsRw_xp_3KVZA",
  supabaseSchema: "public",
  supabaseStoriesTable: "stories_public",
  supabaseSubmissionsTable: "submissions",
  supabaseResponsesTable: "responses",
};
