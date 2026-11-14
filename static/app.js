/* ═══════════════════════════════════════════════════════
   DiraBot — Premium Frontend JS
   WebSocket, REST, Multiple Profiles, Deletion
   ═══════════════════════════════════════════════════════ */

const WS_URL = `ws://${location.host}/ws`;
const API    = '/api';

let ws = null;
let reconnectTimer = null;
let currentProfiles = [];

// ── Boot ─────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  connectWS();
  setInterval(loadStats, 30_000);
});

// ── WebSocket ────────────────────────────────────
function connectWS() {
  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    setStatus(true);
    addLog('🔗 מחובר לשרת', 'success');
    clearTimeout(reconnectTimer);
  };

  ws.onclose = () => {
    setStatus(false);
    addLog('⚠️ חיבור נסגר, מנסה שוב...', 'warn');
    reconnectTimer = setTimeout(connectWS, 3000);
  };

  ws.onerror = () => {
    addLog('❌ שגיאת חיבור', 'error');
  };

  ws.onmessage = (e) => {
    const { event, data } = JSON.parse(e.data);
    handleEvent(event, data);
  };
}

function handleEvent(event, data) {
  switch (event) {
    case 'connected':
      updateStats(data.stats);
      loadListings();
      loadTopListings();
      loadProfiles();
      if(data.config && data.config.sources) {
        if(document.getElementById('srcYad2')) document.getElementById('srcYad2').checked = !!data.config.sources.yad2;
        if(document.getElementById('srcMadlan')) document.getElementById('srcMadlan').checked = !!data.config.sources.madlan;
        if(document.getElementById('srcHomeless')) document.getElementById('srcHomeless').checked = !!data.config.sources.homeless;
        if(document.getElementById('srcKomo')) document.getElementById('srcKomo').checked = !!data.config.sources.komo;
      }
      break;

    case 'scan_started':
      const btn = document.getElementById('scanBtn');
      btn.classList.add('scanning');
      document.getElementById('scanLabel').textContent = 'סורק...';
      break;

    case 'scan_done':
      const btnDone = document.getElementById('scanBtn');
      btnDone.classList.remove('scanning');
      document.getElementById('scanLabel').textContent = 'סרוק דירות חדשות';
      updateStats(data.stats);
      loadListings();
      loadTopListings();
      if (data.new > 0) {
        showToast(`🎉 נמצאו ${data.new} דירות חדשות!`, 'success');
      } else {
        showToast('🔍 סריקה הסתיימה — אין חדש', 'info');
      }
      break;

    case 'new_listing':
      showToast(`🏠 דירה חדשה: ${data.city || ''} — ${data.price?.toLocaleString() || ''}₪`, 'success');
      break;

    case 'typing':
      document.getElementById('typingWrap').classList.add('show');
      scrollChat();
      break;

    case 'chat_response':
      document.getElementById('typingWrap').classList.remove('show');
      addMessage('agent', data.message);
      document.getElementById('sendBtn').disabled = false;
      break;

    case 'log':
      addLog(data.msg, data.level || 'info');
      break;
  }
}

// ── Stats & Status ───────────────────────────────
function setStatus(connected) {
  const pill = document.getElementById('connPill');
  const lbl  = pill.querySelector('.conn-label');
  if (connected) {
    pill.classList.remove('offline');
    lbl.textContent = 'מחובר';
  } else {
    pill.classList.add('offline');
    lbl.textContent = 'מנותק';
  }
}

async function loadStats() {
  try {
    const stats = await fetch(`${API}/stats`).then(r => r.json());
    updateStats(stats);
  } catch {}
}

function updateStats(stats) {
  if (!stats) return;
  animateNum('statToday',    stats.today    ?? 0);
  animateNum('statNotified', stats.notified ?? 0);
  animateNum('statTotal',    stats.total    ?? 0);
}

function animateNum(id, target) {
  const el = document.getElementById(id);
  const current = parseInt(el.textContent) || 0;
  const diff = target - current;
  if (diff === 0) return;
  const steps = 20;
  const step = diff / steps;
  let i = 0;
  const timer = setInterval(() => {
    i++;
    el.textContent = Math.round(current + step * i);
    if (i >= steps) { el.textContent = target; clearInterval(timer); }
  }, 20);
}

function triggerScan() {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'scan' }));
    addLog('⚡ סריקה ידנית הופעלה', 'info');
  }
}

// ── Top Listings ─────────────────────────────────
async function loadTopListings() {
  const container = document.getElementById('topList');
  try {
    const listings = await fetch(`${API}/listings/top?limit=4`).then(r => r.json());
    if (!listings.length) {
      container.innerHTML = '<div style="font-size:12px;color:var(--t-tertiary)">אין דירות עדיין</div>';
      return;
    }
    container.innerHTML = listings.map(l => `
      <a class="top-item" href="${l.url || '#'}" target="_blank">
        <div class="top-score">${l.score}</div>
        <div class="top-info">
          <div class="top-city">${l.city || '—'}</div>
          <div class="top-price">${l.price ? l.price.toLocaleString() + ' ₪' : '—'}</div>
        </div>
      </a>
    `).join('');
  } catch {}
}

// ── Listings Grid & Deletion ─────────────────────
async function loadListings() {
  const grid = document.getElementById('listingsGrid');
  const minScore = parseInt(document.getElementById('scoreSlider').value) || 0;
  grid.innerHTML = '<div class="empty-state">טוען דירות...</div>';

  try {
    const listings = await fetch(`${API}/listings?limit=50&min_score=${minScore}`).then(r => r.json());
    document.getElementById('listingsCount').textContent = `${listings.length} דירות`;
    document.getElementById('listingsBadge').textContent = listings.length || '';

    if (!listings.length) {
      grid.innerHTML = `<div class="empty-state">
        <div style="font-size:2.5rem;margin-bottom:.8rem">🔍</div>
        לא נמצאו דירות התואמות את הקריטריונים.<br>לחץ על סרוק כדי לחפש.
      </div>`;
      return;
    }
    grid.innerHTML = listings.map(l => renderCard(l)).join('');
  } catch (err) {
    grid.innerHTML = `<div class="empty-state" style="color:var(--red)">שגיאה בטעינת דירות</div>`;
  }
}

function renderCard(l) {
  const scoreClass = l.score >= 75 ? 's-high' : l.score >= 50 ? 's-mid' : 's-low';
  const sourceEmoji = l.source === 'yad2' ? '🟡' : l.source === 'madlan' ? '🔵' : l.source === 'homeless' ? '🔴' : l.source === 'komo' ? '🟢' : '⚪';

  const feats = [
    l.is_renovated && '✨ משופצת/חדשה',
    l.has_elevator && 'מעלית',
    l.has_parking  && 'חניה',
    l.has_balcony  && 'מרפסת',
    l.has_mamad    && 'ממ"ד',
  ].filter(Boolean);

  const tags = [
    l.rooms && `${l.rooms} חד'`,
    l.floor != null && `קומה ${l.floor}`,
    l.size_sqm && `${l.size_sqm} מ"ר`,
    l.profile && `📌 ${l.profile}`
  ].filter(Boolean);

  const imgHtml = l.image_url
    ? `<a class="card-img-wrap" href="${l.url || '#'}" target="_blank" title="לצפייה במודעה">
         <img class="card-img" src="${l.image_url}" alt="${l.city || 'דירה'}" loading="lazy"
              onerror="this.closest('.card-img-wrap').style.display='none'">
         <span class="card-img-badge">🔗 למודעה</span>
       </a>`
    : '';

  const liked = l.feedback === 'like';
  return `
    <div class="card ${liked ? 'liked' : ''}" id="card-${l.id}">
      ${imgHtml}
      <div class="card-top">
        <div class="card-source">${sourceEmoji} ${l.source || ''}</div>
        <div class="card-right">
          <button class="del-btn" onclick="deleteListing(${l.id})" title="מחק דירה">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
          </button>
          <div class="card-score ${scoreClass}">${l.score}/100</div>
        </div>
      </div>
      <div class="card-city">${l.city || '—'}</div>
      ${l.neighborhood ? `<div class="card-hood">${l.neighborhood}</div>` : ''}
      ${l.price ? `<div class="card-price">₪${l.price.toLocaleString()}</div>` : ''}
      
      ${tags.length ? `<div class="card-tags">${tags.map(t => `<span class="tag">${t}</span>`).join('')}</div>` : ''}
      ${feats.length ? `<div class="card-tags">${feats.map(f => `<span class="feat">${f}</span>`).join('')}</div>` : ''}
      
      ${l.description ? `<div class="card-desc">${l.description}</div>` : ''}
      ${l.url ? `<a href="${l.url}" target="_blank" class="card-link">לצפייה במודעה</a>` : ''}

      <div class="card-feedback">
        <button class="fb-btn fb-like ${liked ? 'active' : ''}" onclick="giveFeedback(${l.id}, 'like')" title="אהבתי — הצג עוד כאלה">👍 אהבתי</button>
        <button class="fb-btn fb-dislike" onclick="giveFeedback(${l.id}, 'dislike')" title="לא אהבתי — לא יופיע שוב לעולם">👎 לא אהבתי</button>
      </div>
    </div>
  `;
}

async function giveFeedback(id, verdict) {
  try {
    const res = await fetch(`${API}/listings/${id}/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ feedback: verdict })
    });
    if (!res.ok) { showToast('שגיאה בשמירת הפידבק', 'error'); return; }
    const card = document.getElementById(`card-${id}`);
    if (verdict === 'dislike') {
      // נעלמת מיד ולא תחזור לעולם
      if (card) {
        card.style.transform = 'scale(0.9)';
        card.style.opacity = '0';
        setTimeout(() => { card.remove(); loadListings(); }, 220);
      }
      showToast('👎 נחסמה — לא תופיע שוב בסריקות עתידיות', 'info');
    } else {
      if (card) {
        card.classList.add('liked');
        card.querySelector('.fb-like')?.classList.add('active');
      }
      showToast('👍 נשמר — הסוכן יתמקד בדומות', 'success');
    }
  } catch {
    showToast('שגיאה בתקשורת עם השרת', 'error');
  }
}

async function deleteListing(id) {
  try {
    const res = await fetch(`${API}/listings/${id}`, { method: 'DELETE' });
    if (res.ok) {
      const card = document.getElementById(`card-${id}`);
      if (card) {
        card.style.transform = 'scale(0.9) translateY(10px)';
        card.style.opacity = '0';
        setTimeout(() => {
          card.remove();
          loadListings(); // Refresh count
          loadStats();
        }, 200);
      }
      showToast('דירה נמחקה בהצלחה', 'info');
    }
  } catch (e) {
    showToast('שגיאה במחיקת הדירה', 'error');
  }
}

// ── Profiles ─────────────────────────────────────
async function loadProfiles() {
  try {
    currentProfiles = await fetch(`${API}/profiles`).then(r => r.json());
    renderProfiles();
  } catch (e) {
    console.error("Error loading profiles", e);
  }
}

function renderProfiles() {
  const container = document.getElementById('profilesList');
  if (!currentProfiles.length) {
    container.innerHTML = `<div class="empty-state">אין פרופילים מוגדרים. הוסף פרופיל חדש.</div>`;
    return;
  }
  
  container.innerHTML = currentProfiles.map((p, i) => `
    <div class="profile-card ${p.enabled ? 'enabled' : ''}">
      <div class="profile-header" onclick="toggleProfileExpand(${i})">
        <label class="profile-toggle-wrap" onclick="event.stopPropagation()">
          <input type="checkbox" class="toggle-check" ${p.enabled ? 'checked' : ''} onchange="toggleProfileEnable(${i}, this.checked)" />
          <span class="toggle-track"><span class="toggle-thumb"></span></span>
        </label>
        <div class="profile-name-wrap">
          <input type="text" class="profile-name-input" value="${escapeHtml(p.name)}" 
                 onclick="event.stopPropagation()" onchange="updateProfileName(${i}, this.value)" placeholder="שם פרופיל" />
        </div>
        <div class="profile-status ${p.enabled ? 'on' : 'off'}">${p.enabled ? 'פעיל' : 'כבוי'}</div>
        <button class="btn-del-profile" onclick="event.stopPropagation(); deleteProfile(${i})" title="מחק פרופיל">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>
      
      <div class="profile-body hidden" id="profile-body-${i}">
        <div class="field full">
          <label>ערים / מיקומים (מופרד בפסיק)</label>
          <input type="text" value="${(p.locations || []).join(', ')}" onchange="updateProfileArray(${i}, 'locations', this.value)" />
        </div>
        
        <div class="field">
          <label>מחיר</label>
          <div class="price-row">
            <input type="number" placeholder="מ-" value="${p.price?.min || ''}" onchange="updateProfileNested(${i}, 'price', 'min', this.value)" />
            <span class="price-sep">-</span>
            <input type="number" placeholder="עד" value="${p.price?.max || ''}" onchange="updateProfileNested(${i}, 'price', 'max', this.value)" />
          </div>
        </div>
        
        <div class="field">
          <label>חדרים</label>
          <div class="price-row">
            <input type="number" step="0.5" placeholder="מ-" value="${p.rooms?.min || ''}" onchange="updateProfileNested(${i}, 'rooms', 'min', this.value)" />
            <span class="price-sep">-</span>
            <input type="number" step="0.5" placeholder="עד" value="${p.rooms?.max || ''}" onchange="updateProfileNested(${i}, 'rooms', 'max', this.value)" />
          </div>
        </div>

        <div class="field">
          <label>קומה מינימלית</label>
          <input type="number" placeholder="0 = קרקע" value="${p.floor_min ?? ''}" onchange="updateProfileNumber(${i}, 'floor_min', this.value)" />
        </div>
        
        <div class="field full">
          <label>חובה</label>
          <div class="feats-grid">
            <label><input type="checkbox" class="feat-cb" ${p.require_elevator ? 'checked' : ''} onchange="updateProfileBool(${i}, 'require_elevator', this.checked)"><span class="feat-label">מעלית</span></label>
            <label><input type="checkbox" class="feat-cb" ${p.require_parking ? 'checked' : ''} onchange="updateProfileBool(${i}, 'require_parking', this.checked)"><span class="feat-label">חניה</span></label>
            <label><input type="checkbox" class="feat-cb" ${p.require_balcony ? 'checked' : ''} onchange="updateProfileBool(${i}, 'require_balcony', this.checked)"><span class="feat-label">מרפסת</span></label>
            <label><input type="checkbox" class="feat-cb" ${p.require_mamad ? 'checked' : ''} onchange="updateProfileBool(${i}, 'require_mamad', this.checked)"><span class="feat-label">ממ"ד</span></label>
            <label><input type="checkbox" class="feat-cb" ${p.require_renovated ? 'checked' : ''} onchange="updateProfileBool(${i}, 'require_renovated', this.checked)"><span class="feat-label">חדשה/משופצת</span></label>
          </div>
        </div>
        
        <div class="field">
          <label>מילות בונוס (+ציון)</label>
          <textarea placeholder="שמשה, משופצת..." onchange="updateProfileArray(${i}, 'bonus_keywords', this.value)">${(p.bonus_keywords || []).join(', ')}</textarea>
        </div>
        
        <div class="field">
          <label>מילים שחורות (סינון)</label>
          <textarea placeholder="מרתף, סאבלט..." onchange="updateProfileArray(${i}, 'blacklist_keywords', this.value)">${(p.blacklist_keywords || []).join(', ')}</textarea>
        </div>
        
        <button class="btn-save-profile" onclick="saveProfilesToServer()">שמור שינויים בפרופילים</button>
      </div>
    </div>
  `).join('');
}

function toggleProfileExpand(i) {
  const body = document.getElementById(`profile-body-${i}`);
  body.classList.toggle('hidden');
}

function updateProfileName(i, val) { currentProfiles[i].name = val; }
function toggleProfileEnable(i, checked) { 
  currentProfiles[i].enabled = checked; 
  renderProfiles(); // Re-render to update classes/status
  saveProfilesToServer(); // Auto-save toggle
}
function updateProfileArray(i, key, val) {
  currentProfiles[i][key] = val.split(',').map(s => s.trim()).filter(Boolean);
}
function updateProfileNested(i, key, subkey, val) {
  if (!currentProfiles[i][key]) currentProfiles[i][key] = {};
  currentProfiles[i][key][subkey] = val ? Number(val) : 0;
}
function updateProfileBool(i, key, checked) {
  currentProfiles[i][key] = checked;
}
function updateProfileNumber(i, key, val) {
  currentProfiles[i][key] = val ? Number(val) : 0;
}

function addProfile() {
  currentProfiles.unshift({
    name: "פרופיל חדש",
    enabled: true,
    locations: [],
    price: {min:0, max:99999},
    rooms: {min:1, max:10},
    floor_min: 0,
    require_elevator: false,
    require_parking: false,
    require_balcony: false,
    require_mamad: false,
    require_pets: false,
    require_renovated: false,
    blacklist_keywords: [],
    bonus_keywords: []
  });
  renderProfiles();
  document.getElementById(`profile-body-0`).classList.remove('hidden');
}

function deleteProfile(i) {
  if(confirm("האם אתה בטוח שברצונך למחוק את הפרופיל?")) {
    currentProfiles.splice(i, 1);
    renderProfiles();
    saveProfilesToServer();
  }
}

async function saveProfilesToServer() {
  try {
    const res = await fetch(`${API}/profiles`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(currentProfiles)
    });
    if (res.ok) {
      showToast('הפרופילים נשמרו בהצלחה', 'success');
    } else {
      showToast('שגיאה בשמירת פרופילים', 'error');
    }
  } catch(e) {
    showToast('שגיאה בתקשורת עם השרת', 'error');
  }
}

async function saveSource(src, enabled) {
  try {
    const config = await fetch(`${API}/config`).then(r => r.json());
    if(!config.sources) config.sources = {};
    config.sources[src] = enabled;
    await fetch(`${API}/config`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config)
    });
    showToast('הגדרות מקורות נשמרו', 'success');
  } catch(e) {
    showToast('שגיאה בשמירה', 'error');
  }
}


// ── Chat ─────────────────────────────────────────
function sendChat() {
  const inp = document.getElementById('chatInput');
  const msg = inp.value.trim();
  if (!msg || !ws || ws.readyState !== WebSocket.OPEN) return;

  addMessage('user', msg);
  inp.value = '';
  inp.style.height = 'auto';

  document.getElementById('sendBtn').disabled = true;
  ws.send(JSON.stringify({ type: 'chat', message: msg }));
}

function quickSend(msg) {
  document.getElementById('chatInput').value = msg;
  sendChat();
}

function addMessage(role, text) {
  const c = document.getElementById('chatMessages');
  const div = document.createElement('div');
  div.className = `msg ${role}`;

  const formatted = text.split('\n')
    .filter(l => l.trim())
    .map(l => `<p>${escapeHtml(l)}</p>`)
    .join('');

  div.innerHTML = `
    <div class="msg-av">${role === 'agent' ? '🤖' : '👤'}</div>
    <div class="msg-body">${formatted || `<p>${escapeHtml(text)}</p>`}</div>
  `;
  c.appendChild(div);
  scrollChat();
}

function scrollChat() {
  const c = document.getElementById('chatMessages');
  requestAnimationFrame(() => { c.scrollTop = c.scrollHeight; });
}

function handleKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendChat();
  }
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 110) + 'px';
}

// ── UI Utils ─────────────────────────────────────
function switchTab(name) {
  document.querySelectorAll('.tabitem').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(c => c.classList.remove('active'));
  document.getElementById(`tab-${name}`).classList.add('active');
  document.getElementById(`panel-${name}`).classList.add('active');
  if (name === 'listings') loadListings();
}

function addLog(msg, level = 'info') {
  const box = document.getElementById('logBox');
  const entry = document.createElement('div');
  entry.className = `log-line ${level}`;
  const time = new Date().toLocaleTimeString('he-IL', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  entry.textContent = `[${time}] ${msg}`;
  box.appendChild(entry);
  box.scrollTop = box.scrollHeight;
  while (box.children.length > 100) box.removeChild(box.firstChild);
}

function showToast(msg, type = 'info') {
  const cont = document.getElementById('toasts');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = msg;
  cont.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}
