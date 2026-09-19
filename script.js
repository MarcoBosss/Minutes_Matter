const mockData = {
  observations: {
    weather: {
      temperature_c: 3.8,
      precipitation_mm: 4.2,
      wind_speed_kmh: 22
    },

    seismic: {
      event_count: 2,
      max_magnitude: 2.4
    }
  },

  gemini: {
    risk_level: "WATCH",
    confidence: 78,

    reasoning:
      "Recent precipitation combined with seismic activity suggests conditions should be monitored closely.",

    signals: [
      "Moderate recent precipitation",
      "Two seismic events detected nearby",
      "No major visual glacier anomaly detected"
    ]
  }
};


function updateDashboard(data) {

  const weather = data.observations.weather;
  const seismic = data.observations.seismic;
  const gemini = data.gemini;

  document.getElementById("temperature").textContent =
    `${weather.temperature_c} °C`;

  document.getElementById("precipitation").textContent =
    `${weather.precipitation_mm} mm`;

  document.getElementById("wind").textContent =
    `${weather.wind_speed_kmh} km/h`;

  document.getElementById("earthquakes").textContent =
    seismic.event_count;


  const riskElement =
    document.getElementById("risk-level");

  riskElement.textContent = gemini.risk_level;

  riskElement.className =
    `risk ${gemini.risk_level.toLowerCase()}`;


  document.getElementById("confidence").textContent =
    `${gemini.confidence}%`;

  document.getElementById("risk-reason").textContent =
    gemini.reasoning;

  document.getElementById("gemini-assessment").textContent =
    gemini.reasoning;


  const signalsContainer =
    document.getElementById("signals");

  signalsContainer.innerHTML = "";

  gemini.signals.forEach(signal => {

    const element = document.createElement("div");

    element.className = "signal";
    element.textContent = "• " + signal;

    signalsContainer.appendChild(element);

  });

}


updateDashboard(mockData);
