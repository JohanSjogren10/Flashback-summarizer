const form = document.getElementById("summarize-form");
const statusEl = document.getElementById("status");
const resultEl = document.getElementById("result");
const submitBtn = document.getElementById("submit-btn");

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

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  resultEl.hidden = true;

  const url = document.getElementById("url").value.trim();
  const length = document.getElementById("length").value;
  const maxPages = parseInt(document.getElementById("max_pages").value, 10);
  const strategy = document.getElementById("strategy").value;
  const delay = parseFloat(document.getElementById("delay").value);

  if (estimateSeconds() > 120 &&
      !window.confirm(
        `Det här kan ta ungefär ${estimateText()}. Vill du fortsätta?`
      )) {
    return;
  }

  submitBtn.disabled = true;
  showStatus("Hämtar och sammanfattar tråden … detta kan ta en stund.", false, true);

  try {
    const response = await fetch("/api/summarize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        length,
        max_pages: maxPages,
        strategy,
        delay,
      }),
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
    submitBtn.disabled = false;
  }
});

function estimateSeconds() {
  const maxPages = parseInt(document.getElementById("max_pages").value, 10) || 1;
  const delay = parseFloat(document.getElementById("delay").value) || 0;
  return maxPages * (delay + 1);
}

function estimateText() {
  const seconds = estimateSeconds();
  if (seconds < 90) {
    return `${Math.round(seconds)} sekunder`;
  }
  return `${Math.round(seconds / 60)} minuter`;
}

function updateEstimate() {
  const maxPages = parseInt(document.getElementById("max_pages").value, 10) || 1;
  document.getElementById("estimate").textContent =
    `Uppskattad tid: ${maxPages} sidor \u00d7 ~${
      parseFloat(document.getElementById("delay").value) || 0
    } s \u2248 ${estimateText()}.`;
}

["max_pages", "delay"].forEach((id) => {
  document.getElementById(id).addEventListener("input", updateEstimate);
});
updateEstimate();

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
