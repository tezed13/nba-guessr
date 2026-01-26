let playerNames = [];
let currentPlayerName = "";
let streak = 0;

// Fetch all players for autocomplete
fetch("/all_players")
  .then(res => res.json())
  .then(data => playerNames = data)
  .catch(err => console.error("Error loading player list:", err));

async function loadRandomPlayer() {
    // Reset UI
    document.getElementById("seasonsBody").innerHTML = "";
    document.getElementById("resultText").textContent = "";
    document.getElementById("guessInput").value = "";
    document.getElementById("playerName").textContent = "??????";
    document.getElementById("playerName").className = "text-2xl font-black text-center mb-4 text-gray-300 tracking-widest uppercase";
    document.getElementById("nextRound").style.display = "none";
    document.getElementById("submitGuess").disabled = false;

    const start = document.getElementById("startSeason").value;
    const end = document.getElementById("endSeason").value;
    const types = document.getElementById("types").value;

    const res = await fetch(`/random_player?start_season=${start}&end_season=${end}&types=${types}`);
    const data = await res.json();

    if (data.error) {
        document.getElementById("resultText").textContent = data.error;
        return;
    }

    currentPlayerName = data.player_name;
    
    data.seasons.forEach(s => {
        const row = `<tr>
            <td class="border p-2">${s.season}</td>
            <td class="border p-2">${s.tm}</td>
            <td class="border p-2">${s.g}</td>
            <td class="border p-2">${s.gs}</td>
            <td class="border p-2">${s.mp_per_game}</td>
            <td class="border p-2">${s.pts_per_game}</td>
            <td class="border p-2">${s.ast_per_game}</td>
            <td class="border p-2">${s.trb_per_game}</td>
        </tr>`;
        document.getElementById("seasonsBody").innerHTML += row;
    });
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