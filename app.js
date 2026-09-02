const state = { papers: [], folder: 'uncategorized', search: '', section: '' };
const folderNames = { uncategorized: 'Uncategorized', good: 'Good fit', mby: 'Maybe', bad: 'Not a fit' };
const folderKickers = { uncategorized: 'Reading queue', good: 'Keepers', mby: 'On the fence', bad: 'Archive' };
const $ = (selector) => document.querySelector(selector);

async function request(url, options = {}) {
  const response = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed');
  return data;
}

function showToast(message) {
  const toast = $('#toast'); toast.textContent = message; toast.classList.add('show');
  clearTimeout(showToast.timer); showToast.timer = setTimeout(() => toast.classList.remove('show'), 2600);
}

function filteredPapers() {
  return state.papers.filter((paper) => paper.folder === state.folder && (!state.search || paper.name.toLowerCase().includes(state.search.toLowerCase())) && (!state.section || (paper.tags || []).includes(state.section)));
}

function renderCounts() {
  ['uncategorized', 'good', 'mby', 'bad'].forEach((folder) => { $(`#count-${folder}`).textContent = state.papers.filter((paper) => paper.folder === folder).length; });
  $('#paper-count').textContent = `${state.papers.length} paper${state.papers.length === 1 ? '' : 's'}`;
  $('#visible-count').textContent = filteredPapers().length;
}

function renderSectionFilter() {
  const current = state.section; const sections = [...new Set(state.papers.flatMap((paper) => paper.tags || []).filter(Boolean))].sort();
  $('#section-filter').innerHTML = '<option value="">All tags</option>' + sections.map((section) => `<option value="${escapeHtml(section)}">${escapeHtml(section)}</option>`).join('');
  $('#section-filter').value = current;
}

function escapeHtml(value) { return value.replace(/[&<>'"]/g, (character) => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;' }[character])); }

function readableFilename(filename) { return filename.replace(/\.(pdf|html?)$/i, '').replace(/[_-]+/g, ' '); }

function bibtexValue(value) { return String(value || '').replace(/[{}]/g, (character) => character === '{' ? '\\{' : '\\}'); }

function formatBibtex(key, citation) {
  const fields = [['author', citation.author], ['title', citation.title], ['journal', citation.journal], ['year', citation.year], ['volume', citation.volume], ['number', citation.number], ['pages', citation.pages], ['publisher', citation.publisher], ['doi', citation.doi], ['url', citation.url]];
  return `@${citation.entryType || 'misc'}{${key},\n${fields.filter(([, value]) => value).map(([name, value]) => `  ${name} = {${bibtexValue(value)}}`).join(',\n')}\n}`;
}

function paperCard(paper) {
  const isUncategorized = paper.folder === 'uncategorized';
  const fileType = paper.name.toLowerCase().endsWith('.pdf') ? 'PDF' : 'HTM';
  const action = `<button class="categorize-button" data-action="categorize">${isUncategorized ? 'Categorize' : 'Recategorize / edit'}</button>`;
  return `<article class="paper-card ${paper.lastOpened ? 'last-opened' : ''}" data-id="${paper.id}">
    <div class="pdf-badge">${fileType}</div><div><h3 class="paper-name">${escapeHtml(paper.actualTitle || readableFilename(paper.name))}</h3><p class="paper-filename">${escapeHtml(paper.name)}</p><p class="paper-location">${folderNames[paper.folder]}</p>${(paper.tags || []).map((tag) => `<span class="section-pill">${escapeHtml(tag)}</span>`).join(' ')}</div>
    <div class="paper-actions"><button class="open-button" data-action="open">Open paper ↗</button>${!isUncategorized ? '<button class="citation-button" data-action="citation">Copy BibTeX</button>' : ''}${action}<button class="delete-button" data-action="delete">Delete</button></div>
  </article>`;
}

function render() {
  $('#section-kicker').textContent = folderKickers[state.folder]; $('#section-title').textContent = folderNames[state.folder];
  const papers = filteredPapers(); renderCounts(); $('#paper-list').innerHTML = papers.map(paperCard).join(''); $('#empty-state').hidden = papers.length > 0;
}

async function load() {
  const data = await request('/api/papers'); state.papers = data.papers;
  await Promise.all(state.papers.filter((paper) => paper.doi).map(async (paper) => { try { const citation = await request(`/api/citation?doi=${encodeURIComponent(paper.doi)}`); paper.actualTitle = citation.title; } catch (error) { paper.actualTitle = ''; } }));
  renderSectionFilter(); render();
}

function allTags() { return [...new Set(state.papers.flatMap((paper) => paper.tags || []).filter(Boolean))].sort(); }

function openCategorizeModal(paper) {
  $('#categorize-modal').dataset.paperId = paper.id;
  $('#modal-title').textContent = paper.folder === 'uncategorized' ? 'Categorize paper' : 'Recategorize or edit paper';
  $('#modal-paper-name').textContent = paper.name;
    $('#modal-note').value = paper.note || '';
    $('#modal-doi').value = paper.doi || '';
  $('#modal-category').value = paper.folder;
  $('#tag-choices').innerHTML = allTags().map((tag) => `<label class="tag-choice"><input type="checkbox" value="${escapeHtml(tag)}" ${(paper.tags || []).includes(tag) ? 'checked' : ''}><span>${escapeHtml(tag)}</span></label>`).join('');
  $('#tag-new').value = ''; $('#categorize-modal').hidden = false; $('#modal-category').focus();
}

function closeCategorizeModal() { $('#categorize-modal').hidden = true; }

$('#paper-list').addEventListener('click', async (event) => {
  const button = event.target.closest('[data-action]'); if (!button) return; const card = button.closest('.paper-card'); const paper = state.papers.find((item) => item.id === card.dataset.id); if (!paper) return;
  if (button.dataset.action === 'categorize') { openCategorizeModal(paper); return; }
  if (button.dataset.action === 'open') { button.disabled = true; try { await request('/api/open-system', { method:'POST', body: JSON.stringify({ id: paper.id, name: paper.name, folder: paper.folder }) }); state.papers.forEach((item) => { item.lastOpened = item.id === paper.id ? new Date().toISOString() : null; }); render(); showToast('Opened with the default Windows application'); } catch (error) { showToast(error.message); button.disabled = false; } }
    if (button.dataset.action === 'citation') { button.disabled = true; button.textContent = 'Looking up...'; try { const data = await request(`/api/citation?title=${encodeURIComponent(paper.name)}&doi=${encodeURIComponent(paper.doi || '')}`); await navigator.clipboard.writeText(formatBibtex(paper.id, data)); showToast('BibTeX copied to clipboard'); } catch (error) { showToast(error.message); } finally { button.disabled = false; button.textContent = 'Copy BibTeX'; } }
    if (button.dataset.action === 'delete') { if (!window.confirm(`Delete "${paper.name}" permanently?`)) return; button.disabled = true; try { await request('/api/delete', { method: 'DELETE', body: JSON.stringify({ id: paper.id, name: paper.name, folder: paper.folder }) }); showToast('Paper deleted'); await load(); } catch (error) { showToast(error.message); button.disabled = false; } }
});
$('#categorize-modal').addEventListener('click', (event) => { if (event.target.dataset.close === 'true') closeCategorizeModal(); });
$('#tag-new').addEventListener('keydown', (event) => {
  if (event.key !== 'Enter') return;
  event.preventDefault(); const tag = event.target.value.trim(); if (!tag) return;
  const existing = [...$('#tag-choices').querySelectorAll('input')].find((input) => input.value.toLowerCase() === tag.toLowerCase());
  if (existing) existing.checked = true;
  else $('#tag-choices').insertAdjacentHTML('beforeend', `<label class="tag-choice"><input type="checkbox" value="${escapeHtml(tag)}" checked><span>${escapeHtml(tag)}</span></label>`);
  event.target.value = '';
});
$('#categorize-form').addEventListener('submit', async (event) => {
  event.preventDefault(); const paper = state.papers.find((item) => item.id === $('#categorize-modal').dataset.paperId); const target = $('#modal-category').value;
  if (!paper || !target) { showToast('Choose a category first'); return; }
  const tags = [...$('#tag-choices').querySelectorAll('input:checked')].map((input) => input.value);
  const button = $('#modal-submit'); button.disabled = true;
    try { await request('/api/categorize', { method: 'POST', body: JSON.stringify({ id: paper.id, name: paper.name, folder: paper.folder, target, note: $('#modal-note').value, tags, doi: $('#modal-doi').value.trim() }) }); closeCategorizeModal(); showToast(target === paper.folder ? 'Paper details saved' : `Moved to ${folderNames[target]}`); await load(); }
  catch (error) { showToast(error.message); } finally { button.disabled = false; }
});
$('#search').addEventListener('input', (event) => { state.search = event.target.value; render(); });
$('#section-filter').addEventListener('change', (event) => { state.section = event.target.value; render(); });
$('#refresh').addEventListener('click', () => load().catch((error) => showToast(error.message)));
document.querySelectorAll('.folder-link').forEach((button) => button.addEventListener('click', () => { state.folder = button.dataset.folder; document.querySelectorAll('.folder-link').forEach((item) => item.classList.toggle('active', item === button)); render(); }));
load().catch((error) => { $('#empty-state').hidden = false; $('#empty-state').querySelector('h3').textContent = 'Could not load the library'; showToast(error.message); });
