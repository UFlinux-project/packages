import init from "/assets/wasm/packages.js";

// Only the ABI bootstrap and recovery from a failed WASM download live in JS.
init().catch(error => {
  console.error(error);
  const status = document.querySelector("#status");
  status.textContent = status.dataset.loadError;
  document.querySelector("#retry").hidden = false;
});
