/* Static RiskResponse consumer. Provider text is always inserted as text nodes. */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const form = $("timing-form");
  let snapshot = null;
  let selected = null;
  let snapshotVersion = 0;
  let scenarioVersion = 0;
  let scenarioController = null;
  let ready = false;
  let apiBase;
  let map;
  let layers;
  let refreshTimer;
  let persistenceCells = [];

  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  }
  const minutes = value => value === null || value === undefined ? "Not provided" : `${value} minutes`;
  const date = value => value === null || value === undefined || value === "" ? "Not provided" : String(value);
  const number = value => Number.isFinite(value) ? value.toFixed(2) : "Not provided";
  function line(parent, label, value) { parent.append(node("p", `${label}: ${value}`)); }
  function clearScenario() {
    scenarioVersion++;
    scenarioController?.abort();
    scenarioController = null;
    $("scenario-result").replaceChildren();
    $("scenario-message").textContent = "";
    $("evaluate").disabled = false;
  }
  function selectZone(zone) {
    if (!ready) return;
    clearScenario();
    selected = zone;
    scheduleRefresh();
    form.reset();
    $("scenario-content").hidden = false;
    $("selection-message").textContent = `${zone.name} · ${zone.species}`;
    const timing = $("baseline-timing");
    timing.replaceChildren();
    line(timing, "Snapshot priority", zone.priority);
    line(timing, "Fire ETA", minutes(zone.fire_eta_minutes));
    line(timing, "Response time", minutes(zone.response_time_minutes));
    line(timing, "Safety buffer", minutes(zone.safety_buffer_minutes));
    line(timing, "Response window", minutes(zone.response_window_minutes));
    document.querySelectorAll(".candidate").forEach(card => card.classList.toggle("selected", card.dataset.zoneId === zone.id));
    if (map) map.panTo([zone.latitude, zone.longitude]);
  }
  function validPersistence(report) {
    if (!report || !["ready", "empty", "unavailable"].includes(report.status) ||
        report.method !== "random_forest" || report.mode !== snapshot?.mode ||
        !Array.isArray(report.cells) || !Array.isArray(report.quality_flags) ||
        !["window_start", "window_end", "horizon_end"].every(key => typeof report[key] === "string" && Number.isFinite(Date.parse(report[key])))) return false;
    if (!(Date.parse(report.window_start) < Date.parse(report.window_end) &&
          Date.parse(report.window_end) < Date.parse(report.horizon_end))) return false;
    if (!report.cells.every(cell => typeof cell.id === "string" && Array.isArray(cell.fire_ids) &&
        Number.isFinite(cell.latitude) && Math.abs(cell.latitude) <= 90 &&
        Number.isFinite(cell.longitude) && Math.abs(cell.longitude) <= 180 &&
        ((cell.score === null && typeof cell.reason === "string") ||
         (Number.isFinite(cell.score) && cell.score >= 0 && cell.score <= 1 && cell.reason === null)))) return false;
    return report.status !== "ready" || report.cells.some(cell => cell.score !== null);
  }
  function renderPersistence(report) {
    persistenceCells = [];
    $("persistence-cells").replaceChildren();
    $("persistence-meta").textContent = "";
    $("persistence-window").textContent = "";
    $("persistence-note").textContent = "Next 24 hours in the same approximate 5 km cell. Separate from wildlife proximity and operator timing.";
    if (!validPersistence(report)) {
      $("persistence-status").textContent = "Model results unavailable · missing or invalid report.";
      return;
    }
    $("persistence-meta").textContent = (report.model_version ?? "Model unavailable") + " · " + report.source_product + " · " + report.mode;
    const ageHours = Math.max(0, (Date.now() - Date.parse(report.window_end)) / 3600000);
    $("persistence-window").textContent = "Input (UTC): " + report.window_start + " – " + report.window_end + ". Horizon ends: " + report.horizon_end + ". " + (report.mode === "sample" ? "Fixed sample clock." : "Window closed " + ageHours.toFixed(1) + " hours ago.");
    if (report.experimental) $("persistence-note").textContent += " Experimental NRT transfer is unvalidated; vegetation type may be unavailable. Satellite delivery can lag.";
    $("persistence-status").textContent = report.status === "ready"
      ? (report.mode === "sample" ? "Sample model scores · synthetic inputs" : "Experimental live model · random forest")
      : report.status === "empty" ? "No eligible detections in the latest closed window."
      : "Model results unavailable · " + (report.reason ?? "inputs or model unavailable");
    if (report.status !== "ready" && report.status !== "unavailable") return;
    persistenceCells = report.status === "ready" ? report.cells : [];
    for (const cell of [...report.cells].sort((a,b) => (b.score ?? -1) - (a.score ?? -1)).slice(0,5)) {
      const row = node("div", undefined, "persistence-cell");
      const button = node("button", "Cell " + cell.id + " · " + cell.fire_count + " detections");
      button.type = "button";
      button.disabled = !map || cell.score === null;
      button.addEventListener("click", () => map?.panTo([cell.latitude, cell.longitude]));
      row.append(button, node("span", cell.score === null ? "Unavailable" : (cell.score*100).toFixed(0) + "% score"));
      $("persistence-cells").append(row);
    }
  }
  function scheduleRefresh() {
    clearTimeout(refreshTimer);
    const paused = selected ? "timing scenario selected" : document.visibilityState === "hidden" ? "page hidden" : null;
    $("refresh-status").textContent = paused ? "Automatic refresh paused · " + paused + ". Refresh data clears the selection." : "Automatic refresh every five minutes while visible and idle.";
    refreshTimer = setTimeout(() => {
      if (!selected && document.visibilityState !== "hidden" && !$("refresh").disabled) refresh();
      else scheduleRefresh();
    }, 5*60*1000);
  }
  function occurrenceDetails(parent, record) {
    line(parent, "Species", record.species);
    line(parent, "Observation date", date(record.observed_at));
    line(parent, "Source", record.source);
    line(parent, "Dataset", record.dataset_key ?? "Not provided");
    line(parent, "License", record.license ?? "Not provided");
  }
  function initMap() {
    if (!window.L) {
      $("map-message").textContent = "Map library unavailable. Candidate cards and source records remain available below.";
      return;
    }
    map = L.map("map").setView([37, -119], 6);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>',
      maxZoom: 19
    }).on("tileerror", () => { $("map-message").textContent = "Some map tiles are unavailable. Markers and records still show the retrieved observations."; }).addTo(map);
    layers = L.featureGroup().addTo(map);
  }
  function renderMap(data) {
    if (!map) return;
    layers.clearLayers();
    for (const fire of data.fires) {
      const popup = node("div");
      popup.append(node("strong", "Fire detection"));
      line(popup, "Source", fire.source);
      line(popup, "Observed (UTC)", date(fire.observed_at));
      line(popup, "Fire radiative power", fire.frp_mw == null ? "Not provided" : `${fire.frp_mw} MW`);
      const cell = persistenceCells.find(item => item.fire_ids.includes(fire.id));
      if (cell && cell.score !== null) line(popup, "Persistence model", (cell.score*100).toFixed(0) + "% score · cell " + cell.id + " · " + data.mode);
      L.circleMarker([fire.latitude, fire.longitude], {radius: 8, color: "#913317", fillColor: "#df632d", fillOpacity: .9, weight: 2}).addTo(layers).bindPopup(popup);
    }
    for (const record of data.occurrences) {
      const popup = node("div");
      popup.append(node("strong", `Wildlife observation ${record.id}`));
      occurrenceDetails(popup, record);
      popup.append(node("p", "Observation only; current presence is not established."));
      const zone = data.wildlife_zones.find(candidate => candidate.id === `gbif:${record.id}`);
      if (zone) {
        const button = node("button", "Select for timing scenario");
        button.type = "button";
        button.addEventListener("click", () => selectZone(zone));
        popup.append(button);
      }
      L.circleMarker([record.latitude, record.longitude], {radius: 6, color: "#176d87", fillColor: "#fff", fillOpacity: .85, weight: 3}).addTo(layers).bindPopup(popup);
    }
    if (layers.getLayers().length) map.fitBounds(layers.getBounds(), {padding: [30, 30], maxZoom: 12});
  }
  function renderRecords(data) {
    const records = $("records");
    records.replaceChildren();
    data.fires.forEach(fire => {
      const record = node("div", undefined, "record");
      record.append(node("strong", `Fire detection ${fire.id} · ${fire.source}`));
      line(record, "Observed (UTC)", date(fire.observed_at));
      line(record, "Fire radiative power", fire.frp_mw == null ? "Not provided" : `${fire.frp_mw} MW`);
      records.append(record);
    });
    data.occurrences.forEach(occurrence => {
      const record = node("div", undefined, "record");
      record.append(node("strong", `Wildlife observation ${occurrence.id}`));
      occurrenceDetails(record, occurrence);
      records.append(record);
    });
  }
  function renderCandidates(data) {
    $("candidate-count").textContent = `(${data.wildlife_zones.length})`;
    $("candidates").replaceChildren();
    for (const zone of data.wildlife_zones) {
      const card = node("article", undefined, "candidate");
      card.dataset.zoneId = zone.id;
      const button = node("button", zone.name);
      button.type = "button";
      button.addEventListener("click", () => selectZone(zone));
      card.append(button, node("p", zone.species));
      card.append(node("p", `Proximity score: ${number(zone.risk)} / 1`, "score"));
      line(card, "Nearest fire", `${zone.nearest_fire_id} · ${number(zone.distance_to_fire_km)} km`);
      const occurrence = data.occurrences.find(record => `gbif:${record.id}` === zone.id);
      line(card, "Observation date", date(occurrence?.observed_at));
      line(card, "Snapshot priority", zone.priority);
      $("candidates").append(card);
    }
    const empty = [];
    if (!data.fires.length) empty.push("No fire detections in this snapshot.");
    if (!data.occurrences.length) empty.push("No wildlife observations in this snapshot.");
    if (!data.wildlife_zones.length) empty.push("No proximity candidates within 25 km. This does not establish the absence of wildlife or fire risk.");
    $("empty-state").textContent = empty.join(" ");
  }
  async function request(route, options = {}) {
    const {controller = new AbortController(), ...fetchOptions} = options;
    // /risk can fetch FIRMS plus three sequential GBIF pages: allow the
    // four (3.05s connect + 10s read) budgets plus processing/network margin.
    const timeoutMs = route === "/risk" ? 75000 : 25000;
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(`${apiBase}${route}`, {...fetchOptions, signal: controller.signal});
      if (!response.ok) {
        const error = new Error(`HTTP ${response.status}`);
        error.status = response.status;
        throw error;
      }
      return await response.json();
    } finally { clearTimeout(timeout); }
  }
  async function refresh() {
    if ($("refresh").disabled || !apiBase) return;
    const version = ++snapshotVersion;
    ready = false;
    clearTimeout(refreshTimer);
    $("persistence-status").textContent = "Refreshing model results…";
    document.querySelectorAll("#persistence-cells button").forEach(button => { button.disabled = true; });
    clearScenario();
    selected = null;
    $("scenario-content").hidden = true;
    $("selection-message").textContent = "Select a candidate to enter timing assumptions.";
    $("refresh").disabled = true;
    document.querySelectorAll(".candidate button").forEach(button => { button.disabled = true; });
    $("data-status").textContent = "Loading observations…";
    $("data-status").parentElement.dataset.state = "loading";
    if (snapshot) $("coverage").textContent = "Refreshing. The previous snapshot remains visible until new data arrives.";
    try {
      const data = await request("/risk");
      if (version !== snapshotVersion) return;
      if (!Array.isArray(data.fires) || !Array.isArray(data.occurrences) || !Array.isArray(data.wildlife_zones) || !["live", "sample"].includes(data.mode)) throw new Error("Unexpected response");
      snapshot = data;
      ready = true;
      $("data-status").textContent = data.mode === "sample" ? "Sample data · deterministic demonstration fixtures" : "Live data · provider observations";
      $("data-status").parentElement.dataset.state = data.mode;
      $("provenance").textContent = `Sources: NASA FIRMS fire detections · GBIF wildlife observations. Retrieved (UTC): ${date(data.fetched_at)}. ${data.fires.length} fire detections · ${data.occurrences.length} wildlife observations.`;
      $("coverage").textContent = data.truncated ? "GBIF results are capped / truncated; additional observations may exist. Historical and partial observation dates are preserved." : "GBIF results were not truncated by the configured query limit. This query is not a wildlife census; observations may be historical.";
      renderPersistence(data.fire_persistence);
      renderMap(data);
      renderRecords(data);
      renderCandidates(data);
    } catch (error) {
      $("data-status").parentElement.dataset.state = "error";
      $("data-status").textContent = error.status === 503 ? "Data unavailable · an upstream provider could not be reached. Retry with Refresh data." : "Unable to load observations. Check the configured API URL, connection, and backend, then retry.";
      $("persistence-status").textContent = snapshot ? "Previous model results may be stale · refresh failed." : "Model results unavailable · no snapshot.";
      $("coverage").textContent = snapshot ? "The previous snapshot remains visible and may be stale. Timing evaluation is disabled until a successful refresh." : "No snapshot is available. Failed live data is never replaced automatically with samples.";
    } finally { $("refresh").disabled = false; scheduleRefresh(); }
  }
  form.addEventListener("input", clearScenario);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (!ready || !selected) return;
    const values = {};
    for (const input of form.querySelectorAll("input")) {
      const value = input.value.trim() === "" ? NaN : Number(input.value);
      if (!Number.isFinite(value) || value < 0) {
        $("scenario-message").textContent = "Enter a finite, nonnegative duration for each timing field.";
        return;
      }
      values[input.name] = value;
    }
    clearScenario();
    const version = scenarioVersion;
    const snapshotId = snapshotVersion;
    const zone = selected;
    scenarioController = new AbortController();
    $("evaluate").disabled = true;
    $("scenario-message").textContent = "Evaluating operator scenario…";
    try {
      const data = await request("/risk/evaluate", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({zone, ...values}), controller: scenarioController});
      if (version !== scenarioVersion || snapshotId !== snapshotVersion || selected?.id !== zone.id) return;
      if (data.timing_source !== "operator_scenario" || data.assessment?.id !== zone.id) throw new Error("Unexpected scenario response");
      const result = $("scenario-result");
      result.append(node("h3", "Hypothetical operator scenario"));
      line(result, "Timing source", data.timing_source);
      line(result, "Response window", minutes(data.assessment.response_window_minutes));
      line(result, "Priority", data.assessment.priority);
      line(result, "Fire ETA", minutes(data.assessment.fire_eta_minutes));
      line(result, "Response time", minutes(data.assessment.response_time_minutes));
      line(result, "Safety buffer", minutes(data.assessment.safety_buffer_minutes));
      $("scenario-message").textContent = "Evaluation complete. These are operator-entered assumptions, not a predicted fire arrival.";
    } catch (error) {
      if (version !== scenarioVersion) return;
      $("scenario-message").textContent = error.status === 422 ? "Invalid scenario (422). Check the timing values and selected candidate, then try again." : "Scenario evaluation unavailable. Your selection and timing inputs are preserved; try again.";
    } finally {
      if (version === scenarioVersion) { $("evaluate").disabled = false; scenarioController = null; }
    }
  });
  document.addEventListener("visibilitychange", scheduleRefresh);
  $("refresh").addEventListener("click", refresh);
  initMap();
  try {
    const configured = window.WILDFYRE_CONFIG?.apiBaseUrl;
    const url = new URL(configured);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error("Invalid API URL");
    apiBase = url.href.replace(/\/$/, "");
    $("api-address").textContent = apiBase;
    refresh();
  } catch {
    $("data-status").textContent = "API configuration unavailable. Set WILDFYRE_CONFIG.apiBaseUrl in config.js to a reachable HTTP(S) backend URL.";
    $("data-status").parentElement.dataset.state = "error";
    $("refresh").disabled = true;
  }
})();
