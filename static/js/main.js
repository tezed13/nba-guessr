document.getElementById("filters").addEventListener("submit", async (e) => {
    e.preventDefault();
  
    const start = document.getElementById("start_season").value;
    const end = document.getElementById("end_season").value;
    const types = Array.from(document.querySelectorAll("input[type=checkbox]:checked")).map(el => el.value);
  
    const url = `/random_player?start_season=${start}&end_season=${end}&types=${types.join(",")}`;
    const res = await fetch(url);
    const data = await res.json();
  
    const statsDiv = document.getElementById("stats");
    if (data.error) {
      statsDiv.innerHTML = `<p>${data.error}</p>`;
      return;
    }
  
    statsDiv.innerHTML = `
      <h3>Guess this player!</h3>
      <table>
        <tr><td>Season:</td><td>${data.season}</td></tr>
        <tr><td>Team:</td><td>${data.tm}</td></tr>
        <tr><td>PTS:</td><td>${data.pts}</td></tr>
        <tr><td>AST:</td><td>${data.ast}</td></tr>
        <tr><td>TRB:</td><td>${data.trb}</td></tr>
        <tr><td>GP:</td><td>${data.gp}</td></tr>
        <tr><td>GS:</td><td>${data.gs}</td></tr>
        <tr><td>MP:</td><td>${data.mp_per_g}</td></tr>
      </table>
    `;
  
    document.getElementById("guess-section").style.display = "block";
    document.getElementById("check").onclick = async () => {
      const guess = document.getElementById("guess").value.trim();
      const result = document.getElementById("result");
      const playerRes = await fetch(`/players/${data.player_id}/career_stats`);
      const playerData = await playerRes.json();
      const realName = playerData[0]?.player || "Unknown";
      result.textContent = guess.toLowerCase() === realName.toLowerCase() ? "✅ Correct!" : `❌ Nope, it was ${realName}.`;
    };
  });
  