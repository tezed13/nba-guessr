// ---------------------------
// NBA Guessr Game Logic
// ---------------------------

let playerNames = [];
let streak = 0;
let currentPlayerName = "";

// --- Element references ---
const guessInput = document.getElementById("guessInput");
const suggestionsDiv = document.getElementById("suggestions");
const playerNameEl = document.getElementById("playerName");
const seasonsBody = document.getElementById("seasonsBody");
const resultText = document.getElementById("resultText");
const streakEl = document.getElementById("streak");
const submitBtn = document.getElementById("submitGuess");
const giveUpBtn = document.getElementById("giveUp");
const nextRoundBtn = document.getElementById("nextRound");




// Hide next round button initially
nextRoundBtn.style.display = "none";

// --- Load all players for autocomplete ---
fetch("/all_players")
  .then(res => res.json())
  .then(data => playerNames = data)
  .catch(err => console.error("Error loading player list:", err));

// ---------------------------
// Load Random Player
// ---------------------------
async function loadRandomPlayer() {
  const start = document.getElementById("startSeason").value;
  const end = document.getElementById("endSeason").value;
  const types = document.getElementById("types").value.split(",");

  const params = new URLSearchParams({ start_season: start, end_season: end });
  types.forEach(t => params.append("types", t));

  const res = await fetch(`/random_player?${params}`);
  const data = await res.json();

  resultText.textContent = "";
  guessInput.value = "";
  suggestionsDiv.classList.add("hidden");
  nextRoundBtn.style.display = "none";

  if (data.error) {
    playerNameEl.textContent = "Error";
    seasonsBody.innerHTML = `<tr><td colspan="8" class="text-center text-red-600 p-2">${data.error}</td></tr>`;
    return;
  }

  playerNameEl.textContent = "???";
  currentPlayerName = data.player_name;
  seasonsBody.innerHTML = "";

  data.seasons.forEach(season => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td class="border p-2">${season.season}</td>
      <td class="border p-2">${season.tm}</td>
      <td class="border p-2">${season.g}</td>
      <td class="border p-2">${season.gs}</td>
      <td class="border p-2">${season.mp_per_game}</td>
      <td class="border p-2">${season.pts_per_game}</td>
      <td class="border p-2">${season.ast_per_game}</td>
      <td class="border p-2">${season.trb_per_game}</td>
    `;
    seasonsBody.appendChild(row);
  });
}

// ---------------------------
// Autocomplete
// ---------------------------
guessInput.addEventListener("input", () => {
  const query = guessInput.value.toLowerCase().trim();
  if (query.length < 3) {
    suggestionsDiv.classList.add("hidden");
    return;
  }

  const startsWithMatches = playerNames.filter(name =>
    name.toLowerCase().split(" ").some(part => part.startsWith(query))
  );

  const containsMatches = playerNames.filter(name => {
    const lower = name.toLowerCase();
    return !lower.split(" ").some(part => part.startsWith(query)) && lower.includes(query);
  });

  const matches = [...startsWithMatches, ...containsMatches].slice(0, 10);

  if (matches.length === 0) {
    suggestionsDiv.classList.add("hidden");
    return;
  }

  suggestionsDiv.innerHTML = matches
    .map(name => {
      const regex = new RegExp(`(${escapeRegExp(query)})`, "ig");
      const highlighted = name.replace(regex, "<strong>$1</strong>");
      return `<div data-name="${escapeHtmlAttr(name)}" class="p-1 hover:bg-gray-700 cursor-pointer text-white">${highlighted}</div>`;
    })
    .join("");

  suggestionsDiv.classList.remove("hidden");
});

// Click on suggestion
suggestionsDiv.addEventListener("click", e => {
  const item = e.target.closest("div[data-name]");
  if (!item) return;
  guessInput.value = item.dataset.name;
  suggestionsDiv.classList.add("hidden");
});

// Enter key selects first suggestion
guessInput.addEventListener("keydown", e => {
  if (e.key === "Enter") {
    e.preventDefault();
    const firstSuggestion = suggestionsDiv.querySelector("div[data-name]");
    if (firstSuggestion) {
      guessInput.value = firstSuggestion.dataset.name;
      suggestionsDiv.classList.add("hidden");
    }
  }
});

// ---------------------------
// Guess Submission
// ---------------------------
submitBtn.addEventListener("click", () => {
  const guess = guessInput.value.trim().toLowerCase();
  if (!currentPlayerName) return;

  if (guess && currentPlayerName.toLowerCase() === guess) {
    streak++;
    resultText.textContent = `✅ Correct! Streak: ${streak}`;
    playerNameEl.textContent = currentPlayerName;
    nextRoundBtn.style.display = "inline-block"; // Correct: hide next round
  } else {
    streak = 0;
    resultText.textContent = `❌ Incorrect! The player was ${currentPlayerName}. Streak reset.`;
    playerNameEl.textContent = currentPlayerName;
    nextRoundBtn.style.display = "inline-block"; // Show next round
  }

  streakEl.textContent = streak;
});

// ---------------------------
// Give Up
// ---------------------------
giveUpBtn.addEventListener("click", () => {
  if (currentPlayerName) {
    playerNameEl.textContent = currentPlayerName;
    resultText.textContent = `😞 You gave up! The player was ${currentPlayerName}. Streak reset.`;
    streak = 0;
    streakEl.textContent = streak;
    nextRoundBtn.style.display = "inline-block"; // Show next round
  }
});

// ---------------------------
// Next Round
// ---------------------------
nextRoundBtn.addEventListener("click", () => {
  loadRandomPlayer();
  nextRoundBtn.style.display = "none"; // Hide again
});

// ---------------------------
// Helpers
// ---------------------------
function escapeHtmlAttr(s) {
  return s.replace(/&/g, "&amp;").replace(/"/g, "&quot;")
          .replace(/'/g,"&#39;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

function escapeRegExp(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// ---------------------------
// Initial Load
// ---------------------------
loadRandomPlayer();
