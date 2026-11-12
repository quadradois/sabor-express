// Cronômetros calculados só pelo data-fim (sem rede): trocar de etapa não perde nada.
(function () {
  var audio;
  try { audio = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) {}
  function liberar() { if (audio && audio.state !== "running") audio.resume().catch(function () {}); }
  function bipe() {
    liberar();
    if (!audio || audio.state !== "running") return;
    var o = audio.createOscillator();
    o.frequency.value = 880;
    o.connect(audio.destination);
    o.start();
    o.stop(audio.currentTime + 0.3);
  }
  function dois(n) { return (n < 10 ? "0" : "") + n; }
  function tique() {
    var tocar = false, mudo = !audio || audio.state !== "running";
    document.querySelectorAll("[data-fim]").forEach(function (el) {
      var s = Math.max(0, Math.ceil((Date.parse(el.dataset.fim) - Date.now()) / 1000));
      el.querySelector(".resta").textContent = dois(Math.floor(s / 60)) + ":" + dois(s % 60);
      if (s === 0) { el.classList.add("tocando"); tocar = true; }
      el.classList.toggle("mudo", s === 0 && mudo);  // som bloqueado: mostra "Tocar som"
    });
    if (tocar) bipe();
  }
  function acordar() {
    if (navigator.wakeLock && document.visibilityState === "visible")
      navigator.wakeLock.request("screen").catch(function () {});
  }
  // o navegador só libera o som depois de um toque na página
  document.addEventListener("pointerdown", liberar);
  document.addEventListener("visibilitychange", acordar);
  acordar();
  tique();
  setInterval(tique, 1000);
})();
