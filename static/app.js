const form = document.getElementById("summarize-form");
const statusEl = document.getElementById("status");
const resultEl = document.getElementById("result");
const submitBtn = document.getElementById("submit-btn");
const apiBaseInput = document.getElementById("api_base");

const API_BASE_STORAGE_KEY = "flashback-summarizer:api-base";

let statusTimer = null;

function storedApiBase() {
  try {
    return window.localStorage.getItem(API_BASE_STORAGE_KEY) || "";
  } catch (err) {
    return "";
  }
}

function saveApiBase(value) {
  try {
    if (value) {
      window.localStorage.setItem(API_BASE_STORAGE_KEY, value);
    } else {
      window.localStorage.removeItem(API_BASE_STORAGE_KEY);
    }
  } catch (err) {
    /* localStorage kan vara blockerad – strunta i det. */
  }
}

function apiBase() {
  const value = (apiBaseInput.value || "").trim();
  return value.replace(/\/+$/, "");
}

function apiUrl(path) {
  return `${apiBase()}${path}`;
}

apiBaseInput.value = storedApiBase() || window.FLASHBACK_API_BASE || "";
apiBaseInput.addEventListener("change", () => {
  apiBaseInput.value = apiBase();
  saveApiBase(apiBaseInput.value);
});

function showStatus(message, isError = false, loading = false) {
  statusEl.hidden = false;
  statusEl.classList.toggle("error", isError);
  statusEl.textContent = "";
  if (loading) {
    const spinner = document.createElement("span");
    spinner.className = "spinner";
    statusEl.appendChild(spinner);
  }
  statusEl.appendChild(document.createTextNode(message));
}

function hideStatus() {
  statusEl.hidden = true;
}

function startProgress() {
  stopProgress();
  showStatus("Hämtar sidor \u2026", false, true);
  statusTimer = window.setTimeout(() => {
    showStatus("Sammanfattar \u2026", false, true);
  }, 4000);
}

function stopProgress() {
  if (statusTimer !== null) {
    window.clearTimeout(statusTimer);
    statusTimer = null;
  }
}

function describeError(err) {
  if (err instanceof TypeError) {
    return apiBase()
      ? `Kunde inte nå backend på ${apiBase()}. Kontrollera att tjänsten är igång.`
      : "Kunde inte nå backend. Ange Backend-URL under \u201cAvancerat\u201d om sidan körs på GitHub Pages.";
  }
  return err.message;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  resultEl.hidden = true;

  const url = document.getElementById("url").value.trim();
  const length = document.getElementById("length").value;
  const maxPages = parseInt(document.getElementById("max_pages").value, 10);
  const strategy = document.getElementById("strategy").value;
  const delay = parseFloat(document.getElementById("delay").value);

  const payload = { url, length, strategy };
  if (Number.isFinite(maxPages)) {
    payload.max_pages = maxPages;
  }
  if (Number.isFinite(delay)) {
    payload.delay = delay;
  }

  submitBtn.disabled = true;
  saveApiBase(apiBase());
  startProgress();

  try {
    const response = await fetch(apiUrl("/api/summarize"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Något gick fel.");
    }

    renderResult(data);
    if (data.truncated && data.notice) {
      showStatus(data.notice, true);
    } else {
      hideStatus();
    }
  } catch (err) {
    showStatus(describeError(err), true);
  } finally {
    stopProgress();
    submitBtn.disabled = false;
  }
});

function renderResult(data) {
  document.getElementById("result-title").textContent =
    data.title || "Sammanfattning";
  document.getElementById("meta").textContent =
    `${data.num_posts} inlägg · ${data.pages_fetched} av ${data.total_pages} sidor · motor: ${data.backend}`;
  document.getElementById("tldr").textContent = data.tldr;

  const bullets = document.getElementById("bullets");
  bullets.innerHTML = "";
  (data.bullets || []).forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    bullets.appendChild(li);
  });

  resultEl.hidden = false;
}
