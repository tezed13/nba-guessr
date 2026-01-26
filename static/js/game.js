let playerNames = [];
let currentPlayerName = "";
let streak = 0;

// Fetch all players for autocomplete
fetch("/all_players")
  .then(res => res.json())
  .then(data => playerNames = data)
  .catch(err => console.error("Error loading player list:", err));

async function loadRandomPlayer() {
  // 1. Reset UI for the new round
  seasonsBody.innerHTML = "";       
  resultText.textContent = "";      
  guessInput.value = "";            
  playerNameEl.textContent = "??????"; 
  playerNameEl.className = "text-2xl font-black text-center mb-4 text-gray-300 tracking-widest uppercase";
  nextRoundBtn.style.display = "none";
  submitBtn.disabled = false;

  // 2. Get parameters from hidden inputs
  const start = document.getElementById("startSeason").value;
  const end = document.getElementById("endSeason").value;
  const types = document.getElementById("types").value; // DO NOT .split(",") here

  // 3. Fetch data from the backend
  try {
    const res = await fetch(`/random_player?start_season=${start}&end_season=${end}&types=${types}`);
    const data = await res.json();

    if (data.error) {
      resultText.textContent = "Error: " + data.error;
      resultText.className = "mt-4 font-bold text-center text-xl text-red-600";
      return;
    }

    currentPlayerName = data.player_name;
    
    // 4. Populate the stats table
    data.seasons.forEach(s => {
      const row = document.createElement("tr");
      row.className = "hover:bg-gray-800 transition-colors border-b border-gray-800";
      row.innerHTML = `
        <td class="p-2">${s.season}</td>
        <td class="p-2">${s.tm}</td>
        <td class="p-2">${s.g}</td>
        <td class="p-2">${s.gs}</td>
        <td class="p-2">${s.mp_per_game}</td>
        <td class="p-2">${s.pts_per_game}</td>
        <td class="p-2">${s.ast_per_game}</td>
        <td class="p-2">${s.trb_per_game}</td>
      `;
      seasonsBody.appendChild(row);
    });
  } catch (err) {
    console.error("Fetch error:", err);
    resultText.textContent = "Failed to load player data.";
  }
}

// Guess Logic
document.getElementById("submitGuess").addEventListener("click", () => {
    const guess = document.getElementById("guessInput").value.trim().toLowerCase();
    const resultText = document.getElementById("resultText");
    const playerNameEl = document.getElementById("playerName");

    if (!currentPlayerName) return;

    if (guess === currentPlayerName.toLowerCase()) {
        streak++;
        resultText.textContent = `✅ Correct!`;
        resultText.className = "mt-4 font-bold text-center text-xl text-green-600";
    } else {
        streak = 0;
        resultText.textContent = `❌ Incorrect! It was ${currentPlayerName}`;
        resultText.className = "mt-4 font-bold text-center text-xl text-red-600";
    }

    playerNameEl.textContent = currentPlayerName;
    playerNameEl.className = "text-2xl font-black text-center mb-4 text-blue-700 uppercase tracking-normal";
    document.getElementById("streak").textContent = streak;
    document.getElementById("nextRound").style.display = "inline-block";
    document.getElementById("submitGuess").disabled = true;
});

// Give Up
document.getElementById("giveUp").addEventListener("click", () => {
    if (!currentPlayerName) return;
    streak = 0;
    document.getElementById("streak").textContent = streak;
    document.getElementById("playerName").textContent = currentPlayerName;
    document.getElementById("playerName").className = "text-2xl font-black text-center mb-4 text-gray-700 uppercase tracking-normal";
    document.getElementById("resultText").textContent = "You gave up!";
    document.getElementById("nextRound").style.display = "inline-block";
});

document.getElementById("nextRound").addEventListener("click", loadRandomPlayer);

// Autocomplete
const guessInput = document.getElementById("guessInput");
const suggestionsDiv = document.getElementById("suggestions");

guessInput.addEventListener("input", () => {
    const query = guessInput.value.toLowerCase().trim();
    if (query.length < 3) {
        suggestionsDiv.classList.add("hidden");
        return;
    }

    const matches = playerNames
        .filter(name => name.toLowerCase().includes(query))
        .slice(0, 10);

    if (matches.length === 0) {
        suggestionsDiv.classList.add("hidden");
        return;
    }

    suggestionsDiv.innerHTML = matches
        .map(name => `<div class="p-2 hover:bg-gray-200 cursor-pointer" onclick="selectSuggestion('${name.replace(/'/g, "\\'")}')">${name}</div>`)
        .join("");
    suggestionsDiv.classList.remove("hidden");
});

function selectSuggestion(name) {
    guessInput.value = name;
    suggestionsDiv.classList.add("hidden");
}

// Initial Load
window.onload = loadRandomPlayer;