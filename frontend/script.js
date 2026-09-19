// ============================================================
// RISK ASSESSMENT DATA
// ============================================================

async function loadData() {

  try {

    const response = await fetch(
      `../backend/data/risk_assessment.json?t=${Date.now()}`
    );


    if (!response.ok) {

      throw new Error(
        `Could not load risk assessment: ${response.status}`
      );

    }


    const data = await response.json();


    console.log(
      "Loaded risk assessment:",
      data
    );


    updateDashboard(data);

  }

  catch (error) {

    console.error(
      "Error loading risk assessment:",
      error
    );


    document.getElementById(
      "gemini-assessment"
    ).textContent =
      "Unable to retrieve the latest risk assessment.";

  }

}



// ============================================================
// UPDATE DASHBOARD
// ============================================================

function updateDashboard(data) {

  const observations =
    data.observations || {};


  const weather =
    observations.weather || {};


  const seismic =
    observations.seismic || {};


  const gemini =
    data.gemini || {};



  // ----------------------------
  // WEATHER
  // ----------------------------

  document.getElementById(
    "temperature"
  ).textContent =

    weather.temperature_c != null
      ? `${weather.temperature_c} °C`
      : "Unavailable";



  document.getElementById(
    "precipitation"
  ).textContent =

    weather.precipitation_mm != null
      ? `${weather.precipitation_mm} mm`
      : "Unavailable";



  document.getElementById(
    "wind"
  ).textContent =

    weather.wind_speed_kmh != null
      ? `${weather.wind_speed_kmh} km/h`
      : "Unavailable";



  // ----------------------------
  // SEISMIC
  // ----------------------------

  document.getElementById(
    "earthquakes"
  ).textContent =

    seismic.event_count != null
      ? seismic.event_count
      : "Unavailable";



  // ----------------------------
  // RISK LEVEL
  // ----------------------------

  const riskElement =
    document.getElementById(
      "risk-level"
    );


  const riskLevel =
    gemini.risk_level || "UNKNOWN";


  riskElement.textContent =
    riskLevel;


  riskElement.className =
    `risk ${riskLevel.toLowerCase()}`;



  // ----------------------------
  // CONFIDENCE
  // ----------------------------

  document.getElementById(
    "confidence"
  ).textContent =

    gemini.confidence != null
      ? `${gemini.confidence}%`
      : "Unavailable";



  // ----------------------------
  // GEMINI REASONING
  // ----------------------------

  const reasoning =

    gemini.reasoning ||
    "No Gemini assessment available.";


  document.getElementById(
    "risk-reason"
  ).textContent =
    reasoning;


  document.getElementById(
    "gemini-assessment"
  ).textContent =
    reasoning;



  // ----------------------------
  // GEMINI SIGNALS
  // ----------------------------

  const signalsContainer =
    document.getElementById(
      "signals"
    );


  signalsContainer.innerHTML =
    "";


  const signals =
    gemini.signals || [];


  signals.forEach(
    signal => {

      const element =
        document.createElement(
          "div"
        );


      element.className =
        "signal";


      element.textContent =
        signal;


      signalsContainer.appendChild(
        element
      );

    }
  );

}



// ============================================================
// GLACIER IMAGE HISTORY
// ============================================================

// For now these images are listed manually.
// Later your backend can provide these automatically.

const glacierImages = [

  {
    src:
      "../backend/data_collector/images/hintereisferner1_20260919T155910Z.jpg",

    time:
      "19 Sep 2026 — 17:30:00 UTC"
  },


  {
    src:
      "../backend/data_collector/images/hintereisferner1_20260919T160023Z.jpg",

    time:
      "19 Sep 2026 — 18:00:00 UTC"
  },


  {
    src:
      "../backend/data_collector/images/hintereisferner1_latest.jpg",

    time:
      "Latest image | 19 Sep 2026 — 20:00:00 UTC"
  }

];



let currentImageIndex =
  glacierImages.length - 1;



function showGlacierImage() {

  const image =
    glacierImages[
      currentImageIndex
    ];


  document.getElementById(
    "glacier-image"
  ).src =
    `${image.src}?t=${Date.now()}`;


  document.getElementById(
    "image-time"
  ).textContent =
    image.time;

}



// ============================================================
// PREVIOUS IMAGE BUTTON
// ============================================================

document.getElementById(
  "prev-image"
).addEventListener(

  "click",

  () => {

    currentImageIndex--;


    if (
      currentImageIndex < 0
    ) {

      currentImageIndex =
        glacierImages.length - 1;

    }


    showGlacierImage();

  }

);



// ============================================================
// NEXT IMAGE BUTTON
// ============================================================

document.getElementById(
  "next-image"
).addEventListener(

  "click",

  () => {

    currentImageIndex++;


    if (
      currentImageIndex >=
      glacierImages.length
    ) {

      currentImageIndex = 0;

    }


    showGlacierImage();

  }

);



// ============================================================
// INITIAL LOAD
// ============================================================

showGlacierImage();

loadData();



// ============================================================
// REFRESH RISK JSON EVERY 30 SECONDS
// ============================================================

// Important:
// This does NOT call Gemini.
// It only reloads the latest risk_assessment.json.

setInterval(
  loadData,
  30000
);