const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const state = { status: null, busy: false };
const messages = $("#messages");
const welcome = $("#welcome");
const form = $("#composer");
const question = $("#question");
const send = $("#send");

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
  })[char]);
}

function answerHtml(text) {
  let html = escapeHtml(text)
    .replace(/\n{2,}/g, "</p><p>")
    .replace(/\n/g, "<br>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(
    /\[Manual:\s*([^\],]+),\s*Page\s*(\d+)\]/g,
    (_, manual, page) => `<a href="/viewer?manual=${encodeURIComponent(manual.trim())}&page=${page}" target="_blank">[${escapeHtml(manual.trim())} · p.${page}]</a>`
  );
  return `<p>${html}</p>`;
}

async function loadStatus() {
  try {
    const response = await fetch("/status");
    state.status = await response.json();
    const s = state.status;
    $("#ollama-status").textContent = s.ollama_ok ? `${s.model} connected` : "Ollama offline";
    $("#ollama-status").classList.toggle("offline", !s.ollama_ok);
    $("#manual-count").textContent = s.ready ? `${s.manuals} manuals · ${s.chunks.toLocaleString()} chunks` : "No manuals indexed";
    $("#settings-data").textContent = s.data_dir;
    $("#settings-embedder").textContent = s.embedder;
    $("#settings-model").textContent = s.model;
    $("#settings-ollama").textContent = s.ollama;
    $("#data-path").textContent = s.data_dir;

    const dot = $(".ready-dot");
    dot.className = `ready-dot ${s.ready ? "ok" : "error"}`;
    $("#rail-state").textContent = s.ready ? "Ready" : "Setup";

    if (s.ready) {
      $("#welcome-title").textContent = "Factory-grounded answers";
      $("#welcome-copy").textContent = "Ask about your 2014 CC. Every technical answer is grounded in indexed factory manuals, numerically verified, and linked to its source page.";
      $("#starter-questions").classList.remove("hidden");
      $("#open-data-folder").classList.add("hidden");
      $("#data-path").classList.add("hidden");
      question.disabled = false;
    } else {
      $("#welcome-title").textContent = "No manuals indexed yet";
      $("#welcome-copy").textContent = "Copy an existing processed out folder into the data location below, or run the ingestion tools against your factory-manual PDFs.";
      $("#starter-questions").classList.add("hidden");
      $("#data-path").classList.remove("hidden");
      $("#open-data-folder").classList.toggle("hidden", !s.desktop);
      question.disabled = true;
    }
  } catch {
    $(".ready-dot").className = "ready-dot error";
    $("#rail-state").textContent = "Offline";
    $("#manual-count").textContent = "Server unavailable";
  }
}

function appendUser(text) {
  welcome?.remove();
  messages.insertAdjacentHTML("beforeend", `
    <article class="message user-message">
      <div class="message-body">${escapeHtml(text)}</div>
    </article>`);
  messages.scrollTop = messages.scrollHeight;
}

function appendTyping() {
  const node = document.createElement("article");
  node.className = "message answer-card";
  node.innerHTML = `<div class="typing"><i></i><i></i><i></i></div>`;
  messages.appendChild(node);
  messages.scrollTop = messages.scrollHeight;
  return node;
}

function sourceCards(citations = []) {
  if (!citations.length) return "";
  return `<section class="sources"><h3>Factory manual sources</h3>${citations.map(c => `
    <button class="source-card"
      data-url="${escapeHtml(c.viewer_url)}"
      data-title="${escapeHtml(c.manual_title)}"
      data-section="${escapeHtml(c.section_title || c.manual_id)}">
      <strong>${escapeHtml(c.manual_title)}</strong>
      <small>${escapeHtml(c.section_title || c.manual_id)}</small>
      <span>Page ${c.page_physical}</span>
    </button>`).join("")}</section>`;
}

function videoCards(videos = []) {
  if (!videos.length) return "";
  return `<section class="sources"><h3>Video sources</h3>${videos.map(v => `
    <a class="video-source" href="${escapeHtml(v.citation_url || "#")}" target="_blank" rel="noopener">
      ${v.frame_url ? `<img src="${escapeHtml(v.frame_url)}" alt="" data-lightbox>` : ""}
      <span><strong>${escapeHtml(v.title)}</strong><small>${escapeHtml(v.channel)} · ~${escapeHtml(v.timestamp_label)}</small></span>
    </a>`).join("")}</section>`;
}

function appendAnswer(data) {
  const warning = (data.conflicts || []).length
    ? `<div class="warning"><span>⚠</span><div><strong>Safety warning</strong><br>${escapeHtml(data.conflicts.join(" "))}</div></div>`
    : "";
  const verified = data.verified
    ? "All numeric specifications verified"
    : "Source-grounded response";
  const article = document.createElement("article");
  article.className = "message answer-card";
  article.innerHTML = `
    <div class="answer-head">
      <div class="verify-seal">✓</div>
      <div><strong>Grounded answer</strong><small>Sourced from factory manuals</small></div>
      <span class="verify-label">${verified}</span>
    </div>
    <div class="answer-copy">${answerHtml(data.answer)}</div>
    ${warning}
    ${sourceCards(data.citations)}
    ${videoCards(data.video_citations)}`;
  messages.appendChild(article);
  messages.scrollTop = messages.scrollHeight;
}

function appendError(message) {
  messages.insertAdjacentHTML("beforeend", `<article class="message error-card">${escapeHtml(message)}</article>`);
  messages.scrollTop = messages.scrollHeight;
}

form.addEventListener("submit", async event => {
  event.preventDefault();
  const text = question.value.trim();
  if (!text || state.busy) return;
  appendUser(text);
  question.value = "";
  question.style.height = "auto";
  state.busy = true;
  send.disabled = true;
  const typing = appendTyping();
  try {
    const response = await fetch("/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ q: text })
    });
    const data = await response.json();
    typing.remove();
    if (!response.ok) throw new Error(data.message || data.error || "The request failed.");
    appendAnswer(data);
  } catch (error) {
    typing.remove();
    appendError(error.message);
  } finally {
    state.busy = false;
    send.disabled = false;
    question.focus();
  }
});

question.addEventListener("input", () => {
  question.style.height = "auto";
  question.style.height = `${Math.min(question.scrollHeight, 140)}px`;
});
question.addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

$("#starter-questions").addEventListener("click", event => {
  const button = event.target.closest("button");
  if (!button) return;
  question.value = button.textContent;
  form.requestSubmit();
});

document.addEventListener("click", event => {
  const source = event.target.closest(".source-card");
  if (source) {
    $$(".source-card").forEach(card => card.classList.remove("selected"));
    source.classList.add("selected");
    $("#source-title").textContent = source.dataset.title;
    $("#source-section").textContent = source.dataset.section;
    $("#pdf-frame").src = source.dataset.url;
    $("#open-pdf").href = source.dataset.url;
    $("#evidence-empty").classList.add("hidden");
    $("#evidence-content").classList.remove("hidden");
    $("#evidence").classList.add("open");
  }
  const image = event.target.closest("[data-lightbox]");
  if (image) {
    event.preventDefault();
    $("#lightbox img").src = image.src;
    $("#lightbox").classList.add("open");
  }
});

$("#close-evidence").addEventListener("click", () => $("#evidence").classList.remove("open"));
$("#lightbox").addEventListener("click", () => $("#lightbox").classList.remove("open"));

async function loadLibrary() {
  const list = $("#library-list");
  list.innerHTML = `<div class="empty-library">Loading library…</div>`;
  try {
    const response = await fetch("/library");
    const data = await response.json();
    if (!data.manuals.length) {
      list.innerHTML = `<div class="empty-library">${escapeHtml(data.error || "No manuals indexed.")}</div>`;
      return;
    }
    list.innerHTML = data.manuals.map(manual => `
      <div class="library-row">
        <strong>${escapeHtml(manual.title)}</strong>
        <span>${escapeHtml(manual.system || "General")}</span>
        <span>${escapeHtml(manual.vehicle || "2014 CC")}</span>
        <small>${manual.pages ? `${manual.pages} pages` : escapeHtml(manual.manual_id)}</small>
      </div>`).join("");
  } catch {
    list.innerHTML = `<div class="empty-library">Unable to load the library.</div>`;
  }
}

$$(".rail-button").forEach(button => button.addEventListener("click", () => {
  $$(".rail-button").forEach(item => item.classList.remove("active"));
  button.classList.add("active");
  $$(".view").forEach(view => view.classList.remove("active"));
  $(`#${button.dataset.view}-view`).classList.add("active");
  $(".rail").classList.remove("open");
  if (button.dataset.view === "library") loadLibrary();
}));

$(".mobile-menu").addEventListener("click", () => $(".rail").classList.toggle("open"));
$("#refresh-library").addEventListener("click", async () => {
  await loadStatus();
  await loadLibrary();
});
$("#open-data-folder").addEventListener("click", async () => {
  if (window.pywebview?.api) await window.pywebview.api.open_data_folder();
});

loadStatus();
