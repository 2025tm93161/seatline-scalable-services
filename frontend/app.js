const state = { events: [], selected: null, busy: false };
const element = (id) => document.getElementById(id);
const money = (cents) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(cents / 100);
const newKey = () => { element('request-key').value = crypto.randomUUID(); };
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]);
const eventImage = (event) => event.id === 'jazz-night' ? 'photo-1516280440614-37939bbacd81' : 'photo-1497366754035-f200968a6e72';

async function api(path, options = {}) {
  const response = await fetch(`/api/v1${path}`, options);
  const body = await response.json();
  return { response, body };
}

function totals() {
  element('total').textContent = money((state.selected?.price_cents || 0) * Number(element('quantity').value));
}

function selectEvent(event) {
  state.selected = event;
  element('selected-name').textContent = event.name;
  element('seat-total').textContent = `${event.available} / ${event.capacity} available`;
  const shown = Math.min(event.capacity, 100);
  const available = Math.round(event.available / event.capacity * shown);
  element('seat-map').innerHTML = Array.from({ length: shown }, (_, index) => `<div class="seat ${index >= available ? 'taken' : ''}" aria-hidden="true"></div>`).join('');
  document.querySelectorAll('.event').forEach((button) => {
    const selected = button.dataset.id === event.id;
    button.classList.toggle('selected', selected);
    button.setAttribute('aria-pressed', String(selected));
  });
  totals();
}

async function refresh() {
  const results = await Promise.all([api('/events'), api('/bookings')]);
  if (results.some(({ response }) => !response.ok)) throw new Error('A service is unavailable');
  state.events = results[0].body.filter((event) => !event.id.startsWith('evidence-'));
  element('events').innerHTML = state.events.map((event) => `<button class="event" data-id="${escapeHtml(event.id)}" aria-pressed="false"><img src="https://images.unsplash.com/${eventImage(event)}?w=400&auto=format&fit=crop" alt="${event.id === 'jazz-night' ? 'Live music microphone' : 'Creative meeting space'}"><span class="event-info"><small>GENERAL ADMISSION · LIVE SESSION</small><strong>${escapeHtml(event.name)}</strong><span class="event-meta"><span>${event.available} seats left</span><span>${money(event.price_cents)} / guest</span></span></span></button>`).join('');
  document.querySelectorAll('.event').forEach((button) => button.addEventListener('click', () => { selectEvent(state.events.find((event) => event.id === button.dataset.id)); newKey(); }));
  const chosen = state.events.find((event) => event.id === state.selected?.id) || state.events[0];
  if (chosen) selectEvent(chosen);
  const bookings = results[1].body.slice(-12).reverse();
  element('booking-count').textContent = `${results[1].body.length} total`;
  element('bookings').innerHTML = bookings.length ? bookings.map((booking) => `<tr><td title="${escapeHtml(booking.id)}">${escapeHtml(booking.id.slice(0, 13))}…</td><td><span class="badge ${escapeHtml(booking.state)}">${escapeHtml(booking.state.replaceAll('_', ' '))}</span></td><td>${money(booking.amount_cents)}</td><td>${escapeHtml(booking.reason || 'All transaction steps completed')}</td><td>${['PENDING', 'RESERVED', 'PAID', 'COMPENSATING', 'COMPENSATION_PENDING'].includes(booking.state) ? `<button data-recover="${escapeHtml(booking.id)}">Recover</button>` : '—'}</td></tr>`).join('') : '<tr><td colspan="5" class="empty">No reservations yet</td></tr>';
  document.querySelectorAll('[data-recover]').forEach((button) => button.addEventListener('click', async () => {
    button.disabled = true;
    try { await api(`/bookings/${button.dataset.recover}/recover`, { method: 'POST' }); await refresh(); }
    catch (error) { showResult(error.message, false); }
    finally { button.disabled = false; }
  }));
  element('status-dot').style.background = 'var(--green)';
  element('connection-label').textContent = 'Services online';
}

function showResult(message, success) {
  element('result').textContent = message;
  element('result').className = success ? 'success' : 'error';
}

element('booking-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (state.busy || !state.selected) return;
  state.busy = true;
  element('submit').disabled = true;
  showResult('Processing reservation…', true);
  try {
    const { response, body } = await api('/bookings', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': element('request-key').value }, body: JSON.stringify({ event_id: state.selected.id, quantity: Number(element('quantity').value), recipient: element('recipient').value, decline_payment: element('decline').checked, fail_notification: element('fail').checked }) });
    if (body.id) showResult(`${body.state.replaceAll('_', ' ')} · ${body.id}${response.headers.get('Idempotency-Replayed') ? ' · Replayed request' : ''}${body.reason ? ` · ${body.reason}` : ''}`, body.state === 'CONFIRMED');
    else showResult(body.error?.message || 'Reservation failed', false);
    await refresh();
  } catch (error) { showResult(`${error.message}. The outcome may be unknown; retry with the same key.`, false); }
  finally { state.busy = false; element('submit').disabled = false; }
});
element('refresh').addEventListener('click', () => refresh().catch((error) => showResult(error.message, false)));
element('new-key').addEventListener('click', newKey);
element('quantity').addEventListener('input', totals);
element('increase').addEventListener('click', () => { element('quantity').value = Math.min(10, Number(element('quantity').value) + 1); totals(); });
element('decrease').addEventListener('click', () => { element('quantity').value = Math.max(1, Number(element('quantity').value) - 1); totals(); });
newKey();
refresh().catch((error) => { element('connection-label').textContent = 'Connection lost'; showResult(error.message, false); });