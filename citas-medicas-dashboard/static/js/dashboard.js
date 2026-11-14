/**
 * dashboard.js
 * Consume la API REST del backend Flask y renderiza el panel de control
 * de la Clínica San José: KPIs, gráficos (Chart.js) y tabla de citas.
 */

const API = {
  kpis: (dias) => `/api/kpis?dias=${dias}`,
  porEspecialidad: (dias) => `/api/citas-por-especialidad?dias=${dias}`,
  tendencia: (dias) => `/api/tendencia-citas?dias=${dias}`,
  ingresos: () => `/api/ingresos-mensuales?meses=6`,
  medicos: (dias) => `/api/medicos-mas-solicitados?dias=${dias}&limite=6`,
  citasRecientes: () => `/api/citas-recientes?limite=12`,
  inasistenciaTendencia: () => `/api/tasa-inasistencia-tendencia?meses=6`,
};

const ESTADO_LABEL = {
  completada: "Completada",
  confirmada: "Confirmada",
  pendiente: "Pendiente",
  no_asistio: "No asistió",
  cancelada: "Cancelada",
};

const fmtMoneda = (valor) =>
  `Q ${new Intl.NumberFormat("es-GT", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    .format(Number(valor) || 0)}`;

const fmtFecha = (iso) => {
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
};

const fmtFechaCorta = (iso) => {
  const dt = new Date(iso + "T00:00:00");
  return dt.toLocaleDateString("es-ES", { day: "2-digit", month: "short" });
};

function setKpiText(id, valor, formatter = (v) => v) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = formatter(valor ?? 0);
}

function renderEmptyChart(canvasId, texto = "No hay registros aún") {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#7d8ca3";
  ctx.font = "600 14px IBM Plex Sans, sans-serif";
  ctx.textAlign = "center";
  ctx.fillText(texto, canvas.width / 2, canvas.height / 2);
}

function chartDisponible(canvasId) {
  if (typeof Chart !== "undefined") return true;
  renderEmptyChart(canvasId, "Gráfico no disponible");
  return false;
}

let state = { dias: 30, calendarDate: new Date(), calendarData: [], calendarRendered: false };
let charts = {};

// ------------------------------------------------------------------
// Inicialización
// ------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  actualizarReloj();
  setInterval(actualizarReloj, 60_000);

  const prev = document.getElementById("calendar-prev");
  const next = document.getElementById("calendar-next");
  if (prev) {
    prev.addEventListener("click", () => {
      const current = new Date(state.calendarDate.getFullYear(), state.calendarDate.getMonth(), 1);
      state.calendarDate = new Date(current.getFullYear(), current.getMonth() - 1, 1);
      pintarCalendario(state.calendarData, true, "previous");
    });
  }

  if (next) {
    next.addEventListener("click", () => {
      const current = new Date(state.calendarDate.getFullYear(), state.calendarDate.getMonth(), 1);
      state.calendarDate = new Date(current.getFullYear(), current.getMonth() + 1, 1);
      pintarCalendario(state.calendarData, true, "next");
    });
  }

  document.querySelectorAll(".period-btn[data-dias]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".period-btn[data-dias]").forEach((b) => b.classList.remove("is-active"));
      btn.classList.add("is-active");
      state.dias = parseInt(btn.dataset.dias, 10);
      const pdf = document.getElementById("btn-export-pdf");
      const csv = document.getElementById("btn-export-csv");
      if (pdf) pdf.href = `/api/reportes/exportar.pdf?dias=${state.dias}`;
      if (csv) csv.href = `/api/reportes/exportar.csv?dias=${state.dias}`;
      cargarTodo();
    });
  });

  cargarTodo();
});

function actualizarReloj() {
  const ahora = new Date();
  const texto = ahora.toLocaleDateString("es-ES", {
    weekday: "long", day: "2-digit", month: "long", year: "numeric",
  }) + " · " + ahora.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
  document.getElementById("fecha-actual").textContent = texto;
}

async function cargarTodo() {
  const { dias } = state;
  try {
    const [kpis, porEspecialidad, tendencia, ingresos, medicos, recientes, inasistencia] =
      await Promise.all([
        fetchJSON(API.kpis(dias)),
        fetchJSON(API.porEspecialidad(dias)),
        fetchJSON(API.tendencia(dias)),
        fetchJSON(API.ingresos()),
        fetchJSON(API.medicos(dias)),
        fetchJSON(API.citasRecientes()),
        fetchJSON(API.inasistenciaTendencia()),
      ]);

    pintarKPIs(kpis);
    pintarTendencia(tendencia);
    pintarEspecialidad(porEspecialidad);
    pintarTorta(porEspecialidad);
    pintarIngresos(ingresos);
    pintarRanking(medicos);
    state.calendarData = Array.isArray(recientes) ? recientes : [];
    pintarCalendario(state.calendarData);
    pintarTabla(recientes);
    pintarInasistencia(inasistencia);
    pintarAgendaHoy();
  } catch (err) {
    console.error("Error cargando el dashboard:", err);
  }
}

async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Fallo en ${url}: ${res.status}`);
  return res.json();
}

// ------------------------------------------------------------------
// KPIs
// ------------------------------------------------------------------

function pintarKPIs(k) {
  setKpiText("kpi-citas-hoy", k.citas_hoy);
  setKpiText("kpi-citas-pendientes", k.citas_pendientes);
  document.getElementById("kpi-tasa-inasistencia").innerHTML = `${k.tasa_inasistencia ?? 0}<small>%</small>`;
  setKpiText("kpi-ingresos", k.ingresos_periodo, fmtMoneda);
  setKpiText("kpi-medicos", k.medicos_activos);
  setKpiText("kpi-pacientes", k.pacientes_totales);
}

// ------------------------------------------------------------------
// Gráfico: tendencia de citas (líneas apiladas por estado)
// ------------------------------------------------------------------

function pintarTendencia(data) {
  const ctx = document.getElementById("chart-tendencia");
  if (!data || data.length === 0) {
    if (charts.tendencia) charts.tendencia.destroy();
    renderEmptyChart("chart-tendencia", "No hay datos de citas");
    return;
  }
  if (!chartDisponible("chart-tendencia")) return;

  const labels = data.map((d) => fmtFechaCorta(d.fecha));
  if (charts.tendencia) charts.tendencia.destroy();

  charts.tendencia = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Completadas",
          data: data.map((d) => d.completadas),
          borderColor: "#0879ED",
          backgroundColor: "rgba(15,107,92,0.08)",
          fill: true,
          tension: 0.3,
          pointRadius: 0,
          borderWidth: 2,
        },
        {
          label: "No asistió",
          data: data.map((d) => d.no_asistio),
          borderColor: "#B8433C",
          backgroundColor: "rgba(184,67,60,0.06)",
          fill: true,
          tension: 0.3,
          pointRadius: 0,
          borderWidth: 1.6,
        },
        {
          label: "Canceladas",
          data: data.map((d) => d.canceladas),
          borderColor: "#8A94A3",
          backgroundColor: "rgba(138,148,163,0.05)",
          fill: true,
          tension: 0.3,
          pointRadius: 0,
          borderWidth: 1.6,
          borderDash: [4, 3],
        },
      ],
    },
    options: baseOptions({ legend: true }),
  });
}

// ------------------------------------------------------------------
// Gráfico: citas por especialidad (barras horizontales)
// ------------------------------------------------------------------

function pintarEspecialidad(data) {
  const ctx = document.getElementById("chart-especialidad");
  if (!data || data.length === 0 || data.every((item) => Number(item.total) === 0)) {
    if (charts.especialidad) charts.especialidad.destroy();
    renderEmptyChart("chart-especialidad", "Sin citas en el periodo");
    return;
  }

  if (!chartDisponible("chart-especialidad")) return;
  if (charts.especialidad) charts.especialidad.destroy();

  charts.especialidad = new Chart(ctx, {
    type: "bar",
    data: {
      labels: data.map((d) => d.nombre),
      datasets: [{
        data: data.map((d) => d.total),
        backgroundColor: data.map((d) => d.color),
        borderRadius: 3,
        maxBarThickness: 22,
      }],
    },
    options: {
      ...baseOptions({ legend: false }),
      indexAxis: "y",
    },
  });
}

// ------------------------------------------------------------------
// Gráfico: ingresos mensuales
// ------------------------------------------------------------------

function pintarIngresos(data) {
  const ctx = document.getElementById("chart-ingresos");
  if (!data || data.length === 0) {
    if (charts.ingresos) charts.ingresos.destroy();
    renderEmptyChart("chart-ingresos", "Sin ingresos registrados");
    return;
  }

  if (!chartDisponible("chart-ingresos")) return;
  if (charts.ingresos) charts.ingresos.destroy();

  charts.ingresos = new Chart(ctx, {
    type: "bar",
    data: {
      labels: data.map((d) => nombreMes(d.mes)),
      datasets: [{
        data: data.map((d) => d.total),
        backgroundColor: "#A9820F",
        borderRadius: 3,
        maxBarThickness: 34,
      }],
    },
    options: {
      ...baseOptions({ legend: false }),
      plugins: {
        ...baseOptions({ legend: false }).plugins,
        tooltip: { callbacks: { label: (c) => fmtMoneda(c.raw) } },
      },
      scales: {
        ...baseOptions({ legend: false }).scales,
        y: { ...baseOptions({ legend: false }).scales.y,
             ticks: { callback: (v) => fmtMoneda(v), font: { family: "IBM Plex Mono", size: 10 } } },
      },
    },
  });
}

// ------------------------------------------------------------------
// Gráfico: tendencia de inasistencia
// ------------------------------------------------------------------

function pintarInasistencia(data) {
  const ctx = document.getElementById("chart-inasistencia");
  if (!data || data.length === 0) {
    if (charts.inasistencia) charts.inasistencia.destroy();
    renderEmptyChart("chart-inasistencia", "Sin historial de inasistencia");
    return;
  }

  if (!chartDisponible("chart-inasistencia")) return;
  if (charts.inasistencia) charts.inasistencia.destroy();

  charts.inasistencia = new Chart(ctx, {
    type: "line",
    data: {
      labels: data.map((d) => nombreMes(d.mes)),
      datasets: [{
        data: data.map((d) => d.tasa_inasistencia),
        borderColor: "#B8433C",
        backgroundColor: "rgba(184,67,60,0.10)",
        fill: true,
        tension: 0.35,
        pointBackgroundColor: "#B8433C",
        pointRadius: 3,
        borderWidth: 2,
      }],
    },
    options: {
      ...baseOptions({ legend: false }),
      plugins: {
        ...baseOptions({ legend: false }).plugins,
        tooltip: { callbacks: { label: (c) => `${c.raw}% de inasistencia` } },
      },
    },
  });
}

// ------------------------------------------------------------------
// Ranking de médicos (lista con barras)
// ------------------------------------------------------------------

function pintarTorta(data) {
  const ctx = document.getElementById("chart-torta");
  if (!ctx) return;
  if (!data || data.length === 0 || data.every((item) => Number(item.total) === 0)) {
    if (charts.torta) charts.torta.destroy();
    renderEmptyChart("chart-torta", "Sin citas en el periodo");
    return;
  }
  if (!chartDisponible("chart-torta")) return;
  if (charts.torta) charts.torta.destroy();
  charts.torta = new Chart(ctx, {
    type: "pie",
    data: {
      labels: data.map((d) => d.nombre),
      datasets: [{ data: data.map((d) => d.total), backgroundColor: data.map((d) => d.color) }],
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "bottom" } } },
  });
}

async function pintarAgendaHoy() {
  const cont = document.getElementById("agenda-hoy");
  if (!cont) return;
  try {
    const data = await fetchJSON("/api/agenda-hoy");
    if (!data.length) {
      cont.innerHTML = "<p class=\"tabla-vacia\">No hay citas hoy.</p>";
      return;
    }
    cont.innerHTML = data.map((c) => `
      <div class="upcoming-item">
        <div class="user-badge">${(c.medico || "M")[0]}</div>
        <div class="upcoming-item__details">
          <strong>${c.paciente}</strong>
          <span>${c.medico} · ${c.especialidad}</span>
        </div>
        <div class="upcoming-item__time">${c.hora}</div>
        <span class="pill">${c.estado}</span>
      </div>
    `).join("");
  } catch (e) {
    cont.innerHTML = "<p class=\"tabla-vacia\">No se pudo cargar la agenda.</p>";
  }
}

function pintarRanking(data) {
  const cont = document.getElementById("ranking-medicos");
  cont.innerHTML = "";

  if (!data || data.length === 0) {
    cont.innerHTML = "<li class=\"ranking-item\">Sin citas de médicos en este periodo.</li>";
    return;
  }

  const max = Math.max(...data.map((d) => d.total_citas), 1);

  data.forEach((m) => {
    const pct = Math.round((m.total_citas / max) * 100);
    const li = document.createElement("li");
    li.className = "ranking-item";
    li.innerHTML = `
      <div class="ranking-item__top">
        <div>
          <div class="ranking-item__name">${m.medico}</div>
          <div class="ranking-item__specialty">${m.especialidad}</div>
        </div>
        <span class="ranking-item__count">${m.total_citas} citas${m.inasistencias ? ` · ${m.inasistencias} ausencias` : ""}</span>
      </div>
      <div class="ranking-item__bar-track">
        <div class="ranking-item__bar-fill" style="width:${pct}%; background:${m.color}"></div>
      </div>
    `;
    cont.appendChild(li);
  });
}

// ------------------------------------------------------------------
// Tabla de citas recientes
// ------------------------------------------------------------------

function pintarCalendario(citas, animar = false, direccion = "next") {
  const grid = document.getElementById("calendar-grid");
  const monthLabel = document.getElementById("calendar-month-label");
  if (!grid || !monthLabel) return;

  const iniciarAnimacion = animar || !state.calendarRendered;
  grid.classList.remove("is-animating", "is-animating-next", "is-animating-previous");
  if (iniciarAnimacion) {
    void grid.offsetWidth;
    grid.classList.add("is-animating", `is-animating-${direccion}`);
    window.setTimeout(() => grid.classList.remove("is-animating", "is-animating-next", "is-animating-previous"), 700);
  }

  const month = new Date(state.calendarDate.getFullYear(), state.calendarDate.getMonth(), 1);
  const today = new Date();
  const todayIso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

  monthLabel.textContent = month.toLocaleDateString("es-GT", { month: "long", year: "numeric" });
  monthLabel.classList.remove("is-changing");
  if (iniciarAnimacion) {
    void monthLabel.offsetWidth;
    monthLabel.classList.add("is-changing");
  }

  const header = ["L", "M", "M", "J", "V", "S", "D"];
  const cells = header.map((name) => `<span class="calendar-week">${name}</span>`).join("");

  const firstDay = new Date(month.getFullYear(), month.getMonth(), 1);
  const startDay = (firstDay.getDay() + 6) % 7;
  const startGrid = new Date(firstDay);
  startGrid.setDate(firstDay.getDate() - startDay);

  const citasPorFecha = new Map();
  (citas || []).forEach((cita) => {
    const key = String(cita.fecha || "").slice(0, 10);
    if (!key) return;
    if (!citasPorFecha.has(key)) citasPorFecha.set(key, []);
    citasPorFecha.get(key).push(cita);
  });

  const parts = [];
  for (let i = 0; i < 42; i += 1) {
    const cellDate = new Date(startGrid);
    cellDate.setDate(startGrid.getDate() + i);
    const dateIso = `${cellDate.getFullYear()}-${String(cellDate.getMonth() + 1).padStart(2, "0")}-${String(cellDate.getDate()).padStart(2, "0")}`;
    const sameMonth = cellDate.getMonth() === month.getMonth();
    const cellEvents = citasPorFecha.get(dateIso) || [];
    const classes = ["calendar-day"];
    const estados = new Set(cellEvents.map((c) => String(c.estado || "confirmada").toLowerCase()));

    classes.push(`day-tone-${cellDate.getDay()}`);
    if (!sameMonth) classes.push("is-muted");
    if (dateIso === todayIso) classes.push("is-today");
    if (cellEvents.length) classes.push("has-cita");
    estados.forEach((estado) => classes.push(`has-${estado}`));
    if (estados.size > 1) classes.push("has-multiple");

    const dots = cellEvents.slice(0, 3).map((c) => `<i class="calendar-event-dot ${String(c.estado || "confirmada").toLowerCase()}"></i>`).join("");
    const detalle = cellEvents.map((c) => `${c.hora} ${c.paciente} (${ESTADO_LABEL[c.estado] || c.estado})`).join(", ");

    parts.push(
      `<span class="${classes.join(" ")}" style="--calendar-index:${i}" title="${cellEvents.length ? `${cellEvents.length} citas: ${detalle}` : "Sin citas"}" aria-label="${dateIso}, ${cellEvents.length} citas">
        <span class="calendar-date">${cellDate.getDate()}</span>
        <span class="calendar-event-dots">${dots}</span>
      </span>`
    );
  }

  grid.innerHTML = `${cells}${parts.join("")}`;
  state.calendarRendered = true;
}

function pintarTabla(data) {
  const cuerpo = document.getElementById("tabla-citas");
  if (!data.length) {
    cuerpo.innerHTML = `<tr><td colspan="6" class="tabla-vacia">No hay citas registradas.</td></tr>`;
    return;
  }
  cuerpo.innerHTML = data.map((c) => `
    <tr>
      <td>${c.paciente}</td>
      <td>${c.medico}</td>
      <td><span class="specialty-tag"><i style="background:${c.color}"></i>${c.especialidad}</span></td>
      <td>${fmtFecha(c.fecha)}</td>
      <td>${c.hora}</td>
      <td><span class="badge badge--${c.estado}">${ESTADO_LABEL[c.estado] || c.estado}</span></td>
    </tr>
  `).join("");
}

// ------------------------------------------------------------------
// Utilidades de gráficos
// ------------------------------------------------------------------

function nombreMes(aaaa_mm) {
  const [y, m] = aaaa_mm.split("-");
  const dt = new Date(parseInt(y), parseInt(m) - 1, 1);
  return dt.toLocaleDateString("es-ES", { month: "short", year: "2-digit" });
}

function baseOptions({ legend }) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { intersect: false, mode: "index" },
    plugins: {
      legend: {
        display: legend,
        position: "top",
        align: "end",
        labels: {
          usePointStyle: true,
          pointStyle: "rectRounded",
          font: { family: "IBM Plex Sans", size: 11.5 },
          color: "#4B5768",
          boxWidth: 10,
          padding: 14,
        },
      },
      tooltip: {
        backgroundColor: "#14213D",
        titleFont: { family: "IBM Plex Mono", size: 11 },
        bodyFont: { family: "IBM Plex Sans", size: 12 },
        padding: 10,
        cornerRadius: 3,
        displayColors: false,
      },
    },
    scales: {
      x: {
        grid: { display: false },
        ticks: { font: { family: "IBM Plex Mono", size: 10.5 }, color: "#8A94A3" },
      },
      y: {
        grid: { color: "#E7EAE7" },
        border: { display: false },
        ticks: { font: { family: "IBM Plex Mono", size: 10.5 }, color: "#8A94A3" },
        beginAtZero: true,
      },
    },
  };
}
