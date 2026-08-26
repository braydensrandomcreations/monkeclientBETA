const input = document.querySelector('#game-search');
const grid = document.querySelector('#game-grid');
const count = document.querySelector('#game-count');
const emptyState = document.querySelector('#empty-state');
const adminModal = document.querySelector('#admin-modal');
const adminTrigger = document.querySelector('#admin-trigger');
const loginView = document.querySelector('#login-view');
const adminView = document.querySelector('#admin-view');
const sortHint = document.querySelector('#sort-hint');
const sortStatus = document.querySelector('#sort-status');
const collectionSection = document.querySelector('#collection-section');
const collectionGrid = document.querySelector('#collection-grid');

let isAdmin = false;
let currentGames = [];
let draggedCard = null;
let draggedContainer = null;

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;',
  }[character]));
}

function gameCardHtml(game) {
  const isFeatured = Boolean(game.collection);
  return `
    <a class="game-card" data-title="${escapeHtml(game.title.toLowerCase())}" data-id="${escapeHtml(game.id)}" href="${escapeHtml(game.link)}">
      <div class="card-image">
        <img src="${escapeHtml(game.image)}" alt="${escapeHtml(game.title)}">
        <span class="play-icon">▶</span>
        <button
          class="collection-toggle"
          type="button"
          data-id="${escapeHtml(game.id)}"
          aria-pressed="${isFeatured ? 'true' : 'false'}"
          title="${isFeatured ? 'Remove from collection' : 'Add to collection'}"
        >★</button>
      </div>
      <div class="card-info"><span>${escapeHtml(game.category)}</span><strong>${escapeHtml(game.title)}</strong></div>
    </a>
  `;
}

function renderGames(games) {
  if (!grid) return;
  currentGames = games;
  grid.innerHTML = games.map(gameCardHtml).join('');

  const collectionGames = games.filter((game) => game.collection);
  if (collectionGrid) {
    collectionGrid.innerHTML = collectionGames.map(gameCardHtml).join('');
  }
  if (collectionSection) {
    collectionSection.hidden = collectionGames.length === 0;
  }

  filterGames();
  updateDragMode();
}

function filterGames() {
  if (!input || !grid || !count || !emptyState) return;
  const searchTerm = input.value.trim().toLowerCase();
  const games = [...grid.querySelectorAll('.game-card')];
  let visibleGames = 0;
  games.forEach((game) => {
    const isMatch = game.dataset.title.includes(searchTerm);
    game.hidden = !isMatch;
    if (isMatch) visibleGames += 1;
  });
  count.textContent = visibleGames;
  emptyState.hidden = visibleGames !== 0;
}

async function loadGames() {
  if (!grid) return;
  const response = await fetch('/api/games');
  if (!response.ok) throw new Error('Could not load games.');
  renderGames(await response.json());
}

function openAdmin() {
  adminModal.hidden = false;
  document.body.classList.add('modal-open');
  document.querySelector('#login-form input')?.focus();
}

function closeAdmin() {
  adminModal.hidden = true;
  document.body.classList.remove('modal-open');
}

async function checkSession() {
  const response = await fetch('/api/session');
  const session = await response.json();
  isAdmin = session.authenticated;
  loginView.hidden = session.authenticated;
  adminView.hidden = !session.authenticated;
  adminTrigger.textContent = session.authenticated ? 'Manage games' : 'Admin login';
  updateDragMode();
}

function updateDragMode() {
  document.querySelectorAll('.game-card').forEach((card) => {
    card.draggable = isAdmin;
    card.classList.toggle('is-sortable', isAdmin);
  });
  document.body.classList.toggle('show-admin-controls', isAdmin);
  const hasMultipleGames = grid && grid.querySelectorAll('.game-card').length > 1;
  if (sortHint) sortHint.hidden = !isAdmin || !hasMultipleGames;
}

function getDragAfterElement(container, x, y) {
  const cards = [...container.querySelectorAll('.game-card:not(.dragging)')];
  let closest = { distance: Number.POSITIVE_INFINITY, element: null, centerX: 0, centerY: 0 };
  for (const card of cards) {
    const box = card.getBoundingClientRect();
    const centerX = box.left + box.width / 2;
    const centerY = box.top + box.height / 2;
    const distance = Math.hypot(x - centerX, y - centerY);
    if (distance < closest.distance) {
      closest = { distance, element: card, centerX, centerY };
    }
  }
  if (!closest.element) return null;
  const isBefore = y < closest.centerY - 4 ||
    (Math.abs(y - closest.centerY) <= 4 && x < closest.centerX);
  return isBefore ? closest.element : closest.element.nextElementSibling;
}

async function persistOrder(ids) {
  if (sortStatus) sortStatus.textContent = 'Saving…';
  try {
    const response = await fetch('/api/games/reorder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ order: ids }),
    });
    if (!response.ok) throw new Error('Reorder failed.');
    const games = await response.json();
    // Re-render from the canonical server order so the main grid and the
    // collection strip both stay in sync, even when only one of them moved.
    renderGames(games);
    if (sortStatus) {
      sortStatus.textContent = 'Saved';
      setTimeout(() => { if (sortStatus.textContent === 'Saved') sortStatus.textContent = ''; }, 1500);
    }
  } catch (err) {
    if (sortStatus) sortStatus.textContent = "Couldn't save order";
    renderGames(currentGames);
  }
}

function setupDragSort(container) {
  if (!container) return;

  container.addEventListener('dragstart', (event) => {
    const card = event.target.closest('.game-card');
    if (!card || !isAdmin || !container.contains(card)) return;
    draggedCard = card;
    draggedContainer = container;
    requestAnimationFrame(() => card.classList.add('dragging'));
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', card.dataset.id || '');
  });

  container.addEventListener('dragover', (event) => {
    if (!isAdmin || !draggedCard || draggedContainer !== container) return;
    event.preventDefault();
    const afterElement = getDragAfterElement(container, event.clientX, event.clientY);
    if (afterElement == null) {
      container.appendChild(draggedCard);
    } else if (afterElement !== draggedCard) {
      container.insertBefore(draggedCard, afterElement);
    }
  });

  container.addEventListener('drop', (event) => {
    if (!isAdmin || !draggedCard || draggedContainer !== container) return;
    event.preventDefault();
  });

  container.addEventListener('dragend', () => {
    if (!draggedCard || draggedContainer !== container) return;
    draggedCard.classList.remove('dragging');
    const ids = [...container.querySelectorAll('.game-card')].map((card) => card.dataset.id);
    draggedCard = null;
    draggedContainer = null;
    persistOrder(ids);
  });
}

setupDragSort(grid);
setupDragSort(collectionGrid);

document.addEventListener('click', async (event) => {
  const toggle = event.target.closest('.collection-toggle');
  if (!toggle) return;
  event.preventDefault();
  event.stopPropagation();
  if (!isAdmin) return;
  const id = toggle.dataset.id;
  const nextState = toggle.getAttribute('aria-pressed') !== 'true';
  toggle.disabled = true;
  try {
    const response = await fetch('/api/games/collection', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, collection: nextState }),
    });
    if (!response.ok) throw new Error('Toggle failed.');
    renderGames(await response.json());
  } catch (err) {
    toggle.disabled = false;
  }
});

if (input) input.addEventListener('input', filterGames);
if (adminTrigger) adminTrigger.addEventListener('click', openAdmin);
document.querySelector('#modal-close')?.addEventListener('click', closeAdmin);
adminModal?.addEventListener('click', (event) => {
  if (event.target === adminModal) closeAdmin();
});
document.addEventListener('keydown', (event) => {
  if (event.key === '/' && document.activeElement !== input) {
    event.preventDefault();
    input?.focus();
  }
  if (event.key === 'Escape' && adminModal && !adminModal.hidden) closeAdmin();
});

document.querySelector('#login-form')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const error = document.querySelector('#login-error');
  error.textContent = '';
  const response = await fetch('/api/login', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(Object.fromEntries(new FormData(event.target))) });
  if (!response.ok) {
    error.textContent = (await response.json()).error;
    return;
  }
  event.target.reset();
  await checkSession();
});

document.querySelector('#game-form')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const error = document.querySelector('#game-error');
  const success = document.querySelector('#game-success');
  error.textContent = '';
  success.textContent = '';
  const formData = new FormData(event.target);
  const payload = Object.fromEntries(formData);
  payload.collection = formData.get('collection') === 'on';
  const response = await fetch('/api/games', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
  const result = await response.json();
  if (!response.ok) {
    error.textContent = result.error;
    return;
  }
  event.target.reset();
  success.textContent = `${result.title} is live in the arcade.`;
  await loadGames();
});

document.querySelector('#logout-button')?.addEventListener('click', async () => {
  await fetch('/api/logout', {method: 'POST'});
  await checkSession();
});

loadGames().catch(() => {});
checkSession().catch(() => {});
