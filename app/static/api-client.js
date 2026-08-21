(function () {
  "use strict";

  const apiState = {
    simulation: null,
    snapshot: null,
    forecast: null,
    config: null,
    actions: [],
    requestSerial: 0,
    workflowSerial: 0,
  };

  const originalRenderAlerts = renderAlerts;
  const originalRenderActions = renderActions;
  const originalLineLoadBefore = lineLoadBefore;
  const originalLineLoadAfter = lineLoadAfter;
  const originalUpdateHourStat = updateHourStat;
  const originalSelectSpot = selectSpot;
  const originalApplyLineLoadColors = applyLineLoadColors;
  const originalRenderMapCongestion = renderMapCongestion;
  const originalShowDispatch = showDispatch;
  const originalResetState = resetState;

  const mapWrap = document.querySelector(".mapwrap");
  const mapNote = document.getElementById("mapNote");
  const mapModeBtn = document.getElementById("mapModeBtn");
  const serviceDot = document.getElementById("serviceDot");
  const serviceText = document.getElementById("serviceText");
  const dataTime = document.getElementById("dataTime");
  const historyDetail = document.getElementById("historyDetail");
  const transitControl = document.getElementById("transitControl");
  const transitRouteSelect = document.getElementById("transitRouteSelect");
  const transitPlayBtn = document.getElementById("transitPlayBtn");
  const transitDirectionBtn = document.getElementById("transitDirectionBtn");
  const transitSpeed = document.getElementById("transitSpeed");
  const transitProgressBar = document.getElementById("transitProgressBar");
  const transitProgressText = document.getElementById("transitProgressText");
  const transitStatus = document.getElementById("transitStatus");
  const transitSource = document.getElementById("transitSource");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  let geoMap = null;
  let geoLines = {};
  let geoSpots = {};
  let geoCongestionLayer = null;
  let geoVehicleLayer = null;
  let geoVehicleFrame = null;
  let tileErrors = 0;
  let tileFallbackTimer = null;
  let stageTimer = null;
  let evaluationTimer = null;
  let healthTimer = null;
  let transitRouteLayer = null;
  let transitVehicleLayer = null;
  let transitTrailLayer = null;
  let transitRoutes = [];
  let activeTransitRoute = null;
  let transitSampler = null;
  let transitMarkers = [];
  let transitTrail = null;
  let transitTrailPoints = [];
  let transitAnimationFrame = null;
  let transitLastFrame = null;
  let transitProgress = 0;
  let transitRunning = false;
  let transitReverse = false;
  let transitResumeAfterVisibility = false;

  async function api(path, options) {
    const requestOptions = options || {};
    const controller = new AbortController();
    const timeout = setTimeout(function () { controller.abort(); }, 10000);
    const headers = { Accept: "application/json", ...(requestOptions.headers || {}) };
    if (requestOptions.body !== undefined) headers["Content-Type"] = "application/json";
    try {
      const response = await fetch(path, {
        ...requestOptions,
        headers: headers,
        cache: "no-store",
        credentials: "same-origin",
        signal: controller.signal,
      });
      if (!response.ok) {
        let message = "服务请求失败（HTTP " + response.status + "）";
        try {
          const body = await response.json();
          message = body.detail || message;
        } catch (_) {
          // 非 JSON 错误响应保留状态码信息。
        }
        throw new Error(message);
      }
      return await response.json();
    } catch (error) {
      if (error.name === "AbortError") throw new Error("服务请求超时，请稍后重试");
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, function (character) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[character];
    });
  }

  function formatPassengers(value) {
    const wan = Number(value) / 10000;
    return wan.toFixed(1).replace(/\.0$/, "") + "万";
  }

  function formatLocalTime(value, withDate) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    const options = withDate
      ? { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }
      : { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false };
    return new Intl.DateTimeFormat("zh-CN", options).format(date);
  }

  function setServiceState(ok, message) {
    serviceDot.classList.toggle("ok", ok);
    serviceDot.classList.toggle("err", !ok);
    serviceText.textContent = message;
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
      return '<div class="alert"><span class="lv ' + levelClass + '">' + escapeHtml(item.severity) +
        '</span><span class="ln">' + escapeHtml(item.spot_name) + '</span><span style="color:var(--sub);font-size:11.5px">' +
        escapeHtml(item.line_name) + '</span><span class="lt">' + escapeHtml(item.note) + "</span></div>";
    }).join("");
  }

  function serverRenderActions() {
    if (!apiState.simulation) {
      originalRenderActions();
      return;
    }
    if (!apiState.actions.length) {
      document.getElementById("actList").innerHTML =
        '<div class="empty">当前场景无需新增弹性调度指令</div>';
      return;
    }
    document.getElementById("actList").innerHTML = apiState.actions.map((action) =>
      '<div class="act"><span class="badge">' + escapeHtml(action.type) +
      '</span><div style="flex:1;min-width:0"><div class="at">' + escapeHtml(action.title) +
      '</div><div class="ad">' + escapeHtml(action.detail) +
      '</div><div class="basis">💡 决策依据 · 可解释AI：' + escapeHtml(action.basis) +
      '</div></div><span class="ae">' + escapeHtml(action.effect) + "</span></div>"
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
    document.getElementById("hourStat").innerHTML = "当前 <b>" + escapeHtml(data.scenario_name) + "</b> " +
      pad2(hour) + ":00 · " + escapeHtml(data.spot.name) + " 预测 <b>" + data.values[hour] + "</b> 人/时";
  };

  function initGeoMap(config) {
    if (!window.L || !config || !config.map) {
      mapModeBtn.disabled = true;
      mapModeBtn.textContent = "当前为示意图";
      mapNote.textContent = "真实底图库未加载，已使用线网示意图";
      return;
    }

    geoMap = L.map("geoMap", {
      zoomControl: true,
      attributionControl: true,
      preferCanvas: true,
      minZoom: 8,
      maxZoom: config.map.max_zoom || 19,
    });
    geoMap.fitBounds(config.map.bounds, { padding: [18, 18] });
    const tileLayer = L.tileLayer(config.map.tile_url, {
      maxZoom: config.map.max_zoom || 19,
      attribution: config.map.tile_attribution,
    }).addTo(geoMap);
    tileFallbackTimer = setTimeout(function () {
      if (!mapWrap.classList.contains("geo-ready")) {
        mapModeBtn.disabled = true;
        mapModeBtn.textContent = "当前为示意图";
        mapNote.textContent = "底图加载超时，已自动使用线网示意图";
      }
    }, 8000);
    tileLayer.once("tileload", function () {
      clearTimeout(tileFallbackTimer);
      mapWrap.classList.add("geo-ready");
      mapModeBtn.disabled = false;
      mapModeBtn.textContent = "切换示意图";
      mapNote.textContent = "真实地理底图 · 点击站点查看预测曲线";
      setTimeout(function () { geoMap.invalidateSize(); }, 0);
    });
    tileLayer.on("tileerror", function () {
      tileErrors += 1;
      if (tileErrors >= 4 && !mapWrap.classList.contains("geo-ready")) {
        mapModeBtn.disabled = true;
        mapModeBtn.textContent = "当前为示意图";
        mapNote.textContent = "底图服务暂不可用，已自动使用线网示意图";
      }
    });

    geoCongestionLayer = L.layerGroup().addTo(geoMap);
    geoVehicleLayer = L.layerGroup().addTo(geoMap);
    transitRouteLayer = L.layerGroup().addTo(geoMap);
    transitTrailLayer = L.layerGroup().addTo(geoMap);
    transitVehicleLayer = L.layerGroup().addTo(geoMap);
    config.lines.forEach(function (line) {
      geoLines[line.id] = L.polyline(line.route, {
        color: line.color,
        weight: 4,
        opacity: 0.78,
        lineCap: "round",
        lineJoin: "round",
      }).addTo(geoMap).bindTooltip(escapeHtml(line.name), { sticky: true });
    });
    config.spots.forEach(function (spot) {
      const marker = L.circleMarker([spot.latitude, spot.longitude], {
        radius: 6,
        color: spot.group === "ys" ? "#00b386" : "#1e6fff",
        weight: 3,
        fillColor: "#ffffff",
        fillOpacity: 1,
      }).addTo(geoMap);
      marker.bindTooltip(escapeHtml(spot.name), {
        permanent: true,
        direction: "top",
        offset: [0, -7],
        className: "geo-spot-label",
      });
      marker.bindPopup("<b>" + escapeHtml(spot.name) + "</b><br>点击后同步查看 24h 客流预测");
      marker.on("click", function () { selectSpot(spot.id); });
      geoSpots[spot.id] = marker;
    });

    mapModeBtn.onclick = function () {
      if (!mapWrap.classList.contains("geo-ready")) return;
      const schematic = mapWrap.classList.toggle("force-schematic");
      mapModeBtn.textContent = schematic ? "切换真实底图" : "切换示意图";
      mapNote.textContent = schematic
        ? "线网示意图（离线降级视图）"
        : "真实地理底图 · 点击站点查看预测曲线";
      if (schematic && transitRunning) pauseTransit();
      if (!schematic) setTimeout(function () { geoMap.invalidateSize(); }, 0);
    };
    updateGeoLineStyles();
    updateGeoCongestion();
    updateGeoSpotStyles();
  }

  function updateGeoSpotStyles() {
    Object.keys(geoSpots).forEach(function (spotId) {
      const selected = spotId === cur;
      geoSpots[spotId].setStyle({
        radius: selected ? 9 : 6,
        weight: selected ? 4 : 3,
        fillColor: selected ? "#fff3cd" : "#ffffff",
      });
    });
  }

  function updateGeoLineStyles() {
    if (!geoMap || !apiState.config) return;
    apiState.config.lines.forEach(function (line) {
      const layer = geoLines[line.id];
      if (!layer) return;
      let color = line.color;
      let opacity = 0.78;
      let weight = 4;
      if (activeTransitRoute) {
        opacity = 0.22;
        weight = 3;
      }
      if (compareMode !== "off") {
        color = loadColor(compareMode === "before" ? lineLoadBefore(line.id) : lineLoadAfter(line.id));
        opacity = 0.95;
        weight = 6;
      } else if (dispatchShown && apiState.actions.some(function (action) { return action.line_id === line.id; })) {
        opacity = 1;
        weight = 7;
      }
      layer.setStyle({ color: color, opacity: opacity, weight: weight });
    });
  }

  function updateGeoCongestion() {
    if (!geoMap || !geoCongestionLayer || !apiState.snapshot || !apiState.config) return;
    geoCongestionLayer.clearLayers();
    apiState.snapshot.alerts.forEach(function (alert) {
      const spot = apiState.config.spots.find(function (item) { return item.id === alert.spot_id; });
      if (!spot) return;
      const color = alert.severity === "重度" ? "#f5222d" : "#ff7a45";
      L.circle([spot.latitude, spot.longitude], {
        radius: 650 + alert.intensity * 1450,
        color: color,
        weight: 2,
        fillColor: color,
        fillOpacity: 0.16,
        className: "geo-congestion-pulse",
      }).addTo(geoCongestionLayer).bindTooltip(
        escapeHtml(alert.severity + "拥堵 · " + alert.note)
      );
    });
  }

  function routePoint(route, progress) {
    if (route.length < 2) return route[0];
    const scaled = progress * (route.length - 1);
    const index = Math.min(route.length - 2, Math.floor(scaled));
    const local = scaled - index;
    return [
      route[index][0] + (route[index + 1][0] - route[index][0]) * local,
      route[index][1] + (route[index + 1][1] - route[index][1]) * local,
    ];
  }

  function geoDistanceMeters(first, second) {
    const radians = Math.PI / 180;
    const latitude1 = first[0] * radians;
    const latitude2 = second[0] * radians;
    const latitudeDelta = (second[0] - first[0]) * radians;
    const longitudeDelta = (second[1] - first[1]) * radians;
    const value = Math.sin(latitudeDelta / 2) ** 2 + Math.cos(latitude1) * Math.cos(latitude2) *
      Math.sin(longitudeDelta / 2) ** 2;
    return 6371000 * 2 * Math.atan2(Math.sqrt(value), Math.sqrt(1 - value));
  }

  function buildTransitSampler(points) {
    if (!Array.isArray(points) || points.length < 2) return null;
    const cumulative = [0];
    for (let index = 1; index < points.length; index += 1) {
      cumulative.push(cumulative[index - 1] + geoDistanceMeters(points[index - 1], points[index]));
    }
    const total = cumulative[cumulative.length - 1];
    if (!Number.isFinite(total) || total <= 0) return null;
    return {
      distance: total,
      pointAt: function (rawProgress) {
        const progress = Math.max(0, Math.min(1, rawProgress));
        const target = progress * total;
        let low = 0;
        let high = cumulative.length - 1;
        while (low + 1 < high) {
          const middle = Math.floor((low + high) / 2);
          if (cumulative[middle] <= target) low = middle;
          else high = middle;
        }
        const segmentLength = cumulative[high] - cumulative[low];
        const local = segmentLength > 0 ? (target - cumulative[low]) / segmentLength : 0;
        return [
          points[low][0] + (points[high][0] - points[low][0]) * local,
          points[low][1] + (points[high][1] - points[low][1]) * local,
        ];
      },
    };
  }

  function transitDisplayProgress(progress) {
    return transitReverse ? 1 - progress : progress;
  }

  function updateTransitProgress() {
    const displayed = transitDisplayProgress(transitProgress);
    const percent = Math.round(displayed * 100);
    transitProgressBar.style.width = percent + "%";
    transitProgressText.textContent = percent + "%";
  }

  function ensureTransitMarkers() {
    if (!transitVehicleLayer || transitMarkers.length) return;
    ["主车", "跟车一", "跟车二"].forEach(function (label) {
      const marker = L.marker([0, 0], {
        interactive: false,
        opacity: 0,
        icon: L.divIcon({
          className: "transit-bus",
          html: '<span aria-hidden="true">🚌</span>',
          iconSize: [26, 26],
        }),
      }).addTo(transitVehicleLayer);
      marker._transitLabel = label;
      transitMarkers.push(marker);
    });
  }

  function renderTransitFrame() {
    if (!transitSampler) return;
    ensureTransitMarkers();
    const offsets = [0, 0.34, 0.68];
    offsets.forEach(function (offset, index) {
      const logical = (transitProgress + offset) % 1;
      const position = transitSampler.pointAt(transitDisplayProgress(logical));
      transitMarkers[index].setLatLng(position).setOpacity(index === 0 ? 1 : 0.78);
    });
    const primaryPosition = transitSampler.pointAt(transitDisplayProgress(transitProgress));
    transitTrailPoints.push(primaryPosition);
    if (transitTrailPoints.length > 48) transitTrailPoints.shift();
    if (!transitTrail) {
      transitTrail = L.polyline(transitTrailPoints, {
        color: activeTransitRoute ? activeTransitRoute.color : "#1677ff",
        weight: 5,
        opacity: 0.52,
        dashArray: "3 7",
        lineCap: "round",
      }).addTo(transitTrailLayer);
    } else {
      transitTrail.setLatLngs(transitTrailPoints);
    }
    updateTransitProgress();
  }

  function pauseTransit(resetProgress) {
    if (transitAnimationFrame) cancelAnimationFrame(transitAnimationFrame);
    transitAnimationFrame = null;
    transitLastFrame = null;
    transitRunning = false;
    transitPlayBtn.textContent = "▶ 运行轨迹";
    if (resetProgress) {
      transitProgress = 0;
      transitTrailPoints = [];
      if (transitTrailLayer) transitTrailLayer.clearLayers();
      transitTrail = null;
      if (transitSampler) renderTransitFrame();
      else updateTransitProgress();
    }
  }

  function startTransit() {
    if (!transitSampler || !activeTransitRoute || mapWrap.classList.contains("force-schematic")) return;
    if (reduceMotion) {
      transitProgress = (transitProgress + 0.08) % 1;
      transitTrailPoints = [];
      if (transitTrailLayer) transitTrailLayer.clearLayers();
      transitTrail = null;
      renderTransitFrame();
      transitStatus.textContent = "系统已启用减少动态：点击运行轨迹可逐段查看车辆位置";
      return;
    }
    if (transitRunning) return;
    transitRunning = true;
    transitPlayBtn.textContent = "❚❚ 暂停轨迹";
    function animate(now) {
      if (!transitRunning) return;
      if (transitLastFrame !== null) {
        const speed = Number(transitSpeed.value) || 1;
        const previous = transitProgress;
        transitProgress = (transitProgress + ((now - transitLastFrame) / 28000) * speed) % 1;
        if (transitProgress < previous) {
          transitTrailPoints = [];
          if (transitTrailLayer) transitTrailLayer.clearLayers();
          transitTrail = null;
        }
      }
      transitLastFrame = now;
      renderTransitFrame();
      transitAnimationFrame = requestAnimationFrame(animate);
    }
    transitAnimationFrame = requestAnimationFrame(animate);
  }

  function selectTransitRoute(routeId, fitRoute) {
    const route = transitRoutes.find(function (item) { return item.id === routeId; });
    if (!route || !geoMap || !transitRouteLayer) return;
    pauseTransit(false);
    transitRouteLayer.clearLayers();
    transitTrailLayer.clearLayers();
    transitVehicleLayer.clearLayers();
    transitMarkers = [];
    transitTrail = null;
    transitTrailPoints = [];
    transitProgress = 0;
    activeTransitRoute = route;
    transitSampler = buildTransitSampler(route.animation_path);
    const bounds = [];
    route.paths.forEach(function (path) {
      path.forEach(function (point) { bounds.push(point); });
      L.polyline(path, {
        color: "#ffffff",
        weight: 9,
        opacity: 0.9,
        lineCap: "round",
        lineJoin: "round",
      }).addTo(transitRouteLayer);
      L.polyline(path, {
        color: route.color,
        weight: 5,
        opacity: 0.94,
        lineCap: "round",
        lineJoin: "round",
      }).addTo(transitRouteLayer);
    });
    const start = route.animation_path[0];
    const end = route.animation_path[route.animation_path.length - 1];
    L.circleMarker(start, {
      radius: 6, color: route.color, weight: 3, fillColor: "#ffffff", fillOpacity: 1,
    }).addTo(transitRouteLayer).bindTooltip("起点 · " + escapeHtml(route.from));
    L.circleMarker(end, {
      radius: 6, color: route.color, weight: 3, fillColor: route.color, fillOpacity: 1,
    }).addTo(transitRouteLayer).bindTooltip("终点 · " + escapeHtml(route.to));
    transitRouteSelect.value = route.id;
    transitStatus.textContent = route.ref + "路 · " + route.from + " → " + route.to +
      " · 线路约 " + (transitSampler.distance / 1000).toFixed(1) + " km";
    transitDirectionBtn.textContent = transitReverse ? "⇄ 正向" : "⇄ 反向";
    renderTransitFrame();
    updateGeoLineStyles();
    if (fitRoute && bounds.length) geoMap.fitBounds(bounds, { padding: [48, 48], maxZoom: 14 });
  }

  async function refreshTransitRoutes() {
    const data = await api("/api/transit/routes");
    if (!Array.isArray(data.items) || !data.items.length) throw new Error("未找到可绘制的桂林公交线路");
    transitRoutes = data.items;
    transitRouteSelect.innerHTML = transitRoutes.map(function (route) {
      return '<option value="' + escapeHtml(route.id) + '">' + escapeHtml(
        route.ref + "路｜" + route.from + " → " + route.to
      ) + "</option>";
    }).join("");
    transitControl.hidden = !geoMap;
    const timestamp = formatLocalTime(data.osm_base_timestamp || data.generated_at, true);
    transitSource.textContent = data.attribution + " · ODbL · 数据快照 " + timestamp +
      "；车辆位置为轨迹推演，不是官方实时 GPS";
    selectTransitRoute(transitRoutes[0].id, true);
  }

  transitRouteSelect.addEventListener("change", function () {
    selectTransitRoute(transitRouteSelect.value, true);
  });
  transitPlayBtn.addEventListener("click", function () {
    if (transitRunning) pauseTransit(false);
    else startTransit();
  });
  transitDirectionBtn.addEventListener("click", function () {
    const wasRunning = transitRunning;
    pauseTransit(false);
    transitReverse = !transitReverse;
    transitDirectionBtn.textContent = transitReverse ? "⇄ 正向" : "⇄ 反向";
    transitTrailPoints = [];
    if (transitTrailLayer) transitTrailLayer.clearLayers();
    transitTrail = null;
    renderTransitFrame();
    if (wasRunning) startTransit();
  });

  function stopGeoVehicles() {
    if (geoVehicleFrame) cancelAnimationFrame(geoVehicleFrame);
    geoVehicleFrame = null;
    if (geoVehicleLayer) geoVehicleLayer.clearLayers();
  }

  function startGeoVehicles() {
    if (!geoMap || !geoVehicleLayer || !apiState.config) return;
    stopGeoVehicles();
    const moving = [];
    apiState.actions.forEach(function (action, index) {
      if (!action.line_id) return;
      const line = apiState.config.lines.find(function (item) { return item.id === action.line_id; });
      if (!line) return;
      const marker = L.marker(line.route[0], {
        interactive: false,
        icon: L.divIcon({ className: "geo-bus", html: "🚌", iconSize: [24, 24] }),
      }).addTo(geoVehicleLayer);
      moving.push({ marker: marker, route: line.route, offset: index * 0.22 });
    });
    if (reduceMotion || document.hidden || !moving.length) return;
    const startedAt = performance.now();
    function animate(now) {
      const base = ((now - startedAt) % 8000) / 8000;
      moving.forEach(function (item) {
        item.marker.setLatLng(routePoint(item.route, (base + item.offset) % 1));
      });
      geoVehicleFrame = requestAnimationFrame(animate);
    }
    geoVehicleFrame = requestAnimationFrame(animate);
  }

  applyLineLoadColors = function () {
    originalApplyLineLoadColors();
    updateGeoLineStyles();
  };
  renderMapCongestion = function () {
    originalRenderMapCongestion();
    updateGeoCongestion();
  };
  showDispatch = function () {
    originalShowDispatch();
    updateGeoLineStyles();
    startGeoVehicles();
  };
  resetState = function (full) {
    stopGeoVehicles();
    pauseTransit(true);
    originalResetState(full);
    updateGeoLineStyles();
    updateGeoCongestion();
    updateGeoSpotStyles();
  };

  async function refreshSnapshot() {
    const serial = ++apiState.requestSerial;
    const data = await api("/api/snapshot?hour=" + hour + "&scenario=" + encodeURIComponent(scenario));
    if (serial !== apiState.requestSerial) return;
    apiState.snapshot = data;
    document.getElementById("kpiPassengers").textContent = formatPassengers(data.predicted_total);
    dataTime.textContent = "数据时间 " + formatLocalTime(data.generated_at, false);
    renderAlerts();
    renderMapCongestion();
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

  function renderHistory(data) {
    const box = document.getElementById("historyList");
    document.getElementById("historyCount").textContent = "共 " + data.total + " 次";
    if (!data.items.length) {
      box.innerHTML = '<div class="empty">暂无推演记录，运行一次智能体推演后将在此留痕</div>';
      return;
    }
    const statusMap = { planned: "待下发", dispatched: "执行中", evaluated: "已评估" };
    const rows = data.items.map(function (item) {
      const scenarioName = SCENARIOS[item.scenario] ? SCENARIOS[item.scenario].name : item.scenario;
      return "<tr>" +
        '<td><span class="history-status ' + escapeHtml(item.status) + '">' + escapeHtml(statusMap[item.status] || item.status) + "</span></td>" +
        "<td>" + escapeHtml(scenarioName) + "</td>" +
        "<td>" + String(item.hour).padStart(2, "0") + ":00</td>" +
        "<td>" + item.alert_count + " 条</td>" +
        "<td>" + escapeHtml(item.worst_line) + "</td>" +
        '<td><span class="history-load">' + Math.round(item.before_load * 100) + "%</span> → " +
        '<span class="history-load history-load-after">' + Math.round(item.after_load * 100) + "%</span></td>" +
        "<td>" + Number(item.action_count) + " 项</td>" +
        "<td>" + formatLocalTime(item.created_at, true) + "</td>" +
        '<td><button type="button" class="history-view" data-id="' + escapeHtml(item.id) + '">查看</button></td>' +
        "</tr>";
    }).join("");
    box.innerHTML = '<div class="history-table-wrap"><table class="history-table"><thead><tr>' +
      "<th>状态</th><th>场景</th><th>时刻</th><th>预警</th><th>最紧张线路</th><th>满载率干预</th><th>指令</th><th>创建时间</th><th>详情</th>" +
      "</tr></thead><tbody>" + rows + "</tbody></table></div>";
    box.querySelectorAll(".history-view").forEach(function (button) {
      button.addEventListener("click", function () {
        showHistoryDetail(button.dataset.id).catch(reportHistoryError);
      });
    });
  }

  async function refreshHistory() {
    renderHistory(await api("/api/simulations?limit=8"));
  }

  function renderHistoryDetail(detail) {
    const statusMap = { planned: "待下发", dispatched: "执行中", evaluated: "已评估" };
    const scenarioName = SCENARIOS[detail.scenario] ? SCENARIOS[detail.scenario].name : detail.scenario;
    const events = detail.events.map(function (event) {
      return '<div class="history-event"><b>阶段 ' + Number(event.stage) + " · " +
        escapeHtml(event.agent_name) + "</b>　" + escapeHtml(event.tool_name) + "：" +
        escapeHtml(event.message) + "</div>";
    }).join("");
    historyDetail.innerHTML =
      '<div class="history-detail-head"><strong>推演详情</strong><button type="button" class="history-view" id="historyDetailClose">关闭</button></div>' +
      '<div class="history-detail-grid">' +
      '<div class="history-detail-item">状态<b>' + escapeHtml(statusMap[detail.status] || detail.status) + "</b></div>" +
      '<div class="history-detail-item">场景与时刻<b>' + escapeHtml(scenarioName) + " · " + String(detail.hour).padStart(2, "0") + ":00</b></div>" +
      '<div class="history-detail-item">调度指令<b>' + Number(detail.actions.length) + " 项</b></div>" +
      '<div class="history-detail-item">导出次数<b>' + Number(detail.export_count) + " 次</b></div>" +
      "</div>" +
      '<div class="history-event"><b>最紧张线路</b>　' + escapeHtml(detail.worst_line) +
      "，满载率 " + Math.round(Number(detail.before_load) * 100) + "% → " +
      Math.round(Number(detail.after_load) * 100) + "%</div>" + events;
    historyDetail.hidden = false;
    document.getElementById("historyDetailClose").onclick = function () {
      historyDetail.hidden = true;
    };
    historyDetail.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "nearest" });
  }

  async function showHistoryDetail(simulationId) {
    historyDetail.hidden = false;
    historyDetail.innerHTML = '<div class="empty">正在读取推演详情…</div>';
    renderHistoryDetail(await api("/api/simulations/" + encodeURIComponent(simulationId)));
  }

  function reportHistoryError(error) {
    historyDetail.hidden = false;
    historyDetail.textContent = "历史记录读取失败：" + error.message;
  }

  function reportConnectionError(error) {
    setServiceState(false, "服务异常");
    status.textContent = "后端服务连接失败：" + error.message;
  }

  function clearWorkflowTimers() {
    if (stageTimer) clearInterval(stageTimer);
    if (evaluationTimer) clearTimeout(evaluationTimer);
    stageTimer = null;
    evaluationTimer = null;
  }

  function setExplorationDisabled(disabled) {
    timeSlider.disabled = disabled;
    scSel.disabled = disabled;
    document.getElementById("spotChips").querySelectorAll("button").forEach(function (button) {
      button.disabled = disabled;
    });
  }

  function clearActivePlan(message) {
    if (!running && !apiState.simulation && !apiState.actions.length) return;
    apiState.workflowSerial += 1;
    clearWorkflowTimers();
    running = false;
    setExplorationDisabled(false);
    apiState.simulation = null;
    apiState.snapshot = null;
    apiState.forecast = null;
    apiState.actions = [];
    window.busAgentRuntimeActions = null;
    resetState(false);
    if (message) status.textContent = message;
  }

  runBtn.onclick = async function () {
    if (running) return;
    const workflowSerial = ++apiState.workflowSerial;
    clearWorkflowTimers();
    apiState.simulation = null;
    apiState.actions = [];
    window.busAgentRuntimeActions = null;
    running = true;
    setExplorationDisabled(true);
    runBtn.disabled = true;
    runBtn.textContent = "⏳ 推演中…";
    resetState(false);
    hour = 11;
    timeSlider.value = 11;
    hourLabel.textContent = "11:00";
    try {
      await Promise.all([refreshSnapshot(), refreshForecast()]);
      if (workflowSerial !== apiState.workflowSerial) return;
      const simulation = await api("/api/simulations", {
        method: "POST",
        body: JSON.stringify({ scenario: scenario, hour: hour, spot_id: cur }),
      });
      if (workflowSerial !== apiState.workflowSerial) return;
      apiState.simulation = simulation;
      apiState.actions = apiState.simulation.actions;
      window.busAgentRuntimeActions = apiState.actions;
      refreshHistory().catch(reportHistoryError);
      let nextStage = 0;
      stageTimer = setInterval(function () {
        nextStage += 1;
        setStage(nextStage, true);
        if (nextStage >= 3) {
          clearInterval(stageTimer);
          stageTimer = null;
          running = false;
          setExplorationDisabled(false);
          document.getElementById("kpiPlan").textContent = "0 项";
          runBtn.textContent = "✓ 方案已生成";
        }
      }, 900);
    } catch (error) {
      if (workflowSerial !== apiState.workflowSerial) return;
      running = false;
      setExplorationDisabled(false);
      runBtn.disabled = false;
      runBtn.textContent = "▶ 运行智能体推演";
      reportConnectionError(error);
    }
  };

  disBtn.onclick = async function () {
    if (stage < 3 || !apiState.simulation) return;
    disBtn.disabled = true;
    const simulationId = apiState.simulation.id;
    try {
      apiState.simulation = await api("/api/simulations/" + simulationId + "/dispatch", { method: "POST" });
      dispatched = true;
      setStage(4, true);
      document.getElementById("kpiPlan").textContent = apiState.simulation.actions.length + " 项";
      refreshHistory().catch(reportHistoryError);
      // 后端评估请求立即发出；1.1 秒延迟仅用于保留原型的阶段演示节奏。
      const evaluation = api("/api/simulations/" + simulationId + "/evaluate", {
        method: "POST",
      }).then(
        function (value) { return { ok: true, value: value }; },
        function (error) { return { ok: false, error: error }; }
      );
      evaluationTimer = setTimeout(async function () {
        evaluationTimer = null;
        const result = await evaluation;
        if (!apiState.simulation || apiState.simulation.id !== simulationId) return;
        if (result.ok) {
          apiState.simulation = result.value;
          setStage(5, true);
          refreshHistory().catch(reportHistoryError);
        } else {
          disBtn.disabled = false;
          reportConnectionError(result.error);
        }
      }, 1100);
    } catch (error) {
      disBtn.disabled = false;
      reportConnectionError(error);
    }
  };

  resetBtn.onclick = function () {
    apiState.workflowSerial += 1;
    clearWorkflowTimers();
    running = false;
    setExplorationDisabled(false);
    apiState.simulation = null;
    apiState.snapshot = null;
    apiState.forecast = null;
    apiState.actions = [];
    window.busAgentRuntimeActions = null;
    historyDetail.hidden = true;
    resetState(true);
    Promise.all([refreshSnapshot(), refreshForecast()]).catch(reportConnectionError);
  };

  let sliderTimer;
  timeSlider.oninput = function () {
    hour = +timeSlider.value;
    hourLabel.textContent = pad2(hour) + ":00";
    clearActivePlan("参数已变化，请重新运行智能体推演生成匹配方案");
    renderMapCongestion();
    drawForecast(cur, false);
    clearTimeout(sliderTimer);
    sliderTimer = setTimeout(function () {
      Promise.all([refreshSnapshot(), refreshForecast()]).catch(reportConnectionError);
    }, 90);
  };

  scSel.onchange = function () {
    scenario = scSel.value;
    clearActivePlan("场景已变化，请重新运行智能体推演生成匹配方案");
    renderMapCongestion();
    drawForecast(cur, false);
    Promise.all([refreshSnapshot(), refreshForecast()]).catch(reportConnectionError);
  };

  selectSpot = function (id) {
    originalSelectSpot(id);
    updateGeoSpotStyles();
    clearActivePlan("景区已变化，请重新运行智能体推演生成匹配方案");
    refreshForecast().catch(reportConnectionError);
  };
  document.addEventListener("click", function (event) {
    if (event.target.closest && event.target.closest("#spotChips .chip")) {
      setTimeout(function () {
        updateGeoSpotStyles();
        clearActivePlan("景区已变化，请重新运行智能体推演生成匹配方案");
        refreshForecast().catch(reportConnectionError);
      }, 0);
    }
  });

  document.getElementById("historyRefresh").onclick = function () {
    refreshHistory().catch(reportHistoryError);
  };

  document.getElementById("exportBtn").onclick = async function () {
    buildPrintSheet();
    if (apiState.simulation) {
      try {
        await api("/api/simulations/" + apiState.simulation.id + "/exports", {
          method: "POST",
          body: JSON.stringify({ format: "print" }),
        });
      } catch (error) {
        reportConnectionError(error);
        return;
      }
    }
    setTimeout(function () { window.print(); }, 60);
  };

  document.addEventListener("fullscreenchange", function () {
    if (geoMap) setTimeout(function () { geoMap.invalidateSize(); }, 120);
  });

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) {
      stopGeoVehicles();
      transitResumeAfterVisibility = transitRunning;
      pauseTransit(false);
    } else if (dispatched) {
      startGeoVehicles();
    }
    if (!document.hidden && transitResumeAfterVisibility) {
      transitResumeAfterVisibility = false;
      startTransit();
    }
  });

  async function checkHealth() {
    try {
      const health = await api("/api/health");
      setServiceState(true, "服务正常 v" + health.version);
    } catch (error) {
      setServiceState(false, navigator.onLine ? "服务异常" : "网络离线");
    }
  }

  async function initialize() {
    try {
      const results = await Promise.all([
        api("/api/health"),
        api("/api/config"),
      ]);
      apiState.config = results[1];
      document.getElementById("kpiSpots").textContent = apiState.config.spots.length + " 个";
      setServiceState(true, "服务正常 v" + results[0].version);
      initGeoMap(apiState.config);
      const dataResults = await Promise.allSettled([
        refreshSnapshot(),
        refreshForecast(),
        refreshHistory(),
        refreshTransitRoutes(),
      ]);
      if (dataResults[0].status === "rejected") reportConnectionError(dataResults[0].reason);
      if (dataResults[1].status === "rejected") reportConnectionError(dataResults[1].reason);
      if (dataResults[2].status === "rejected") reportHistoryError(dataResults[2].reason);
      if (dataResults[3].status === "rejected") {
        transitControl.hidden = !geoMap;
        transitStatus.textContent = "真实公交线路加载失败：" + dataResults[3].reason.message;
      }
      healthTimer = setInterval(checkHealth, 30000);
    } catch (error) {
      reportConnectionError(error);
    }
  }

  window.addEventListener("online", checkHealth);
  window.addEventListener("offline", function () { setServiceState(false, "网络离线"); });
  window.addEventListener("beforeunload", function () {
    clearWorkflowTimers();
    stopGeoVehicles();
    pauseTransit(false);
    clearTimeout(tileFallbackTimer);
    if (healthTimer) clearInterval(healthTimer);
  });

  initialize();
})();
