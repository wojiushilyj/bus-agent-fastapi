(function () {
  "use strict";

  const apiState = {
    simulation: null,
    snapshot: null,
    forecast: null,
    actions: [],
    requestSerial: 0,
  };

  const originalRenderAlerts = renderAlerts;
  const originalRenderActions = renderActions;
  const originalLineLoadBefore = lineLoadBefore;
  const originalLineLoadAfter = lineLoadAfter;
  const originalUpdateHourStat = updateHourStat;
  const originalSelectSpot = selectSpot;

  async function api(path, options) {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    if (!response.ok) {
      let message = "服务请求失败";
      try {
        const body = await response.json();
        message = body.detail || message;
      } catch (_) {
        // 保留通用错误信息。
      }
      throw new Error(message);
    }
    return response.json();
  }

  function serverRenderAlerts() {
    if (!apiState.snapshot) {
      originalRenderAlerts();
      return;
    }
    const box = document.getElementById("alertList");
    const alerts = apiState.snapshot.alerts;
    document.getElementById("kpiAlert").textContent = alerts.length + " 条";
    if (!alerts.length) {
      box.innerHTML = '<div class="empty">当前时刻预测畅通，无拥堵预警</div>';
      return;
    }
    box.innerHTML = alerts.map((item) => {
      const levelClass = item.severity === "重度" ? "lv-h" : "lv-m";
      return '<div class="alert"><span class="lv ' + levelClass + '">' + item.severity +
        '</span><span class="ln">' + item.spot_name + '</span><span style="color:var(--sub);font-size:11.5px">' +
        item.line_name + '</span><span class="lt">' + item.note + "</span></div>";
    }).join("");
  }

  function serverRenderActions() {
    if (!apiState.actions.length) {
      originalRenderActions();
      return;
    }
    document.getElementById("actList").innerHTML = apiState.actions.map((action) =>
      '<div class="act"><span class="badge">' + action.type + '</span><div style="flex:1;min-width:0"><div class="at">' +
      action.title + '</div><div class="ad">' + action.detail + '</div><div class="basis">💡 决策依据 · 可解释AI：' +
      action.basis + '</div></div><span class="ae">' + action.effect + "</span></div>"
    ).join("");
  }

  renderAlerts = serverRenderAlerts;
  renderActions = serverRenderActions;
  lineLoadBefore = function (lineId) {
    const value = apiState.snapshot && apiState.snapshot.line_loads[lineId];
    return value ? value.before : originalLineLoadBefore(lineId);
  };
  lineLoadAfter = function (lineId) {
    const value = apiState.snapshot && apiState.snapshot.line_loads[lineId];
    return value ? value.after : originalLineLoadAfter(lineId);
  };
  updateHourStat = function () {
    const data = apiState.forecast;
    if (!data || data.spot.id !== cur || data.scenario !== scenario) {
      originalUpdateHourStat();
      return;
    }
    document.getElementById("hourStat").innerHTML = "当前 <b>" + data.scenario_name + "</b> " +
      pad2(hour) + ":00 · " + data.spot.name + " 预测 <b>" + data.values[hour] + "</b> 人/时";
  };

  async function refreshSnapshot() {
    const serial = ++apiState.requestSerial;
    const data = await api("/api/snapshot?hour=" + hour + "&scenario=" + encodeURIComponent(scenario));
    if (serial !== apiState.requestSerial) return;
    apiState.snapshot = data;
    renderAlerts();
    applyLineLoadColors();
  }

  async function refreshForecast() {
    const requestedSpot = cur;
    const requestedScenario = scenario;
    const data = await api("/api/forecast?spot_id=" + encodeURIComponent(requestedSpot) +
      "&scenario=" + encodeURIComponent(requestedScenario));
    if (requestedSpot !== cur || requestedScenario !== scenario) return;
    apiState.forecast = data;
    // 保持原型绘图函数不变，仅把后端返回的基准曲线注入其数据源。
    FC[data.spot.id] = data.curves.normal.slice();
    drawForecast(cur, false);
    updateHourStat();
  }

  function reportConnectionError(error) {
    status.textContent = "后端服务连接失败：" + error.message;
  }

  runBtn.onclick = async function () {
    if (running) return;
    running = true;
    runBtn.disabled = true;
    runBtn.textContent = "⏳ 推演中…";
    resetState(false);
    hour = 11;
    timeSlider.value = 11;
    hourLabel.textContent = "11:00";
    try {
      await Promise.all([refreshSnapshot(), refreshForecast()]);
      apiState.simulation = await api("/api/simulations", {
        method: "POST",
        body: JSON.stringify({ scenario: scenario, hour: hour, spot_id: cur }),
      });
      apiState.actions = apiState.simulation.actions;
      let nextStage = 0;
      const timer = setInterval(function () {
        nextStage += 1;
        setStage(nextStage, true);
        if (nextStage >= 3) {
          clearInterval(timer);
          running = false;
          document.getElementById("kpiPlan").textContent = "0 项";
        }
      }, 900);
    } catch (error) {
      running = false;
      runBtn.disabled = false;
      runBtn.textContent = "▶ 运行智能体推演";
      reportConnectionError(error);
    }
  };

  disBtn.onclick = async function () {
    if (stage < 3 || !apiState.simulation) return;
    disBtn.disabled = true;
    try {
      apiState.simulation = await api("/api/simulations/" + apiState.simulation.id + "/dispatch", { method: "POST" });
      dispatched = true;
      setStage(4, true);
      document.getElementById("kpiPlan").textContent = apiState.simulation.actions.length + " 项";
      setTimeout(async function () {
        try {
          apiState.simulation = await api("/api/simulations/" + apiState.simulation.id + "/evaluate", { method: "POST" });
          setStage(5, true);
        } catch (error) {
          disBtn.disabled = false;
          reportConnectionError(error);
        }
      }, 1100);
    } catch (error) {
      disBtn.disabled = false;
      reportConnectionError(error);
    }
  };

  resetBtn.onclick = function () {
    apiState.simulation = null;
    apiState.actions = [];
    resetState(true);
    Promise.all([refreshSnapshot(), refreshForecast()]).catch(reportConnectionError);
  };

  let sliderTimer;
  timeSlider.oninput = function () {
    hour = +timeSlider.value;
    hourLabel.textContent = pad2(hour) + ":00";
    renderMapCongestion();
    drawForecast(cur, false);
    clearTimeout(sliderTimer);
    sliderTimer = setTimeout(function () {
      Promise.all([refreshSnapshot(), refreshForecast()]).catch(reportConnectionError);
    }, 90);
  };

  scSel.onchange = function () {
    scenario = scSel.value;
    renderMapCongestion();
    drawForecast(cur, false);
    Promise.all([refreshSnapshot(), refreshForecast()]).catch(reportConnectionError);
  };

  selectSpot = function (id) {
    originalSelectSpot(id);
    refreshForecast().catch(reportConnectionError);
  };
  document.addEventListener("click", function (event) {
    if (event.target.closest && event.target.closest("#spotChips .chip")) {
      setTimeout(function () { refreshForecast().catch(reportConnectionError); }, 0);
    }
  });

  document.getElementById("exportBtn").onclick = async function () {
    buildPrintSheet();
    if (apiState.simulation) {
      try {
        await api("/api/simulations/" + apiState.simulation.id + "/exports", { method: "POST" });
      } catch (error) {
        reportConnectionError(error);
        return;
      }
    }
    setTimeout(function () { window.print(); }, 60);
  };

  Promise.all([api("/api/health"), refreshSnapshot(), refreshForecast()]).catch(reportConnectionError);
})();
