const modeUrlButton = document.getElementById("mode-url");
const modeUploadButton = document.getElementById("mode-upload");
const panelUrl = document.getElementById("panel-url");
const panelUpload = document.getElementById("panel-upload");
const imageUrlInput = document.getElementById("image-url");
const imageFileInput = document.getElementById("image-file");
const fitModeSelect = document.getElementById("fit-mode");
const addressInput = document.getElementById("address");
const discoverButton = document.getElementById("discover-btn");
const sendButton = document.getElementById("send-btn");
const previewImage = document.getElementById("preview");
const previewEmpty = document.getElementById("preview-empty");
const statusText = document.getElementById("status-text");
const progressBar = document.getElementById("progress-bar");
const lineCount = document.getElementById("line-count");
const deviceHint = document.getElementById("device-hint");

let mode = "url";
let pollingId = null;
let objectUrl = null;

function setMode(nextMode) {
  mode = nextMode;
  modeUrlButton.classList.toggle("active", mode === "url");
  modeUploadButton.classList.toggle("active", mode === "upload");
  panelUrl.classList.toggle("active", mode === "url");
  panelUpload.classList.toggle("active", mode === "upload");
}

function setBusy(isBusy) {
  sendButton.disabled = isBusy;
  discoverButton.disabled = isBusy;
}

function setStatus(state, message, sent, total) {
  statusText.textContent = `${state.toUpperCase()}: ${message}`;
  const safeTotal = total || 128;
  const safeSent = sent || 0;
  const pct = Math.max(0, Math.min(100, (safeSent / safeTotal) * 100));
  progressBar.style.width = `${pct}%`;
  lineCount.textContent = `${safeSent} / ${safeTotal} lines`;
}

async function refreshStatus() {
  try {
    const response = await fetch("/api/status");
    const data = await response.json();
    setStatus(data.state, data.message, data.sent_lines, data.total_lines);
  } catch {
    setStatus("error", "Could not fetch status", 0, 128);
  }
}

function startPolling() {
  if (pollingId) {
    return;
  }
  pollingId = setInterval(refreshStatus, 1000);
}

function updatePreviewFromUrl() {
  const url = imageUrlInput.value.trim();
  if (!url) {
    previewImage.style.display = "none";
    previewEmpty.style.display = "block";
    return;
  }
  previewImage.src = url;
  previewImage.style.display = "block";
  previewEmpty.style.display = "none";
}

function updatePreviewFromFile() {
  const file = imageFileInput.files && imageFileInput.files[0];
  if (!file) {
    previewImage.style.display = "none";
    previewEmpty.style.display = "block";
    return;
  }

  if (objectUrl) {
    URL.revokeObjectURL(objectUrl);
  }
  objectUrl = URL.createObjectURL(file);
  previewImage.src = objectUrl;
  previewImage.style.display = "block";
  previewEmpty.style.display = "none";
}

modeUrlButton.addEventListener("click", () => setMode("url"));
modeUploadButton.addEventListener("click", () => setMode("upload"));
imageUrlInput.addEventListener("input", updatePreviewFromUrl);
imageFileInput.addEventListener("change", updatePreviewFromFile);
addressInput.addEventListener("input", () => { deviceHint.textContent = ""; });

// Handle clipboard paste for images
document.addEventListener("paste", async (event) => {
  const items = event.clipboardData?.items;
  if (!items) return;

  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    if (item.kind === "file" && item.type.startsWith("image/")) {
      event.preventDefault();
      const file = item.getAsFile();
      if (file) {
        // Switch to upload mode
        setMode("upload");
        
        // Create a DataTransfer object and set the file
        const dataTransfer = new DataTransfer();
        dataTransfer.items.add(file);
        imageFileInput.files = dataTransfer.files;
        
        // Trigger change event to update preview
        imageFileInput.dispatchEvent(new Event("change", { bubbles: true }));
      }
      break;
    }
  }
});

discoverButton.addEventListener("click", async () => {
  setBusy(true);
  setStatus("connecting", "Scanning for projector", 0, 128);

  try {
    const response = await fetch("/api/discover");
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Could not discover device");
    }
    addressInput.value = payload.address;
    setStatus("ready", `Discovered ${payload.address}`, 0, 128);
  } catch (error) {
    setStatus("error", error.message || "Discovery failed", 0, 128);
  } finally {
    setBusy(false);
  }
});

sendButton.addEventListener("click", async () => {
  const address = addressInput.value.trim() || null;
  const fitMode = fitModeSelect.value;

  setBusy(true);
  setStatus("connecting", "Preparing transfer", 0, 128);

  try {
    let response;

    if (mode === "url") {
      const url = imageUrlInput.value.trim();
      if (!url) {
        throw new Error("Paste an image URL first");
      }

      response = await fetch("/api/send-url", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, address, fit_mode: fitMode })
      });
    } else {
      const file = imageFileInput.files && imageFileInput.files[0];
      if (!file) {
        throw new Error("Choose an image file first");
      }

      const formData = new FormData();
      formData.append("file", file);
      formData.append("fit_mode", fitMode);
      if (address) {
        formData.append("address", address);
      }

      response = await fetch("/api/send-upload", {
        method: "POST",
        body: formData
      });
    }

    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Transfer failed");
    }

    await refreshStatus();
    setStatus("done", `Sent to ${payload.address}`, 128, 128);
  } catch (error) {
    setStatus("error", error.message || "Transfer failed", 0, 128);
  } finally {
    setBusy(false);
  }
});

startPolling();
refreshStatus();

async function loadCachedDevice() {
  try {
    const res = await fetch("/api/cached-device");
    const data = await res.json();
    if (data.address && !addressInput.value) {
      addressInput.value = data.address;
      deviceHint.textContent = "Last used device (within 24 h)";
    }
  } catch {}
}
loadCachedDevice();
