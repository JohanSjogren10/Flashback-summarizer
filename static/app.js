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

  submitBtn.disabled = true;
  showStatus("Hämtar och sammanfattar tråden … detta kan ta en stund.", false, true);

  try {
    const response = await fetch("/api/summarize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, length, max_pages: maxPages }),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Något gick fel.");
    }

    renderResult(data);
    hideStatus();
  } catch (err) {
    showStatus(err.message, true);
  } finally {
    submitBtn.disabled = false;
  }
});

function renderResult(data) {
  document.getElementById("result-title").textContent =
    data.title || "Sammanfattning";
  document.getElementById("meta").textContent =
    `${data.num_posts} inlägg · ~${data.pages_fetched} sidor · motor: ${data.backend}`;
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
