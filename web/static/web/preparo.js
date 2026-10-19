// Cronômetros calculados só pelo data-fim (sem rede): trocar de etapa não perde nada.
(function () {
  var audio;
  function som() { return audio || (audio = new (window.AudioContext || window.webkitAudioContext)()); }
  function bipe() {
    var a = som(), o = a.createOscillator();
    o.frequency.value = 880;
    o.connect(a.destination);
    o.start();
    o.stop(a.currentTime + 0.3);
  }
  function dois(n) { return (n < 10 ? "0" : "") + n; }
  function tique() {
    var tocar = false;
    document.querySelectorAll("[data-fim]").forEach(function (el) {
      var s = Math.max(0, Math.ceil((Date.parse(el.dataset.fim) - Date.now()) / 1000));
      el.querySelector(".resta").textContent = dois(Math.floor(s / 60)) + ":" + dois(s % 60);
      if (s === 0) { el.classList.add("tocando"); tocar = true; }
    });
    if (tocar) try { bipe(); } catch (e) {}
  }
  function acordar() {
    if (navigator.wakeLock && document.visibilityState === "visible")
      navigator.wakeLock.request("screen").catch(function () {});
  }
  // o navegador só libera o som depois de um toque na página
  document.addEventListener("pointerdown", function () { try { som().resume(); } catch (e) {} });
  document.addEventListener("visibilitychange", acordar);
  acordar();
  tique();
  setInterval(tique, 1000);
})();
