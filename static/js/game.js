let playerNames = [];
let currentPlayerName = "";
let streak = 0;

// Fetch all players for autocomplete
fetch("/all_players")
  .then(res => res.json())
  .then(data => playerNames = data)
  .catch(err => console.error("Error loading player list:", err));

async function loadRandomPlayer() {
    // 1. Reset the table and UI
    const seasonsBody = document.getElementById("seasonsBody");
    const resultText = document.getElementById("resultText");
    const playerNameEl = document.getElementById("playerName");
    const guessInput = document.getElementById("guessInput");

    seasonsBody.innerHTML = "";
    resultText.textContent = "";
    guessInput.value = "";
    playerNameEl.textContent = "??????";

    // 2. Grab settings from hidden inputs in your guess.html
    const start = document.getElementById("startSeason").value;
    const end = document.getElementById("endSeason").value;
    const types = document.getElementById("types").value; 

    try {
        // 3. The Fetch (Make sure this URL matches your app.py route)
        const res = await fetch(`/random_player?start_season=${start}&end_season=${end}&types=${types}`);
        const data = await res.json();

        if (data.error) {
            console.error("Backend Error:", data.error);
            return;
        }

        currentPlayerName = data.player_name;

        // 4. Fill the table
        data.seasons.forEach(s => {
            const row = document.createElement("tr");
            row.className = "border-b border-gray-800 hover:bg-gray-900";
            row.innerHTML = `
                <td class="p-2 text-blue-400 font-bold">${s.season}</td>
                <td class="p-2">${s.tm}</td>
                <td class="p-2">${s.g}</td>
                <td class="p-2">${s.gs}</td>
                <td class="p-2">${s.mp_per_game}</td>
                <td class="p-2 text-yellow-500 font-bold">${s.pts_per_game}</td>
                <td class="p-2">${s.ast_per_game}</td>
                <td class="p-2">${s.trb_per_game}</td>
            `;
            seasonsBody.appendChild(row);
        });
    } catch (err) {
        console.error("Failed to fetch player:", err);
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