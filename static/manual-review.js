const state = {
  manuals: [],
  selected: null,
  page: 1,
  pageData: null,
  status: "unreviewed",
  zoom: "1.35",
  loading: false,
};
const basePath = window.MANUAL_REVIEW_BASE || "";

const $ = (id) => document.getElementById(id);

async function api(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

function filteredManuals() {
  const query = $("search").value.trim().toLowerCase();
  const filter = $("filter").value;
  return state.manuals.filter((manual) => {
    const matches = `${manual.title} ${manual.manual_id} ${manual.processed_filename}`
      .toLowerCase().includes(query);
    if (!matches) return false;
    if (filter === "factory") return manual.review_type === "factory_integrity";
    if (filter === "community") return manual.review_type === "community_extraction";
    if (filter === "missing") return manual.possible_missing_pages > 0;
    if (filter === "official") return manual.source_kind === "official_original";
    if (filter === "same") return manual.source_kind === "same_source";
    return true;
  });
}

function renderManuals() {
  const manuals = filteredManuals();
  $("visibleCount").textContent = `${manuals.length} shown`;
  $("manualList").innerHTML = manuals.map((manual) => `
    <button class="manual-row ${state.selected?.manual_id === manual.manual_id ? "selected" : ""}"
      data-manual="${manual.manual_id}">
      <span class="manual-title">${escapeHtml(manual.title)}</span>
      <span>${manual.review_pages}</span>
      <span class="manual-meta">
        <span>${manual.chunk_count || 0} chunks</span>
        <span>${manual.source_kind === "official_original" ? "official matched" : manual.source_kind.replace("_", " ")}</span>
        ${manual.possible_pdf_loss_pages ? `<span class="missing-count">${manual.possible_pdf_loss_pages} PDF-loss</span>` : ""}
        ${manual.possible_extraction_pages ? `<span class="missing-count">${manual.possible_extraction_pages} extraction</span>` : ""}
      </span>
    </button>`).join("");
  document.querySelectorAll("[data-manual]").forEach((button) => {
    button.addEventListener("click", () => selectManual(button.dataset.manual));
  });
}

async function selectManual(manualId) {
  state.selected = state.manuals.find((manual) => manual.manual_id === manualId);
  state.page = 1;
  renderManuals();
  $("originalName").textContent = state.selected.original_filename;
  $("processedName").textContent = state.selected.processed_filename;
  const community = state.selected.review_type === "community_extraction";
  $("leftPaneLabel").textContent = community ? "AutoDoc source PDF" : "Official original";
  $("rightPaneLabel").textContent = community ? "Extraction reference" : "Processed source";
  $("pageTotal").textContent = `of ${state.selected.review_pages}`;
  $("pageNumber").max = state.selected.review_pages;
  $("manualStatus").textContent =
    `${state.selected.title} · ${state.selected.source_kind.replaceAll("_", " ")} · original offset +${state.selected.original_page_offset}`;
  await loadPage();
}

async function loadPage() {
  if (!state.selected || state.loading) return;
  state.loading = true;
  $("pageNumber").value = state.page;
  $("saveState").textContent = "Loading…";
  const token = Date.now();
  const base = `${basePath}/api/page/${encodeURIComponent(state.selected.manual_id)}`;
  $("originalPage").src = `${base}/original/${state.page}.png?zoom=${state.zoom}&v=${token}`;
  $("processedPage").src = `${base}/processed/${state.page}.png?zoom=${state.zoom}&v=${token}`;
  try {
    state.pageData = await api(`${base}/${state.page}`);
    $("originalCount").textContent = `${state.pageData.counts.original.toLocaleString()} chars`;
    $("processedCount").textContent = `${state.pageData.counts.processed.toLocaleString()} chars`;
    $("extractedCount").textContent = `${state.pageData.counts.extracted.toLocaleString()} chars`;
    $("correctedText").value = state.pageData.editable_text;
    $("note").value = state.pageData.note;
    $("diagramFlag").checked = state.pageData.flags.has_diagram;
    $("missingFlag").checked = state.pageData.flags.possible_missing_text;
    $("ocrFlag").checked = state.pageData.flags.needs_ocr;
    state.status = state.pageData.status;
    setStatus(state.status);
    const ratio = Math.round((state.pageData.flags.processed_ratio || 0) * 100);
    const extractedRatio = Math.round((state.pageData.flags.extracted_ratio || 0) * 100);
    $("warningBox").classList.toggle("hidden", !state.pageData.flags.possible_missing_text);
    $("warningBox").textContent = state.pageData.flags.possible_pdf_text_loss
      ? `Processed readable text is ${ratio}% of the official page. Inspect the PDF conversion.`
      : (state.pageData.flags.possible_extraction_loss
        ? `Indexed text is ${extractedRatio}% of the processed page. Inspect the extraction.`
        : "");
    $("chunks").innerHTML = state.pageData.chunks.length
      ? state.pageData.chunks.map((chunk) => `
          <div class="chunk"><strong>${escapeHtml(chunk.section_title || "Untitled chunk")}</strong><br>
          ${chunk.char_count} chars · ${escapeHtml(chunk.chunk_id || "")}</div>`).join("")
      : `<div class="chunk">No indexed chunk is anchored to this page.</div>`;
    $("saveState").textContent = "";
  } catch (error) {
    $("saveState").textContent = `Error: ${error.message}`;
  } finally {
    state.loading = false;
  }
}

function setStatus(status) {
  state.status = status;
  document.querySelectorAll(".status").forEach((button) => {
    button.classList.toggle("active", button.dataset.status === status);
  });
}

async function savePage() {
  if (!state.selected) return;
  $("saveState").textContent = "Saving…";
  await api(`${basePath}/api/page/${encodeURIComponent(state.selected.manual_id)}/${state.page}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      status: state.status,
      corrected_text: $("correctedText").value,
      note: $("note").value,
    }),
  });
  $("saveState").textContent = "Saved";
  setTimeout(() => { if ($("saveState").textContent === "Saved") $("saveState").textContent = ""; }, 1800);
}

function changePage(delta) {
  if (!state.selected) return;
  state.page = Math.min(state.selected.review_pages, Math.max(1, state.page + delta));
  loadPage();
}

function syncScroll(source, target) {
  if (!$("syncScroll").checked) return;
  const maxSource = source.scrollHeight - source.clientHeight;
  const maxTarget = target.scrollHeight - target.clientHeight;
  if (maxSource > 0 && maxTarget > 0) target.scrollTop = source.scrollTop / maxSource * maxTarget;
  const maxSourceX = source.scrollWidth - source.clientWidth;
  const maxTargetX = target.scrollWidth - target.clientWidth;
  if (maxSourceX > 0 && maxTargetX > 0) target.scrollLeft = source.scrollLeft / maxSourceX * maxTargetX;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  })[character]);
}

async function init() {
  const index = await api(`${basePath}/api/manuals`);
  state.manuals = index.manuals;
  $("sourceCount").textContent =
    `${index.factory_manuals} factory manuals · ${index.community_guides} AutoDoc guides · ${index.possible_pdf_loss_pages} PDF-loss · ${index.possible_extraction_pages} extraction review`;
  renderManuals();
  if (state.manuals.length) await selectManual(state.manuals[0].manual_id);
}

$("search").addEventListener("input", renderManuals);
$("filter").addEventListener("change", renderManuals);
$("prevPage").addEventListener("click", () => changePage(-1));
$("nextPage").addEventListener("click", () => changePage(1));
$("pageNumber").addEventListener("change", () => {
  if (!state.selected) return;
  state.page = Math.min(state.selected.review_pages, Math.max(1, Number($("pageNumber").value) || 1));
  loadPage();
});
$("zoom").addEventListener("change", () => { state.zoom = $("zoom").value; loadPage(); });
$("save").addEventListener("click", savePage);
$("rebuild").addEventListener("click", async () => {
  $("rebuild").disabled = true;
  $("rebuild").textContent = "Auditing…";
  const index = await api(`${basePath}/api/rebuild-index`, { method: "POST" });
  state.manuals = index.manuals;
  $("sourceCount").textContent =
    `${index.factory_manuals} factory manuals · ${index.community_guides} AutoDoc guides · ${index.possible_pdf_loss_pages} PDF-loss · ${index.possible_extraction_pages} extraction review`;
  renderManuals();
  $("rebuild").disabled = false;
  $("rebuild").textContent = "Rebuild audit";
});
document.querySelectorAll(".status").forEach((button) => {
  button.addEventListener("click", () => setStatus(button.dataset.status));
});
const originalViewport = $("originalViewport");
const processedViewport = $("processedViewport");
originalViewport.addEventListener("scroll", () => syncScroll(originalViewport, processedViewport));
processedViewport.addEventListener("scroll", () => syncScroll(processedViewport, originalViewport));
document.addEventListener("keydown", (event) => {
  if (event.ctrlKey && event.key.toLowerCase() === "s") {
    event.preventDefault();
    savePage();
  } else if (!["TEXTAREA", "INPUT"].includes(document.activeElement.tagName)) {
    if (event.key === "ArrowLeft") changePage(-1);
    if (event.key === "ArrowRight") changePage(1);
  }
});

init().catch((error) => { $("sourceCount").textContent = `Failed: ${error.message}`; });
