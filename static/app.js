const form = document.getElementById("summarize-form");
const statusEl = document.getElementById("status");
const resultEl = document.getElementById("result");
const submitBtn = document.getElementById("submit-btn");

let statusTimer = null;

function showStatus(message, isError = false, loading = false) {
  statusEl.hidden = false;
  statusEl.classList.toggle("error", isError);
  statusEl.innerHTML = loading
    ? `<span class="spinner"></span>${message}`
    : message;
}

function hideStatus() {
  statusEl.hidden = true;
}

function startProgress() {
  showStatus("Hämtar sidor \u2026", false, true);
  stopProgress();
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
  startProgress();

  try {
    const response = await fetch("/api/summarize", {
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
    showStatus(err.message, true);
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
