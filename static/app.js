// Global chart instances and phase tracking data
let weightChartInstance = null;
let volumeChartInstance = null;
let overloadByPhaseData = [];

// Helper function to format numbers with specified decimal places
function fmtNum(n, decimals = 0) {
  if (n === null || n === undefined) return '-';
  return Number(n).toLocaleString('en-US', { maximumFractionDigits: decimals, minimumFractionDigits: decimals });
}

// Maps badge status types to their respective CSS classes
function badgeClass(badge) {
  return { up: 'badge-up', down: 'badge-down', hold: 'badge-hold', neutral: 'badge-neutral' }[badge] || 'badge-neutral';
}

// Maps badge status types to their respective visual arrow/icon symbols
function badgeIcon(badge) {
  return { up: '↑', down: '↓', hold: '→', neutral: '·' }[badge] || '';
}

// Asynchronous main function to fetch dashboard data from the API and trigger all rendering functions
async function loadDashboard() {
  let data;
  try {
    const res = await fetch('/api/data');
    data = await res.json();
    if (data.error) throw new Error(data.error);
  } catch (err) {
    console.error('Failed to load dashboard data:', err);
    return;
  }

  // Render KPIs, banners, tables, calendars, and trend charts using fetched data
  renderKpis(data);
  renderPhaseBanner(data.cycle);
  overloadByPhaseData = data.overload_by_phase || [];
  const activePhaseName = data.cycle && data.cycle.available ? data.cycle.phase : null;
  const activeEntry = overloadByPhaseData.find(p => p.phase === activePhaseName) || overloadByPhaseData[0];
  if (activeEntry) {
    renderOverloadTable(activeEntry.suggestions, `No sessions logged during the ${activeEntry.phase} phase yet.`);
  } else {
    renderOverloadTable(data.overload_suggestions);
  }
  renderPhaseTabs(overloadByPhaseData, data.cycle);
  renderPrTable(data.pr_tracker);
  renderSchedule(data.weekly_schedule);
  renderCalendar(data.calendar_month);
  renderProgressOverview(data);
  renderProgressSummary(data);
  renderWeightChart(data.weight_trend);
  renderVolumeChart(data.volume_trend);
}

// Renders key performance indicator cards (weight, delta, workouts, volume, PRs, and cycle status)
function renderKpis(data) {
  const k = data.kpis;
  const cycle = data.cycle;

  // Display current body weight in lbs
  document.getElementById('kpi-weight').innerHTML =
    (k.current_weight ?? '-') + ' <span style="font-size:0.8rem;">lbs</span>';

  // Display weight change delta compared to the first log entry with appropriate color
  const deltaEl = document.getElementById('kpi-weight-delta');
  if (k.weight_delta === null || k.weight_delta === undefined) {
    deltaEl.textContent = 'No previous entry yet';
    deltaEl.style.color = 'var(--text-muted)';
  } else {
    const arrow = k.weight_delta <= 0 ? '↓' : '↑';
    deltaEl.textContent = `${arrow} ${Math.abs(k.weight_delta)} lbs vs first log`;
    deltaEl.style.color = k.weight_delta <= 0 ? 'var(--green-text)' : 'var(--red-text)';
  }

  // Display workout counts, total volume, and monthly PR achievements
  document.getElementById('kpi-workouts').textContent = fmtNum(k.total_workouts);
  document.getElementById('kpi-volume').innerHTML = fmtNum(k.total_volume, 1) + ' <span style="font-size:0.8rem;">lbs</span>';
  document.getElementById('kpi-prs-month').textContent = fmtNum(k.prs_this_month);

  // Display current cycle phase details or fallback message if unavailable
  if (cycle && cycle.available) {
    document.getElementById('kpi-phase').textContent = cycle.goal || cycle.phase;
    document.getElementById('kpi-phase-day').textContent = `Day ${cycle.cycle_day} of ${cycle.cycle_length}`;
  } else {
    document.getElementById('kpi-phase').textContent = 'Not set';
    document.getElementById('kpi-phase-day').textContent = cycle?.message || '';
  }
}

// Updates the top phase banner with target metrics and training notes for the current cycle phase
function renderPhaseBanner(cycle) {
  const nameEl = document.getElementById('phaseBannerName');
  const repsEl = document.getElementById('phaseBannerReps');
  const notesEl = document.getElementById('phaseBannerNotes');

  // Handle case where cycle data is missing or unavailable
  if (!cycle || !cycle.available) {
    nameEl.textContent = 'Cycle phase not available';
    repsEl.textContent = '-';
    notesEl.textContent = cycle?.message || 'Log a start date in the Cycle Settings sheet.';
    return;
  }

  // Populate banner with active phase goal, repetition targets, and notes
  nameEl.textContent = `${cycle.goal || cycle.phase}`;
  repsEl.textContent = `${cycle.rep_target_min}-${cycle.rep_target_max} reps`;
  notesEl.textContent = cycle.notes || '-';
}

// Dynamically creates and renders navigation tabs for each training cycle phase
function renderPhaseTabs(byPhase, activeCycle) {
  const container = document.getElementById('phaseTabs');
  if (!container) return;

  if (!byPhase || byPhase.length === 0) {
    container.innerHTML = '';
    return;
  }

  const activePhaseName = activeCycle && activeCycle.available ? activeCycle.phase : null;

  // Map phase objects into HTML button elements
  container.innerHTML = byPhase.map((p, i) => {
    const isActive = p.phase === activePhaseName || (!activePhaseName && i === 0);
    return `<button type="button" class="phase-tab${isActive ? ' active' : ''}" data-phase="${p.phase}">${p.goal || p.phase}</button>`;
  }).join('');

  // Attach click event listeners to handle tab switching interactivity
  container.querySelectorAll('.phase-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      // 1. Visually toggle active class across tabs
      container.querySelectorAll('.phase-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      // 2. Find data corresponding to the clicked phase
      const entry = overloadByPhaseData.find(p => p.phase === btn.dataset.phase);
      
      if (entry) {
        // 3. Refresh overload suggestion table for the selected phase
        renderOverloadTable(entry.suggestions, `No sessions logged during the ${entry.phase} phase yet.`);
        
        // 4. Update the Phase Banner dynamically with new phase attributes
        renderPhaseBanner({
          available: true,
          goal: entry.goal || entry.phase,
          phase: entry.phase,
          rep_target_min: entry.rep_target_min,
          rep_target_max: entry.rep_target_max,
          notes: entry.notes
        });
      }
    });
  });
}

// Renders the progressive overload suggestion table rows
function renderOverloadTable(rows, emptyMessage) {
  const tbody = document.getElementById('overloadTableBody');
  if (!rows || rows.length === 0) {
    const msg = emptyMessage || 'No workouts logged yet.';
    tbody.innerHTML = `<tr><td colspan="5" style="color:var(--text-muted);">${msg}</td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map(r => {
    const weightLabel = r.is_bodyweight ? 'Bodyweight' : `${fmtNum(r.weight, 1)} lbs`;
    const repsLabel = r.last_reps.join('-');
    return `
      <tr>
        <td>${r.exercise}</td>
        <td>${r.category || '-'}</td>
        <td>${weightLabel} &middot; ${repsLabel}</td>
        <td>${r.min_reps ?? '-'} reps</td>
        <td class="${badgeClass(r.badge)}">${badgeIcon(r.badge)} ${r.suggestion}</td>
      </tr>`;
  }).join('');
}

// Renders personal records (PRs) tracker table rows
function renderPrTable(rows) {
  const tbody = document.getElementById('prTableBody');
  if (!rows || rows.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" style="color:var(--text-muted);">No workouts logged yet.</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map(r => {
    const bestLabel = r.is_bodyweight
      ? `Bodyweight &middot; ${fmtNum(r.best_reps)} reps`
      : `${fmtNum(r.best_weight, 1)} lbs &middot; ${fmtNum(r.best_reps)} reps`;
    const vsPr = r.vs_last_pr || '-';
    let vsClass = 'badge-neutral';
    if (vsPr.includes('↑')) vsClass = 'badge-up';
    else if (vsPr.includes('↓')) vsClass = 'badge-down';

    return `
      <tr>
        <td>${r.exercise}</td>
        <td>${r.category || '-'}</td>
        <td>${bestLabel}</td>
        <td>${r.date}</td>
        <td class="${vsClass}">${vsPr}</td>
      </tr>`;
  }).join('');
}

// Renders the weekly training schedule table
function renderSchedule(schedule) {
  const tbody = document.getElementById('scheduleTableBody');
  if (!schedule || schedule.length === 0) {
    tbody.innerHTML = '<tr><td colspan="2" style="color:var(--text-muted);">No schedule set.</td></tr>';
    return;
  }
  tbody.innerHTML = schedule.map(s => `<tr><td>${s.day}</td><td>${s.activity || '-'}</td></tr>`).join('');
}

// Renders the monthly training calendar view
function renderCalendar(cal) {
  const label = document.getElementById('calendarMonthLabel');
  const container = document.getElementById('calendarMonth');
  container.querySelectorAll('.calendar-day, .calendar-day-empty').forEach(el => el.remove());

  if (!cal) return;
  if (label) label.textContent = cal.month_label || '';

  const trainedSet = new Set(cal.trained_days || []);

  // Insert empty slots to align days of the week correctly
  for (let i = 0; i < cal.first_weekday; i++) {
    const empty = document.createElement('div');
    empty.className = 'calendar-day-empty';
    container.appendChild(empty);
  }

  // Generate calendar cells for each day of the month
  for (let d = 1; d <= cal.num_days; d++) {
    const cell = document.createElement('div');
    let cls = 'calendar-day';
    if (trainedSet.has(d)) cls += ' trained';
    if (d === cal.today_day) cls += ' today';
    cell.className = cls;
    cell.textContent = d;
    cell.title = trainedSet.has(d) ? `${cal.month_label} ${d}: workout logged` : `${cal.month_label} ${d}: rest day`;
    container.appendChild(cell);
  }
}

// Computes and renders high-level progress metrics (strength, consistency, recovery, target)
function renderProgressOverview(data) {
  const suggestions = data.overload_suggestions || [];
  let strength = 0;
  if (suggestions.length > 0) {
    const good = suggestions.filter(s => s.badge === 'up' || s.badge === 'hold').length;
    strength = Math.round((good / suggestions.length) * 100);
  }

  const trainingDates = data.training_dates || [];
  let consistency = 0;
  if (trainingDates.length > 0) {
    const first = new Date(trainingDates[0]);
    const today = new Date();
    const daysSince = Math.max(1, Math.round((today - first) / 86400000) + 1);
    consistency = Math.min(100, Math.round((trainingDates.length / daysSince) * 100));
  }

  // Compute recovery score based on consecutive days trained backwards from today
  let recovery = 100;
  if (trainingDates.length > 0) {
    const sortedDates = [...new Set(trainingDates)].sort().reverse();
    
    let consecutiveDays = 0;
    let curr = new Date();
    curr.setHours(0, 0, 0, 0);

    let checkDate = new Date(curr);
    
    while (true) {
      const year = checkDate.getFullYear();
      const month = String(checkDate.getMonth() + 1).padStart(2, '0');
      const day = String(checkDate.getDate()).padStart(2, '0');
      const dateStr = `${year}-${month}-${day}`;

      if (sortedDates.includes(dateStr)) {
        consecutiveDays++;
        checkDate.setDate(checkDate.getDate() - 1);
      } else {
        if (consecutiveDays === 0) {
          checkDate.setDate(checkDate.getDate() - 1);
          const yesterdayStr = `${checkDate.getFullYear()}-${String(checkDate.getMonth() + 1).padStart(2, '0')}-${String(checkDate.getDate()).padStart(2, '0')}`;
          if (sortedDates.includes(yesterdayStr)) {
            consecutiveDays++;
            checkDate.setDate(checkDate.getDate() - 1);
            continue;
          }
        }
        break;
      }
    }

    if (consecutiveDays > 1) {
      recovery = Math.max(0, 100 - ((consecutiveDays - 1) * 20));
    }
  }

  let targetText = 'Hypertrophy & Strength';
  if (data.cycle && data.cycle.available && data.cycle.goal) {
    targetText = data.cycle.goal;
  }

  // Render progress rings into DOM container
  const container = document.getElementById('progressCircles');
  container.innerHTML = `
    <div class="circle-item">
      <div class="progress-ring" style="background: conic-gradient(var(--accent-blue) ${strength}%, #e2e8f0 ${strength}% 100%);">
        <div class="progress-ring-inner">${strength}%</div>
      </div>
      <div class="circle-label">Strength</div>
    </div>
    <div class="circle-item">
      <div class="progress-ring" style="background: conic-gradient(var(--accent-blue) ${consistency}%, #e2e8f0 ${consistency}% 100%);">
        <div class="progress-ring-inner">${consistency}%</div>
      </div>
      <div class="circle-label">Consistency</div>
    </div>
    <div class="circle-item">
      <div class="progress-ring" style="background: conic-gradient(var(--accent-blue) ${recovery}%, #e2e8f0 ${recovery}% 100%);">
        <div class="progress-ring-inner">${recovery}%</div>
      </div>
      <div class="circle-label">Recovery</div>
    </div>
    <div class="circle-item">
      <div class="progress-ring circle-target">
        <div class="progress-ring-inner circle-target-inner">${targetText}</div>
      </div>
      <div class="circle-label">Target</div>
    </div>
  `;
}

// Renders summary rows detailing workout and weight metrics
function renderProgressSummary(data) {
  const k = data.kpis;
  const tbody = document.getElementById('progressSummaryBody');

  const weightRow = k.weight_delta === null || k.weight_delta === undefined
    ? ['Body Weight', 'No comparison yet', 'pill-blue', 'Log more entries']
    : [
        'Body Weight',
        `${k.weight_delta <= 0 ? '↓' : '↑'} ${Math.abs(k.weight_delta)} lbs`,
        'pill-green',
        'On Track',
      ];

  const rows = [
    weightRow,
    ['Workouts Logged', fmtNum(k.total_workouts), 'pill-green', 'Keep going'],
    ['Total Volume', `${fmtNum(k.total_volume, 1)} lbs`, 'pill-green', 'Tracked'],
    ['Exercises Tracked', fmtNum((data.pr_tracker || []).length), 'pill-blue', 'In log'],
  ];

  tbody.innerHTML = rows.map(([label, val, pillClass, pillText]) => `
    <tr>
      <td>${label}</td>
      <td>${val}</td>
      <td><span class="pill ${pillClass}">${pillText}</span></td>
    </tr>`).join('');
}

// Renders the body weight trend line chart using Chart.js
function renderWeightChart(trend) {
  const ctx = document.getElementById('weightChart').getContext('2d');
  const labels = (trend || []).map(t => t.date);
  const values = (trend || []).map(t => t.weight);

  if (weightChartInstance) weightChartInstance.destroy();
  weightChartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        data: values,
        borderColor: '#3b82f6',
        backgroundColor: 'rgba(59, 130, 246, 0.1)',
        fill: true,
        tension: 0.3,
        pointRadius: 3
      }]
    },
    options: {
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false } },
        y: { beginAtZero: false }
      }
    }
  });
}

// Renders the weekly training volume bar chart using Chart.js
function renderVolumeChart(trend) {
  const ctx = document.getElementById('volumeChart').getContext('2d');
  const recentTrend = (trend || []).slice(-10);
  const labels = recentTrend.map(t => t.date);
  const values = recentTrend.map(t => t.volume);

  if (volumeChartInstance) volumeChartInstance.destroy();
  volumeChartInstance = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: '#3b82f6',
        borderRadius: 4
      }]
    },
    options: {
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false } },
        y: { display: false }
      }
    }
  });
}

// Trigger dashboard initialization once the DOM is fully loaded
document.addEventListener('DOMContentLoaded', loadDashboard);