async function loadData() {
  try {
    // ../ means "go out of frontend/ and look in the project root"
    // Date.now() prevents the browser from showing an old cached JSON file
    
    const response = await fetch(
  `../backend/data/risk_assessment.json?t=${Date.now()}`
);

    if (!response.ok) {
      throw new Error(`Could not load risk assessment: ${response.status}`);
    }

    const data = await response.json();

    updateDashboard(data);

  } catch (error) {
    console.error("Error loading risk assessment:", error);

    document.getElementById("gemini-assessment").textContent =
      "Unable to retrieve the latest risk assessment.";
  }
}


function updateDashboard(data) {
  const weather = data.observations.weather || {};
  const seismic = data.observations.seismic || {};
  const gemini = data.gemini || {};

  // WEATHER
  document.getElementById("temperature").textContent =
    weather.temperature_c != null
      ? `${weather.temperature_c} °C`
      : "Unavailable";

  document.getElementById("precipitation").textContent =
    weather.precipitation_mm != null
      ? `${weather.precipitation_mm} mm`
      : "Unavailable";

  document.getElementById("wind").textContent =
    weather.wind_speed_kmh != null
      ? `${weather.wind_speed_kmh} km/h`
      : "Unavailable";


  // SEISMIC
  document.getElementById("earthquakes").textContent =
    seismic.event_count != null
      ? seismic.event_count
      : "Unavailable";


  // GEMINI RISK LEVEL
  const riskElement = document.getElementById("risk-level");

  const riskLevel = gemini.risk_level || "UNKNOWN";

  riskElement.textContent = riskLevel;

  riskElement.className =
    `risk ${riskLevel.toLowerCase()}`;


  // CONFIDENCE
  document.getElementById("confidence").textContent =
    gemini.confidence != null
      ? `${gemini.confidence}%`
      : "Unavailable";


  // REASONING
  document.getElementById("risk-reason").textContent =
    gemini.reasoning || "No assessment available.";

  document.getElementById("gemini-assessment").textContent =
    gemini.reasoning || "No assessment available.";


  // SIGNALS
  const signalsContainer = document.getElementById("signals");

  signalsContainer.innerHTML = "";

  const signals = gemini.signals || [];

  signals.forEach(signal => {
    const element = document.createElement("div");

    element.className = "signal";

    element.textContent = "• " + signal;

    signalsContainer.appendChild(element);
  });
}


// Load immediately when page opens
loadData();


// Refresh every 30 seconds
setInterval(loadData, 30000);